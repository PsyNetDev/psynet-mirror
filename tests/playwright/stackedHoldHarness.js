const { expect } = require("./fixtures");
const {
  assertNoBackendError,
  beginExperiment,
  enterTimelineAfterGateway,
  installTimelineHoldReleaseProbe,
  installTimelineHoldReleaseProbeOnContext,
  readTimelineHoldReleaseProbe,
  silenceTimelineHoldSafetyPoll,
  wrapTimelineHoldResumeProbe,
  startExperiment,
  startParticipantRequestTracker,
  startTimelineHoldSocketTracker,
  stopExperiment,
  summarizeParticipantRequests,
  requestHandlerMs,
  requestTimingDetail,
  unexpectedBlockingRequests,
  waitForHeldParticipantToResume,
  waitForTimelinePageReady,
  withFreshParticipantIds,
  isDestroyedExecutionContext,
  isInplaceTimelineModeEnabled
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const ENTRY_REQUEST_MAX_MS = 2500;
const START_PAGE_MAX_MS = 6000;
// Dallinger `@db.serialized` retries POST /participant with
// ``random.expovariate(0.5)`` sleep (mean 2s) after a conflict with the
// partner's GET /timeline. One unlucky retry already exceeds 6000ms. This
// budget is only for overlapping signups; linger/spread/GET /timeline floors
// stay 2200/1500/2500.
const SERIALIZED_SIGNUP_MAX_MS = 15000;
const BLOCKING_REQUEST_MS = 4000;
// Fast waiters leave in ~0.2–0.8s after last paint. Two waiters leaving
// together can each spend ~1.1s rendering the next page; the second sits in
// the gunicorn listen-queue. Overlay linger is wake→end wallclock, including
// that wait: it is real for the participant. Compare it with
// max(2200, Server-Timing app + 500). A missed wake still cannot hide: tests
// silence the 2s safety poll and assert the resume is a server wake.
// Summaries print queue~ so a long linger can be split into handler vs pool
// occupancy; do not subtract queue from linger or waiter-release spread.
const PARTNER_HOLD_RELEASE_MAX_MS = 2200;
const HOLD_RESUME_OVERLAY_SLACK_MS = 500;
const WAITER_RELEASE_SPREAD_MAX_MS = 1500;
const SETTLE_HOLD_MS = 3500;
const ACTION_PROMPT = "Choose your action";
const RESULTS_PROMPT = "Everyone is ready";
const PAIR_HOLD_TEXT = "Waiting for your partner";
const GROUP_HOLD_TEXT = "Waiting for your group";
const RELEASE_RESUME_REASONS = new Set(["server notification", "queued hold wake"]);
const LATE_ARRIVAL_RESUME_REASONS = new Set([
  ...RELEASE_RESUME_REASONS,
  "websocket connection"
]);

function entryPathRequests(records) {
  // GET /timeline (and load-participant) use the 2500ms handler budget.
  // POST /participant does not: Dallinger `@db.serialized` serializes
  // concurrent signups and retries with expovariate sleep. Overlapping
  // consent→timeline uses SERIALIZED_SIGNUP_MAX_MS. Sequential starts still
  // have START_PAGE_MAX_MS.
  return records.filter((record) =>
    ["load_participant", "timeline_document"].includes(record.kind)
  );
}

function overlayWakeAndEndMs(probe, resumeLog, sinceMs) {
  // Poller and last-arrival can both wake a stacked hold. First-wake→last-end
  // spans those hops and looks like overlay linger. Pair the last end with
  // the last wake that preceded it.
  const wakes = (resumeLog || []).filter(
    (entry) => entry.kind === "wake" && (sinceMs == null || entry.atMs >= sinceMs)
  );
  const ends = (resumeLog || []).filter(
    (entry) =>
      entry.kind === "holdEnded" && (sinceMs == null || entry.atMs >= sinceMs)
  );
  if (wakes.length && ends.length) {
    const lastEndAtMs = ends[ends.length - 1].atMs;
    const lastWake = [...wakes]
      .reverse()
      .find((entry) => entry.atMs <= lastEndAtMs);
    if (lastWake != null) {
      return { lingerMs: lastEndAtMs - lastWake.atMs, lastWakeAtMs: lastWake.atMs };
    }
  }
  if (probe.holdEndedAtMs != null && probe.wakeReceivedAtMs != null) {
    return {
      lingerMs: probe.holdEndedAtMs - probe.wakeReceivedAtMs,
      lastWakeAtMs: probe.wakeReceivedAtMs
    };
  }
  return { lingerMs: null, lastWakeAtMs: null };
}

function overlayEndingHoldResumePosts(holdResumePosts, lastWakeAtMs) {
  if (lastWakeAtMs == null) {
    return holdResumePosts;
  }
  const overlapping = holdResumePosts.filter((post) => {
    const startedAtMs = post.startedAtMs ?? 0;
    const endedAtMs = startedAtMs + (post.durationMs ?? 0);
    return endedAtMs >= lastWakeAtMs;
  });
  return overlapping.length ? overlapping : holdResumePosts;
}

function lastArriverWorkRecord(lastEntry) {
  const records = lastEntry?.tracker?.records || [];
  if (!records.length) {
    return null;
  }
  const sinceMs = lastArriverClock(lastEntry).clickedAtMs;
  const recent = records.filter((record) => (record.startedAtMs ?? 0) >= (sinceMs ?? 0));
  const pool = recent.length ? recent : records;
  const posts = pool.filter(
    (record) => record.kind === "response" && record.holdResume !== true
  );
  if (posts.length) {
    return posts[posts.length - 1];
  }
  const timelines = pool.filter(
    (record) =>
      record.kind === "timeline_document" || record.kind === "timeline_json"
  );
  // A last-arrival GET can 302 after page_uuid advances during render. The
  // first GET is the grouping work; the follow-up 200 is only the HTML body.
  return timelines[0] || null;
}

function requestFinishedAtMs(record) {
  if (record?.finishedAtMs != null) {
    return record.finishedAtMs;
  }
  if (record?.startedAtMs != null && record?.durationMs != null) {
    return record.startedAtMs + record.durationMs;
  }
  return null;
}

function lastArriverReleaseAtMs(lastEntry) {
  const finishedAtMs = requestFinishedAtMs(lastArriverWorkRecord(lastEntry));
  if (finishedAtMs != null) {
    return finishedAtMs;
  }
  return lastArriverClock(lastEntry).paintedAtMs;
}

function arrivalWorkEntry(arrival) {
  return arrival.entry || arrival;
}

function pickConcurrentLastArriver(arrivals) {
  // A skipper filled the barrier. A slower first-paint hold is a waiter,
  // even if Playwright recorded a later paint time after the overlay left.
  if (!arrivals.length) {
    throw new Error("pickConcurrentLastArriver needs at least one arrival");
  }
  const skippers = arrivals.filter((arrival) => !arrival.held);
  const pool = skippers.length ? skippers : arrivals;
  return pool.reduce((best, current) =>
    lastArriverReleaseAtMs(arrivalWorkEntry(current)) >=
    lastArriverReleaseAtMs(arrivalWorkEntry(best))
      ? current
      : best
  );
}

function responsesOverlappingLastArriver(records, sinceMs) {
  // Websocket onOpen can start a hold-resume POST before the last arriver
  // clicks. Count that POST if it finished after they started.
  return records.filter((record) => {
    if (record.kind !== "response") {
      return false;
    }
    const finishedAtMs = requestFinishedAtMs(record);
    if (finishedAtMs != null) {
      return finishedAtMs >= sinceMs;
    }
    return (record.startedAtMs ?? 0) >= sinceMs;
  });
}

function overlayLingerBudgetMs(holdResumePosts) {
  const posts = Array.isArray(holdResumePosts)
    ? holdResumePosts
    : holdResumePosts
      ? [holdResumePosts]
      : [];
  const postMs = posts.reduce(
    (maxMs, post) => Math.max(maxMs, requestHandlerMs(post)),
    0
  );
  return Math.max(
    PARTNER_HOLD_RELEASE_MAX_MS,
    postMs + HOLD_RESUME_OVERLAY_SLACK_MS
  );
}

function publishedWakeTokens(holdFrames) {
  const tokens = [];
  for (const frame of holdFrames) {
    const jsonStart = frame.indexOf("{");
    if (jsonStart < 0) {
      continue;
    }
    try {
      const payload = JSON.parse(frame.slice(jsonStart));
      for (const target of payload.targets || []) {
        if (target.wake_token) {
          tokens.push(target.wake_token);
        }
      }
    } catch {
      // Keep going; the summary still includes the raw frame.
    }
  }
  return tokens;
}

function requestsSince(records, startedAtMs, kind = null) {
  return records.filter(
    (record) =>
      (record.startedAtMs ?? 0) >= startedAtMs &&
      (kind == null || record.kind === kind)
  );
}

function responsesSince(records, startedAtMs) {
  return requestsSince(records, startedAtMs, "response");
}

function lastArriverClock(lastEntry) {
  const kind = lastEntry.start?.kind === "choice" ? "choice" : "entry";
  const clickedAtMs =
    lastEntry.start?.clickedAtMs ?? lastEntry.start?.consentClickedAtMs;
  const paintedAtMs =
    lastEntry.start?.paintedAtMs ?? lastEntry.start?.timelineAtMs;
  const clickToPaintMs =
    lastEntry.start?.clickToPaintMs ??
    lastEntry.start?.consentToTimelineMs ??
    paintedAtMs - clickedAtMs;
  return { kind, clickedAtMs, paintedAtMs, clickToPaintMs };
}

function holdReleaseSummary({
  clickToPaintMs,
  afterClickMs,
  afterPaintMs,
  afterReleaseMs = null,
  clockKind = "entry",
  holdResumePostMs,
  holdResumePost = null,
  lastArriverWork = null,
  extraTimelineGets,
  probe,
  resumeRequests,
  resumeLog = [],
  holdFrames = [],
  waitingWakeToken = null,
  overlayLingerMs: rawLingerMs = null,
  lingerBudgetMs = null,
  holdResumePostCount = null,
  label = "waiter"
}) {
  const reasons = (probe.resumeReasons || [])
    .map((entry) => entry.reason)
    .join(",") || "none";
  const wake = probe.wakeReason
    ? `wake ${probe.wakeReason}`
    : "no hold wake event";
  const holdResumeDetail = requestTimingDetail(
    holdResumePost,
    holdResumePostMs
  );
  const lastWorkKind = lastArriverWork
    ? `${lastArriverWork.method} ${lastArriverWork.path}`
    : "work";
  const lastWorkDetail = requestTimingDetail(lastArriverWork, clickToPaintMs);
  const lingerBudget = lingerBudgetMs ?? overlayLingerBudgetMs(holdResumePost);
  const lingerLabel =
    rawLingerMs == null
      ? "overlay linger missing"
      : `overlay linger ${Math.round(rawLingerMs)}ms`;
  const responseNotes =
    resumeLog
      .filter((entry) => entry.kind)
      .map((entry) => {
        if (entry.kind === "approved") {
          return `approved ${entry.pageType} fragment=${entry.hasFragment} hold=${entry.hasHold} requiresReload=${entry.requiresReload} inplace=${entry.inplace}`;
        }
        if (entry.kind === "rejected") {
          return `rejected ${entry.message || ""}`;
        }
        return entry.kind;
      })
      .join("; ") || "no response handler notes";
  const clickLabel =
    clockKind === "choice" ? "choice→paint" : "consent→timeline";
  const afterPaintLabel =
    clockKind === "choice" ? "last paint" : "last timeline";
  const afterClickLabel =
    clockKind === "choice" ? "after last choice" : "after last consent";
  const afterReleaseNote =
    afterReleaseMs == null
      ? ""
      : `; ${Math.round(afterReleaseMs)}ms after last arriver ${lastWorkKind} finished`;
  return (
    `${label}: last arriver ${clickLabel} ${Math.round(clickToPaintMs)}ms ` +
    `(${lastWorkKind} ${lastWorkDetail}); ` +
    `waiter ${Math.round(afterPaintMs)}ms after ${afterPaintLabel}` +
    `${afterReleaseNote} ` +
    `(${Math.round(afterClickMs)}ms ${afterClickLabel}; ` +
    `hold-resume POST ${holdResumeDetail}; ${lingerLabel}; overlay budget ${Math.round(lingerBudget)}ms; hold-resume POSTs ${holdResumePostCount ?? (holdResumePost ? 1 : 0)}; extra GET /timeline ${extraTimelineGets}; ` +
    `inplace=${isInplaceTimelineModeEnabled()}; ` +
    `${wake}; resumes ${reasons}; ${responseNotes}; ` +
    `hold resumes ${probe.nextPageHoldResumes?.length || 0}; ` +
    `waiting token ${waitingWakeToken || "missing"}; ` +
    `published ${publishedWakeTokens(holdFrames).join(",") || "none"}; ` +
    `requests ${summarizeParticipantRequests(resumeRequests)})`
  );
}

function assertEntryWasResponsive(
  entry,
  label,
  { signupMaxMs = START_PAGE_MAX_MS } = {}
) {
  const summary = summarizeParticipantRequests(entry.tracker.records);
  const entryRequests = entryPathRequests(entry.tracker.records);
  expect(
    [200, 503].includes(entry.timeline.status),
    `${label} first GET /timeline status ${entry.timeline.status} (${summary})`
  ).toBe(true);
  expect(entry.timeline.busy, `${label} first GET /timeline was busy (${summary})`).toBe(
    false
  );
  expect(
    entry.timeline.busyPage,
    `${label} first GET /timeline rendered a busy page (${summary})`
  ).toBe(false);
  expect(
    unexpectedBlockingRequests(entryRequests, ENTRY_REQUEST_MAX_MS),
    `${label} unexpected entry blocking: ${summary}`
  ).toEqual([]);
  const createParticipant = entry.tracker.records.find(
    (record) => record.kind === "create_participant"
  );
  if (createParticipant != null) {
    expect(
      createParticipant.durationMs,
      `${label} POST /participant took ${Math.round(createParticipant.durationMs)}ms (${summary})`
    ).toBeLessThan(signupMaxMs);
  }
  const grouping = lastArriverWorkRecord(entry);
  if (grouping != null) {
    expect(
      requestHandlerMs(grouping),
      `${label} grouping ${grouping.method} ${grouping.path} ${grouping.status} took ${Math.round(requestHandlerMs(grouping))}ms (${summary})`
    ).toBeLessThan(ENTRY_REQUEST_MAX_MS);
  }
  expect(
    entry.timeline.durationMs,
    `${label} GET /timeline HTML took ${Math.round(entry.timeline.durationMs)}ms (${summary})`
  ).toBeLessThan(ENTRY_REQUEST_MAX_MS);
  expect(
    entry.start.consentToTimelineMs,
    `${label} stayed on Starting experiment... for ${entry.start.consentToTimelineMs}ms (${summary})`
  ).toBeLessThan(signupMaxMs);
}

function silenceHoldSafetyPollOnNewDocuments() {
  // Runs in every document, including legacy hold-resume reloads. A later
  // beginTimelineHold would otherwise schedule a fresh 2s poll while a
  // concurrent last arriver is still in serialized POST /participant.
  const silence = (psynet) => {
    if (!psynet || psynet.__psynetHoldSafetyPollSilenced) {
      return;
    }
    psynet.scheduleTimelineHoldCheck = function (target) {
      if (target && target.resumeRequested) {
        target.resumeRequested = false;
        setTimeout(() => psynet.resumeTimelineHold("queued hold wake"), 0);
      }
      if (target) {
        clearTimeout(target.safetyTimer);
        target.safetyTimer = null;
        if (target.hold) {
          target.hold.safety_poll_ms = 60000;
        }
      }
    };
    psynet.__psynetHoldSafetyPollSilenced = true;
  };
  let currentPsynet = window.psynet;
  Object.defineProperty(window, "psynet", {
    configurable: true,
    enumerable: true,
    get() {
      return currentPsynet;
    },
    set(value) {
      currentPsynet = value;
      silence(value);
    }
  });
  silence(currentPsynet);
}

async function createHoldSession(browser, recruitmentUrl, label) {
  const context = await browser.newContext();
  const resumeLog = [];
  await context.exposeBinding("__psynetRecordHoldResume", (_source, entry) => {
    resumeLog.push({
      ...(entry || {}),
      atMs: Date.now()
    });
  });
  await context.addInitScript(silenceHoldSafetyPollOnNewDocuments);
  await installTimelineHoldReleaseProbeOnContext(context);
  const page = await beginExperiment(
    await context.newPage(),
    context,
    withFreshParticipantIds(recruitmentUrl, label)
  );
  return {
    label,
    context,
    page,
    sockets: startTimelineHoldSocketTracker(page),
    resumeLog,
    entry: null,
    waitingWakeToken: null,
    resumePromise: null
  };
}

async function closeHoldSessions(sessions) {
  for (const session of sessions) {
    session.entry?.tracker.stop();
    session.choiceTracker?.stop();
    session.sockets?.stop();
    await session.context.close();
  }
}

async function startHoldExperiment(browser, experimentDir, labels, options = {}) {
  const env = { ...(options.env || {}) };
  if (env.PSYNET_LEGACY_DEBUG_GUNICORN_THREADS == null) {
    // Sequential last-arrival needs n HTTP slots (GET + waiter POSTs) plus
    // one spare so a waiter Redis subscribe is not on the last-arrival SQL
    // worker. Concurrent last arrivals occupy two GET /timeline workers at
    // once, so tests use n + 2. Otherwise a hold-resume POST sits in the
    // listen queue and overlay linger includes that wait.
    env.PSYNET_LEGACY_DEBUG_GUNICORN_THREADS = String(
      Math.max(labels.length + 2, 2)
    );
  }
  const experiment = startExperiment(experimentDir, { ...options, env });
  const recruitmentUrl = await experiment.urlPromise;
  const sessions = [];
  try {
    for (const label of labels) {
      sessions.push(await createHoldSession(browser, recruitmentUrl, label));
    }
  } catch (error) {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
    throw error;
  }
  return { experiment, sessions, recruitmentUrl };
}

async function silenceVisibleHoldSafetyPoll(page, timeout = 5000) {
  // Server-rendered hold HTML can paint the indicator before
  // ``psynet.timelineHold`` attaches. A last arriver can also clear the
  // overlay during that gap. Wait for the controller, or treat a gone
  // indicator as an already-cleared hold.
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      if (
        (await page.locator("#psynet-timeline-hold-indicator").count()) === 0
      ) {
        return "cleared";
      }
      if (await silenceTimelineHoldSafetyPoll(page)) {
        return "silenced";
      }
    } catch (error) {
      if (isDestroyedExecutionContext(error)) {
        return "cleared";
      }
      throw error;
    }
    const remaining = Math.max(50, deadline - Date.now());
    await page
      .waitForFunction(
        () =>
          Boolean(
            !document.getElementById("psynet-timeline-hold-indicator") ||
              (window.psynet && window.psynet.timelineHold)
          ),
        { timeout: remaining }
      )
      .catch(() => {});
  }
  return "missing";
}

async function armVisibleHold(
  session,
  { holdText, prompt, timeout = STEP_TIMEOUT_MS }
) {
  // A concurrent last arrival can reload this waiter before the probe is
  // armed. Treat that as a cleared hold instead of failing evaluate.
  const stillHeld = await waitForHoldOrPrompt(session.page, {
    holdText,
    prompt,
    timeout
  });
  if (!stillHeld) {
    return false;
  }
  try {
    await installTimelineHoldReleaseProbe(session.page);
    const wrapped = await wrapTimelineHoldResumeProbe(session.page);
    if (
      (await session.page.locator("#psynet-timeline-hold-indicator").count()) ===
      0
    ) {
      return false;
    }
    expect(
      wrapped,
      `${session.label} hold-resume probe was not attached`
    ).toBe(true);
    const silenceState = await silenceVisibleHoldSafetyPoll(session.page);
    if (silenceState === "cleared") {
      return false;
    }
    expect(
      silenceState,
      `${session.label} hold safety poll was not running`
    ).toBe("silenced");
    session.waitingWakeToken = await session.page.evaluate(
      () => psynet.timelineHold?.hold?.wake_token || null
    );
    session.resumeSinceMs = Date.now();
  } catch (error) {
    if (!isDestroyedExecutionContext(error)) {
      throw error;
    }
    return false;
  }
  session.resumePromise = waitForHeldParticipantToResume(session.page, {
    prompt,
    timeout,
    resumeLog: session.resumeLog
  });
  return true;
}

async function assertStillHeld(session, holdText) {
  await expect(
    session.page.locator("#psynet-timeline-hold-indicator")
  ).toBeVisible();
  await expect(
    session.page.locator(".psynet-timeline-hold-message")
  ).toContainText(holdText);
}

async function enterWaitingHold(session, { holdText, prompt, timeout = STEP_TIMEOUT_MS }) {
  session.entry = await enterTimelineAfterGateway(session.page, timeout);
  assertEntryWasResponsive(session.entry, session.label);
  expect(session.entry.paint.type).toBe("_BarrierHoldPage");
  expect(session.entry.paint.showsHold).toBe(true);
  await waitForTimelinePageReady(session.page, timeout);
  const armed = await armVisibleHold(session, { holdText, prompt, timeout });
  expect(armed, `${session.label} expected a lasting hold`).toBe(true);
  return session.entry;
}

async function enterSkippingHold(session, { timeout = STEP_TIMEOUT_MS } = {}) {
  session.entry = await enterTimelineAfterGateway(session.page, timeout);
  assertEntryWasResponsive(session.entry, session.label);
  expect(
    session.entry.paint.type,
    `${session.label} first timeline HTML was not a ModularPage (status=${session.entry.timeline.status}, type=${session.entry.paint.type})`
  ).toBe("ModularPage");
  expect(session.entry.paint.showsHold).toBe(false);
  await waitForTimelinePageReady(session.page, timeout);
  await expect(session.page.locator("#main-body")).toContainText(ACTION_PROMPT, {
    timeout
  });
  await expect(session.page.locator("#psynet-timeline-hold-indicator")).toHaveCount(
    0
  );
  await expect(session.page.locator("body")).not.toHaveClass(/timeline-held/);
  return session.entry;
}

async function armChoiceHold(
  session,
  {
    holdText,
    prompt,
    buttonName = "go",
    timeout = STEP_TIMEOUT_MS
  }
) {
  session.choiceTracker = startParticipantRequestTracker(session.page);
  await session.page.getByRole("button", { name: buttonName }).click();
  const armed = await armVisibleHold(session, { holdText, prompt, timeout });
  expect(armed, `${session.label} expected a lasting post-choice hold`).toBe(
    true
  );
}

async function waitForHoldOrPrompt(
  page,
  { holdText, prompt, timeout = STEP_TIMEOUT_MS }
) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const remaining = Math.max(250, deadline - Date.now());
    try {
      await page.waitForFunction(
        ({ expectedPrompt, expectedHold }) => {
          const body = document.getElementById("main-body")?.innerText || "";
          const hold =
            document.querySelector(".psynet-timeline-hold-message")?.innerText ||
            "";
          const indicator = document.getElementById(
            "psynet-timeline-hold-indicator"
          );
          return Boolean(
            (indicator && hold.includes(expectedHold)) ||
              (body.includes(expectedPrompt) && !indicator)
          );
        },
        { expectedPrompt: prompt, expectedHold: holdText },
        { timeout: remaining }
      );
      return (await page.locator("#psynet-timeline-hold-indicator").count()) > 0;
    } catch (error) {
      if (!isDestroyedExecutionContext(error)) {
        throw error;
      }
      await page.waitForLoadState("domcontentloaded").catch(() => {});
    }
  }
  throw new Error("Timed out waiting for a hold chip or the next prompt.");
}

async function attachClearedHoldResume(
  session,
  { wakeToken, prompt = ACTION_PROMPT, timeout }
) {
  if (wakeToken) {
    session.waitingWakeToken = wakeToken;
  }
  await wrapTimelineHoldResumeProbe(session.page);
  await assertActionOrPrompt(session.page, prompt, timeout);
  const probe = await readTimelineHoldReleaseProbe(session.page);
  const sinceMs = session.resumeSinceMs;
  const logged = [...(session.resumeLog || [])]
    .reverse()
    .find(
      (entry) =>
        entry.reason && (sinceMs == null || entry.atMs >= sinceMs)
    );
  const endedAtMs =
    probe.holdEndedAtMs != null &&
    (sinceMs == null || probe.holdEndedAtMs >= sinceMs)
      ? probe.holdEndedAtMs
      : probe.previousHoldEndedAtMs != null &&
          (sinceMs == null || probe.previousHoldEndedAtMs >= sinceMs)
        ? probe.previousHoldEndedAtMs
        : null;
  const resumedAtMs = endedAtMs || logged?.atMs;
  if (resumedAtMs == null) {
    throw new Error(
      `${session.label} holdEndedAtMs missing after the hold cleared`
    );
  }
  session.resumePromise = Promise.resolve({
    resumedAtMs
  });
}

function choiceHoldStart(clickedAtMs, paintedAtMs) {
  return {
    kind: "choice",
    clickedAtMs,
    paintedAtMs,
    clickToPaintMs: paintedAtMs - clickedAtMs,
    consentClickedAtMs: clickedAtMs,
    timelineAtMs: paintedAtMs
  };
}

async function submitChoiceMaybeHeld(
  session,
  {
    holdText,
    prompt,
    buttonName = "go",
    timeout = STEP_TIMEOUT_MS
  }
) {
  session.choiceTracker = startParticipantRequestTracker(session.page);
  const clickedAtMs = Date.now();
  await session.page.getByRole("button", { name: buttonName }).click();
  await wrapTimelineHoldResumeProbe(session.page);
  const stillHeld = await waitForHoldOrPrompt(session.page, {
    holdText,
    prompt,
    timeout
  });
  const doneAtMs = Date.now();
  const start = choiceHoldStart(clickedAtMs, doneAtMs);
  if (stillHeld) {
    session.resumeSinceMs = clickedAtMs;
    if (await armVisibleHold(session, { holdText, prompt, timeout })) {
      return { held: true, start, tracker: session.choiceTracker };
    }
  }
  await session.choiceTracker.flush();
  const paintedHold = session.choiceTracker.records.find(
    (record) =>
      record.kind === "response" &&
      (record.startedAtMs ?? 0) >= clickedAtMs &&
      record.responseWakeToken
  );
  const resumedHold = session.choiceTracker.records.some(
    (record) =>
      record.kind === "response" &&
      (record.startedAtMs ?? 0) >= clickedAtMs &&
      record.holdResume === true
  );
  if (paintedHold || resumedHold || stillHeld) {
    session.resumeSinceMs = clickedAtMs;
    await attachClearedHoldResume(session, {
      wakeToken: paintedHold?.responseWakeToken,
      prompt,
      timeout
    });
    return { held: true, start, tracker: session.choiceTracker };
  }
  await assertActionOrPrompt(session.page, prompt, timeout);
  expect(
    doneAtMs - clickedAtMs,
    `${session.label} stayed on a hold after a last-choice skip`
  ).toBeLessThan(START_PAGE_MAX_MS);
  return { held: false, start, tracker: session.choiceTracker };
}

async function submitLastChoice(
  session,
  { buttonName = "go", prompt, timeout = STEP_TIMEOUT_MS }
) {
  session.choiceTracker = startParticipantRequestTracker(session.page);
  const clickedAtMs = Date.now();
  await session.page.getByRole("button", { name: buttonName }).click();
  await expect(session.page.locator("#main-body")).toContainText(prompt, {
    timeout
  });
  await expect(session.page.locator("#psynet-timeline-hold-indicator")).toHaveCount(
    0
  );
  const doneAtMs = Date.now();
  await session.choiceTracker.flush();
  expect(
    doneAtMs - clickedAtMs,
    `${session.label} stayed on a hold after submitting the last choice`
  ).toBeLessThan(START_PAGE_MAX_MS);
  return {
    clickedAtMs,
    doneAtMs,
    tracker: session.choiceTracker,
    start: {
      kind: "choice",
      clickedAtMs,
      paintedAtMs: doneAtMs,
      clickToPaintMs: doneAtMs - clickedAtMs,
      consentClickedAtMs: clickedAtMs,
      timelineAtMs: doneAtMs
    }
  };
}

async function assertWaiterReleasedWithLastArriver(
  session,
  lastEntry,
  {
    prompt = ACTION_PROMPT,
    timeout = STEP_TIMEOUT_MS,
    allowWebsocketResume = false,
    maxHoldResumePosts = 2
  } = {}
) {
  const resume = await session.resumePromise;
  await expect(session.page.locator("#main-body")).toContainText(prompt, {
    timeout
  });
  const probe = await readTimelineHoldReleaseProbe(session.page);
  if (session.choiceTracker) {
    await session.choiceTracker.flush();
  } else {
    await session.entry.tracker.flush();
  }
  if (lastEntry?.tracker?.flush) {
    await lastEntry.tracker.flush();
  }
  const records = session.choiceTracker
    ? session.choiceTracker.records
    : session.entry.tracker.records;
  const clock = lastArriverClock(lastEntry);
  const sinceMs = clock.clickedAtMs;
  const releaseAtMs = lastArriverReleaseAtMs(lastEntry);
  const extraTimelineSinceMs = releaseAtMs;
  const resumeRequests = responsesOverlappingLastArriver(records, sinceMs);
  const afterClickMs = resume.resumedAtMs - clock.clickedAtMs;
  const afterPaintMs = resume.resumedAtMs - clock.paintedAtMs;
  const afterReleaseMs = resume.resumedAtMs - releaseAtMs;
  const laterTimeline = requestsSince(
    records,
    extraTimelineSinceMs,
    "timeline_document"
  );
  const holdResumePosts = resumeRequests.filter(
    (record) =>
      record.kind === "response" &&
      record.status === 200 &&
      record.holdResume === true
  );
  const overlayClock = overlayWakeAndEndMs(
    probe,
    session.resumeLog || [],
    sinceMs
  );
  const lingerPosts = overlayEndingHoldResumePosts(
    holdResumePosts,
    overlayClock.lastWakeAtMs
  );
  const overlayHoldResumePost =
    lingerPosts[lingerPosts.length - 1] || holdResumePosts[0] || null;
  const holdResumePostMs = overlayHoldResumePost?.durationMs ?? null;
  const lingerBudgetMs = overlayLingerBudgetMs(lingerPosts);
  const lastArriverWork = lastArriverWorkRecord(lastEntry);
  const reasonsAfterLast = (session.resumeLog || [])
    .filter((entry) => {
      if (!entry.reason) {
        return false;
      }
      if (sinceMs == null || entry.atMs >= sinceMs) {
        return true;
      }
      return (
        entry.reason === "websocket connection" &&
        resume.resumedAtMs >= sinceMs
      );
    })
    .map((entry) => entry.reason);
  const wakeToEndMs = overlayClock.lingerMs;
  const publishedWakes = publishedWakeTokens(session.sockets?.frames || []);
  const sawPublishedWake = publishedWakes.includes(session.waitingWakeToken);
  const summary = holdReleaseSummary({
    clickToPaintMs: clock.clickToPaintMs,
    afterClickMs,
    afterPaintMs,
    afterReleaseMs,
    clockKind: clock.kind,
    holdResumePostMs,
    holdResumePost: overlayHoldResumePost,
    overlayLingerMs: wakeToEndMs,
    lingerBudgetMs,
    holdResumePostCount: holdResumePosts.length,
    lastArriverWork,
    extraTimelineGets: laterTimeline.length,
    probe: {
      ...probe,
      resumeReasons: reasonsAfterLast.map((reason) => ({ reason, atMs: sinceMs }))
    },
    resumeRequests,
    resumeLog: session.resumeLog || [],
    holdFrames: session.sockets?.frames || [],
    waitingWakeToken: session.waitingWakeToken,
    label: session.label
  });
  expect(
    session.waitingWakeToken,
    `${session.label} hold is missing a wake token (${summary})`
  ).toBeTruthy();
  if (
    !allowWebsocketResume ||
    !reasonsAfterLast.includes("websocket connection") ||
    reasonsAfterLast.includes("server notification")
  ) {
    expect(
      publishedWakes,
      `${session.label} last arriver did not wake the waiting hold (${summary})`
    ).toContain(session.waitingWakeToken);
    if (wakeToEndMs == null) {
      // Legacy reload can drop in-page clocks. A published wake plus an
      // approved hold-resume POST still prove the overlay left from the server.
      expect(
        holdResumePosts.length,
        `${session.label} missing wake→end clock and hold-resume POST (${summary})`
      ).toBeGreaterThan(0);
    } else {
      expect(
        wakeToEndMs,
        `${session.label} hold overlay lingered after the wake (${summary})`
      ).toBeLessThan(lingerBudgetMs);
    }
  } else if (wakeToEndMs != null) {
    expect(
      wakeToEndMs,
      `${session.label} hold overlay lingered after the wake (${summary})`
    ).toBeLessThan(lingerBudgetMs);
  }
  expect(
    afterReleaseMs,
    `${session.label} hold-resume clock ran backwards (${summary})`
  ).toBeGreaterThan(-ENTRY_REQUEST_MAX_MS);
  expect(
    afterClickMs,
    `${session.label} still held after the last arriver started (${summary})`
  ).toBeLessThan(START_PAGE_MAX_MS + lingerBudgetMs);
  expect(
    unexpectedBlockingRequests(resumeRequests, ENTRY_REQUEST_MAX_MS),
    `${session.label} hold-resume blocking: ${summary}`
  ).toEqual([]);
  // Hold tests set gunicorn workers to the session count plus two spares so
  // concurrent last-arrival GET /timeline can overlap every waiter hold-resume
  // POST without starving a waiter Redis subscribe. A short HTTP 503 is NOWAIT
  // when a POST hits the same participant row as that participant's GET.
  // unexpectedBlockingRequests still fails a busy retry that lasts 500ms
  // or more.
  if (isInplaceTimelineModeEnabled()) {
    expect(
      laterTimeline.length,
      `${session.label} extra /timeline reloads after the last arriver finished grouping (${summary})`
    ).toBe(0);
  } else {
    expect(
      laterTimeline.length,
      `${session.label} extra /timeline reloads after the last arriver finished grouping (${summary})`
    ).toBeLessThanOrEqual(1);
  }
  expect(
    holdResumePosts.length,
    `${session.label} missing hold-resume POST /response (${summary})`
  ).toBeGreaterThan(0);
  expect(
    reasonsAfterLast,
    `${session.label} used a safety poll after the last arriver started (${summary})`
  ).not.toContain("safety poll");
  expect(
    reasonsAfterLast,
    `${session.label} used a hold-timeout resume after the last arriver started (${summary})`
  ).not.toContain("hold timeout");
  const allowedReasons = allowWebsocketResume
    ? LATE_ARRIVAL_RESUME_REASONS
    : RELEASE_RESUME_REASONS;
  expect(
    reasonsAfterLast.some((reason) => allowedReasons.has(reason)) ||
      (sawPublishedWake && holdResumePosts.length > 0),
    `${session.label} did not resume from a server wake (${summary})`
  ).toBe(true);
  expect(
    holdResumePosts.length,
    `${session.label} extra hold-resume requests: ${summary}`
  ).toBeLessThanOrEqual(maxHoldResumePosts);
  console.log(summary);
  return {
    resume,
    probe,
    summary,
    holdResumePost: overlayHoldResumePost
  };
}

async function assertAllWaitersReleasedTogether(sessions, lastEntry, options = {}) {
  const results = await Promise.all(
    sessions.map((session) =>
      assertWaiterReleasedWithLastArriver(session, lastEntry, options)
    )
  );
  const times = results.map((result) => result.resume.resumedAtMs);
  const spread = Math.max(...times) - Math.min(...times);
  expect(
    spread,
    `waiting members left ${spread}ms apart after the hold was satisfied`
  ).toBeLessThan(WAITER_RELEASE_SPREAD_MAX_MS);
  return results;
}

async function enterPossiblyHeldArrival(
  session,
  { holdText, prompt = ACTION_PROMPT, timeout = STEP_TIMEOUT_MS } = {}
) {
  const entry = await enterTimelineAfterGateway(session.page, timeout);
  session.entry = entry;
  assertEntryWasResponsive(entry, session.label, {
    signupMaxMs: SERIALIZED_SIGNUP_MAX_MS
  });
  await waitForTimelinePageReady(session.page, timeout);
  await wrapTimelineHoldResumeProbe(session.page);
  const stillHeld = await waitForHoldOrPrompt(session.page, {
    holdText,
    prompt,
    timeout
  });
  session.resumeSinceMs = entry.start.timelineAtMs;
  if (stillHeld) {
    if (await armVisibleHold(session, { holdText, prompt, timeout })) {
      return { entry, held: true };
    }
  }
  if (entry.paint.showsHold) {
    expect(
      entry.paint.wakeToken,
      `${session.label} first-paint hold is missing a wake token`
    ).toBeTruthy();
    await attachClearedHoldResume(session, {
      wakeToken: entry.paint.wakeToken,
      prompt,
      timeout
    });
    return { entry, held: true };
  }
  await expect(session.page.locator("#main-body")).toContainText(prompt, {
    timeout
  });
  await expect(session.page.locator("#psynet-timeline-hold-indicator")).toHaveCount(
    0
  );
  return { entry, held: false };
}

async function assertActionOrPrompt(page, prompt, timeout = STEP_TIMEOUT_MS) {
  await waitForTimelinePageReady(page, timeout);
  await expect(page.locator("#main-body")).toContainText(prompt, { timeout });
  await expect(page.locator("#psynet-timeline-hold-indicator")).toHaveCount(0);
}

async function assertActionPage(page, timeout = STEP_TIMEOUT_MS) {
  await assertActionOrPrompt(page, ACTION_PROMPT, timeout);
}

async function assertNoSessionErrors(sessions) {
  for (const session of sessions) {
    if (session.entry?.tracker) {
      await session.entry.tracker.flush();
      // POST /participant is bounded by SERIALIZED_SIGNUP_MAX_MS /
      // START_PAGE_MAX_MS at entry. Dallinger `@db.serialized` retry sleep
      // is not timeline-handler blocking.
      const records = session.entry.tracker.records.filter(
        (record) => record.kind !== "create_participant"
      );
      expect(
        unexpectedBlockingRequests(records, BLOCKING_REQUEST_MS),
        `${session.label} unexpected blocking: ${summarizeParticipantRequests(
          session.entry.tracker.records
        )}`
      ).toEqual([]);
    }
    if (session.choiceTracker) {
      session.choiceTracker.stop();
    }
    await assertNoBackendError(session.page);
  }
}

module.exports = {
  ACTION_PROMPT,
  BLOCKING_REQUEST_MS,
  ENTRY_REQUEST_MAX_MS,
  GROUP_HOLD_TEXT,
  PAIR_HOLD_TEXT,
  PARTNER_HOLD_RELEASE_MAX_MS,
  RESULTS_PROMPT,
  SERIALIZED_SIGNUP_MAX_MS,
  SETTLE_HOLD_MS,
  START_PAGE_MAX_MS,
  STEP_TIMEOUT_MS,
  WAITER_RELEASE_SPREAD_MAX_MS,
  armChoiceHold,
  assertActionPage,
  assertAllWaitersReleasedTogether,
  assertEntryWasResponsive,
  assertNoSessionErrors,
  assertStillHeld,
  assertWaiterReleasedWithLastArriver,
  enterPossiblyHeldArrival,
  closeHoldSessions,
  createHoldSession,
  enterSkippingHold,
  enterTimelineAfterGateway,
  enterWaitingHold,
  lastArriverReleaseAtMs,
  lastArriverWorkRecord,
  pickConcurrentLastArriver,
  responsesSince,
  startHoldExperiment,
  stopExperiment,
  submitChoiceMaybeHeld,
  submitLastChoice
};

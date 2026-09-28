const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  evaluateOnLivePage,
  installTimelineHoldReleaseProbe,
  silenceTimelineHoldSafetyPoll,
  startResponseSubmitTracker,
  waitForTimelinePageReady,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const HOLD_WAKE_TIMEOUT_MS = 10000;

async function installBeforeUnloadTracking(page) {
  await page.evaluate(() => {
    window.beforeUnloadOperations = [];
    if (window.beforeUnloadTrackingInstalled) return;

    window.beforeUnloadTrackingInstalled = true;
    const originalAddEventListener = window.addEventListener.bind(window);
    const originalRemoveEventListener =
      window.removeEventListener.bind(window);
    window.addEventListener = function (type, ...args) {
      if (type === "beforeunload") window.beforeUnloadOperations.push("add");
      return originalAddEventListener(type, ...args);
    };
    window.removeEventListener = function (type, ...args) {
      if (type === "beforeunload") {
        window.beforeUnloadOperations.push("remove");
      }
      return originalRemoveEventListener(type, ...args);
    };
  });
}

function installTimelineHoldWakeCounter() {
  if (!["http:", "https:"].includes(location.protocol)) return;
  if (window.__timelineHoldWakeCounterInstalled) return;
  window.__timelineHoldWakeCounterInstalled = true;
  if (sessionStorage.getItem("timelineHoldWakeCount") === null) {
    sessionStorage.setItem("timelineHoldWakeCount", "0");
  }
  window.addEventListener("timelineHoldWakeReceived", () => {
    const count = Number(sessionStorage.getItem("timelineHoldWakeCount"));
    sessionStorage.setItem("timelineHoldWakeCount", String(count + 1));
  });
}

async function startBackgroundHold(page, { trackLucidUnload = false } = {}) {
  await completeInitialGateway(page);
  await expect(page.locator("#main-body")).toContainText(
    "Submit this page to start background feedback processing.",
    { timeout: STEP_TIMEOUT_MS }
  );
  if (trackLucidUnload) {
    await installBeforeUnloadTracking(page);
    await page.evaluate(() => {
      psynetTemplateData.flags.lucidRecruitment = true;
      Object.assign(psynetTemplateData.lucid, {
        inactivityTimeoutMs: 600000,
        inactivityTimeoutS: 600,
        noFocusTimeoutMs: 600000,
        noFocusTimeoutReason: "no-focus-",
        overallTimeoutS: 600,
        secondsLeft: 600,
        shouldWarnOnBeforeUnload: true
      });
      psynet.initLucidTermination();
    });
  }
  const visiblePageUuid = await page.evaluate(() => window.pageUuid);
  const mainBodyTop = await page
    .locator("#main-body")
    .evaluate((element) => element.getBoundingClientRect().top + window.scrollY);
  await page.locator("#next-button").click();
  await expect(page.locator("#psynet-timeline-hold-indicator")).toBeVisible({
    timeout: STEP_TIMEOUT_MS
  });
  return { visiblePageUuid, mainBodyTop };
}

async function probeTimelineHoldClientBehavior(page) {
  await installTimelineHoldReleaseProbe(page);
  const overlay = await evaluateOnLivePage(page, () => {
    const controller = psynet.timelineHold;
    if (!controller) {
      throw new Error("timeline hold is not active");
    }
    if (!psynet.pageReady) {
      throw new Error("timeline hold probe ran before pageReady");
    }
    const originalSchedule = psynet.scheduleTimelineHoldCheck;
    const originalTimeout = psynet.scheduleTimelineHoldTimeout;
    const originalConnect = PsyNetWebSocketChannel.connect;
    clearTimeout(controller.safetyTimer);
    clearTimeout(controller.timeoutTimer);
    controller.safetyTimer = null;
    controller.timeoutTimer = null;
    if (controller.connection) {
      controller.connection.close();
      controller.connection = null;
    }
    psynet.scheduleTimelineHoldCheck = function () {};
    psynet.scheduleTimelineHoldTimeout = function () {};
    PsyNetWebSocketChannel.connect = function () {
      return {
        close() {},
        isOpen() {
          return false;
        },
        send() {}
      };
    };

    let arrivalClosed = 0;
    const fakeArrival = () => ({
      channel: "test",
      connection: {
        close() {
          arrivalClosed += 1;
        }
      }
    });

    psynet.arrivalUpdates = fakeArrival();
    const strayNotice = document.createElement("div");
    strayNotice.id = "psynet-arrival-notice";
    document.body.appendChild(strayNotice);
    psynet.ensureArrivalUpdates(null);
    const closedWithoutChannel =
      arrivalClosed === 1 && psynet.arrivalUpdates === null;
    const noticeClearedWithoutChannel =
      document.getElementById("psynet-arrival-notice") === null;

    psynet.arrivalUpdates = fakeArrival();
    const hold = { ...controller.hold };
    psynet.beginTimelineHold(hold);
    const closedOnBeginHold =
      arrivalClosed === 2 && psynet.arrivalUpdates === null;

    const reusedIndicator = document.getElementById(
      "psynet-timeline-hold-indicator"
    );
    let hopEnded = 0;
    const hopEndedListener = () => {
      hopEnded += 1;
    };
    window.addEventListener("timelineHoldEnded", hopEndedListener);
    psynet.beginTimelineHold({
      ...hold,
      page_uuid: "hop-page-uuid",
      wake_token: "hop-wake-token",
      message: "Updated wait copy"
    });
    window.removeEventListener("timelineHoldEnded", hopEndedListener);
    const hopReusedChip =
      document.getElementById("psynet-timeline-hold-indicator") ===
      reusedIndicator;
    const hopKeptPageInert = Boolean(
      document.getElementById("main-body")?.inert
    );
    const commentStashAfterHop = document.getElementById(
      "psynet-timeline-hold-indicator"
    )?.dataset.commentButtonWasDisabled;
    const hopPreservedCommentStash =
      commentStashAfterHop === undefined || commentStashAfterHop === "false";
    const updatedMessage = document.querySelector(
      "#psynet-timeline-hold-indicator .psynet-timeline-hold-message"
    )?.innerHTML;
    const originalSilent = Boolean(controller.hold.silent);
    controller.hold.silent = true;
    psynet.handleArrivalUpdateMessage({
      type: "timeline_hold_wake",
      targets: [
        {
          hold_message:
            '<span class="psynet-timeline-hold-title">Waiting for other participants…</span>'
        }
      ]
    });
    const silentIgnoredArrival =
      document.querySelector(
        "#psynet-timeline-hold-indicator .psynet-timeline-hold-message"
      )?.innerHTML === updatedMessage;
    controller.hold.silent = originalSilent;

    const OriginalXHR = window.XMLHttpRequest;
    let sendCount = 0;
    window.XMLHttpRequest = function FakeXHR() {
      const xhr = {
        readyState: 0,
        status: 0,
        response: "",
        responseText: "",
        timeout: 0,
        onreadystatechange: null,
        onload: null,
        onerror: null,
        ontimeout: null,
        open() {},
        setRequestHeader() {},
        abort() {},
        addEventListener() {},
        removeEventListener() {},
        send() {
          sendCount += 1;
          xhr.readyState = 4;
          if (sendCount === 1) {
            xhr.status = 503;
            xhr.response = JSON.stringify({
              status: "busy",
              submission: "busy",
              message: "The experiment is temporarily busy. Please try again."
            });
          } else {
            xhr.status = 200;
            xhr.response = JSON.stringify({
              submission: "approved",
              page: { contents: "", attributes: {} }
            });
          }
          xhr.responseText = xhr.response;
          if (xhr.onreadystatechange) {
            xhr.onreadystatechange();
          }
          if (xhr.onload) {
            xhr.onload();
          }
        }
      };
      return xhr;
    };
    const originalApproved = psynet.handleApprovedResponse;
    const originalAlert = psynet.alert;
    let approved = 0;
    psynet.handleApprovedResponse = async () => {
      approved += 1;
      return true;
    };
    psynet.alert = (text) => {
      throw new Error(
        `unexpected psynet.alert during hold client probe: ${text}`
      );
    };
    const pendingBefore = psynet.nextPagePending;
    psynet.nextPagePending = false;
    window.__holdClientNext = { done: false };
    // Do not await nextPage in this evaluate. submitGenericResponse waits
    // 250ms between the busy 503 and the retry; Playwright's awaitPromise
    // does not flush that timer while the evaluate is still open.
    Promise.resolve()
      .then(() =>
        psynet.nextPage(null, {}, {}, undefined, { timelineHoldResume: true })
      )
      .then((passed) => {
        window.__holdClientNext = {
          done: true,
          passed,
          approved,
          sendCount,
          error: null
        };
      })
      .catch((error) => {
        window.__holdClientNext = {
          done: true,
          passed: false,
          approved,
          sendCount,
          error: String(error && error.message ? error.message : error)
        };
      });
    window.__holdClientRestore = () => {
      window.XMLHttpRequest = OriginalXHR;
      psynet.handleApprovedResponse = originalApproved;
      psynet.alert = originalAlert;
      psynet.nextPagePending = pendingBefore;
      psynet.scheduleTimelineHoldCheck = originalSchedule;
      psynet.scheduleTimelineHoldTimeout = originalTimeout;
      PsyNetWebSocketChannel.connect = originalConnect;
    };
    window.__holdClientOriginalApproved = originalApproved;

    return {
      closedWithoutChannel,
      noticeClearedWithoutChannel,
      closedOnBeginHold,
      hopEnded,
      hopReusedChip,
      hopKeptPageInert,
      hopPreservedCommentStash,
      updatedMessage,
      silentIgnoredArrival
    };
  });

  await page.waitForFunction(
    () => window.__holdClientNext && window.__holdClientNext.done,
    { timeout: 10000 }
  );
  const nextPage = await page.evaluate(() => window.__holdClientNext);
  if (nextPage.error) {
    throw new Error(nextPage.error);
  }

  await page.waitForFunction(
    () => Boolean(window.psynet && window.psynet.timelineHold),
    { timeout: 15000 }
  );

  const clocks = await evaluateOnLivePage(page, () => {
    const probe = window.__psynetHoldReleaseProbe;
    let clocksReset = false;
    if (probe) {
      probe.holdEndedAtMs = 123;
      probe.wakeReceivedAtMs = 456;
      probe.wakeReason = "old";
      window.dispatchEvent(new CustomEvent("timelineHoldStarted"));
      clocksReset =
        probe.holdEndedAtMs === null &&
        probe.wakeReceivedAtMs === null &&
        probe.wakeReason === null;
    }
    const originalReplace = window.location.replace.bind(window.location);
    window.location.replace = (url) => {
      throw new Error(`lucid terminated during hold: ${url}`);
    };
    if (window.location.replace === originalReplace) {
      throw new Error("could not stub location.replace");
    }
    const originalLucidFlag = psynetTemplateData.flags.lucidRecruitment;
    const originalLucid = { ...psynetTemplateData.lucid };
    psynetTemplateData.flags.lucidRecruitment = true;
    Object.assign(psynetTemplateData.lucid, {
      inactivityTimeoutMs: 1,
      inactivityTimeoutS: 0,
      noFocusTimeoutMs: 1,
      noFocusTimeoutReason: "no-focus-",
      overallTimeoutS: 600,
      secondsLeft: 600,
      shouldWarnOnBeforeUnload: false
    });
    psynet.initLucidTermination();
    window.__holdClientLucid = {
      originalReplace,
      originalLucidFlag,
      originalLucid
    };
    return { clocksReset };
  });

  await new Promise((resolve) => setTimeout(resolve, 1200));

  const rest = await evaluateOnLivePage(page, () => {
    const lucid = window.__holdClientLucid;
    psynet.clearLucidTermination();
    if (lucid) {
      psynetTemplateData.flags.lucidRecruitment = lucid.originalLucidFlag;
      Object.assign(psynetTemplateData.lucid, lucid.originalLucid);
      window.location.replace = lucid.originalReplace;
      window.__holdClientLucid = null;
    }

    let reloadedHoldPayload = 0;
    const originalReload = psynet.loadNextTimelinePageWithReload;
    psynet.loadNextTimelinePageWithReload = () => {
      reloadedHoldPayload += 1;
    };
    const originalApproved = psynet.handleApprovedResponse;
    psynet.handleApprovedResponse =
      window.__holdClientOriginalApproved || originalApproved;
    const liveHold = psynet.timelineHold ? { ...psynet.timelineHold.hold } : {};
    try {
      psynet.handleApprovedResponse({
        page: {
          attributes: {
            timeline_hold: liveHold,
            requires_full_page_reload: true,
            page_uuid: liveHold.page_uuid
          }
        }
      });
    } finally {
      psynet.handleApprovedResponse = originalApproved;
      psynet.loadNextTimelinePageWithReload = originalReload;
    }
    if (typeof window.__holdClientRestore === "function") {
      window.__holdClientRestore();
      window.__holdClientRestore = null;
    }
    if (liveHold.page_uuid) {
      if (psynet.timelineHold) {
        psynet.stopTimelineHold();
      }
      psynet.beginTimelineHold(liveHold);
    }
    return { reloadedHoldPayload };
  });

  return {
    ...overlay,
    sendCount: nextPage.sendCount,
    approved: nextPage.approved,
    passed: nextPage.passed,
    clocksReset: clocks.clocksReset,
    reloadedHoldPayload: rest.reloadedHoldPayload,
    lucidHoldPausedClocks: true
  };
}

test("wait_while preserves the submitted page and wakes after async work", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold"
  );

  // Install before withExperiment navigates. page.addInitScript after the
  // consent document is already loaded does not run until the next full load.
  await context.addInitScript(installTimelineHoldWakeCounter);
  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    const { visiblePageUuid, mainBodyTop } = await startBackgroundHold(
      experimentPage,
      { trackLucidUnload: true }
    );
    await experimentPage.evaluate(installTimelineHoldWakeCounter);
    // check_interval is 1s. An in-place safety-poll POST can return the next
    // page and stop the hold controller before websocket onMessage dispatches
    // timelineHoldWakeReceived, so the wake counter stays 0.
    expect(await silenceTimelineHoldSafetyPoll(experimentPage)).toBe(true);

    await expect(experimentPage.locator("#main-body")).toContainText(
      "Submit this page to start background feedback processing."
    );
    await expect
      .poll(() =>
        experimentPage.evaluate(
          () => window.beforeUnloadOperations.at(-1)
        )
      )
      .toBe("add");
    expect(
      await experimentPage.evaluate(
        (uuid) =>
          window.pageUuid === uuid &&
          psynet.submissionPageUuid !== window.pageUuid &&
          document.getElementById("main-body").inert,
        visiblePageUuid
      )
    ).toBe(true);
    await expect(experimentPage.locator("#comment-button")).toBeDisabled();

    // The indicator floats, so the preserved page must not shift when it appears.
    const holdLayout = await experimentPage.evaluate(() => {
      const mainBody = document.getElementById("main-body");
      const header = document.getElementById("timeline-header");
      const region = document.getElementById("timeline-hold-region");
      return {
        mainBodyTop: mainBody.getBoundingClientRect().top + window.scrollY,
        regionPosition: getComputedStyle(region).position,
        indicatorTop: document
          .getElementById("psynet-timeline-hold-indicator")
          .getBoundingClientRect().top,
        headerBottom: header.getBoundingClientRect().bottom
      };
    });
    expect(holdLayout.mainBodyTop).toBeCloseTo(mainBodyTop, 1);
    expect(holdLayout.regionPosition).toBe("fixed");
    expect(holdLayout.indicatorTop).toBeGreaterThanOrEqual(
      holdLayout.headerBottom
    );

    await expect(experimentPage.locator("#main-body")).toContainText(
      "Background feedback processing finished.",
      { timeout: STEP_TIMEOUT_MS }
    );
    const accounting = await experimentPage.evaluate(() => ({
      credit: Number(document.getElementById("hold-credit").textContent),
      metric: Number(document.getElementById("hold-metric").textContent)
    }));
    expect(accounting.credit).toBeGreaterThanOrEqual(2.5);
    expect(accounting.credit).toBeLessThanOrEqual(20);
    expect(accounting.metric).toBeCloseTo(accounting.credit, 5);
    expect(
      await experimentPage.evaluate(
        () => Number(sessionStorage.getItem("timelineHoldWakeCount"))
      )
    ).toBeGreaterThanOrEqual(1);
    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toHaveCount(0);
    expect(
      await experimentPage.evaluate(
        () =>
          !document.body.classList.contains("timeline-held") &&
          !document.getElementById("main-body").inert
      )
    ).toBe(true);
    await expect(experimentPage.locator("#comment-button")).toBeEnabled();

    await installBeforeUnloadTracking(experimentPage);
    const compileFailureCleanup = await experimentPage.evaluate(async () => {
      const originalCompileResponse = psynet.compileResponse;
      psynetTemplateData.flags.lucidRecruitment = true;
      psynet.captureSubmissionControlState();
      psynet.removeBeforeUnloadEventListener();
      psynet.compileResponse = async () => {
        throw new Error("synthetic compile failure");
      };
      try {
        await psynet.submitResponse(() => {});
      } catch (error) {
        // Expected synthetic failure.
      } finally {
        psynet.compileResponse = originalCompileResponse;
      }
      return {
        controlStateCleared: psynet.submissionControlState === null,
        lastBeforeUnloadOperation: window.beforeUnloadOperations.at(-1)
      };
    });
    expect(compileFailureCleanup).toEqual({
      controlStateCleared: true,
      lastBeforeUnloadOperation: "add"
    });

    const holdTransitionRecovery = await experimentPage.evaluate(async () => {
      const originals = {
        inplaceTransitions:
          psynetTemplateData.flags.inplaceTimelineTransitions,
        loadFragment: psynet.loadNextTimelinePageFromResponse,
        loadReload: psynet.loadNextTimelinePageWithReload,
        logError: psynet.log.error,
        stopHold: psynet.stopTimelineHold,
        timelineHold: psynet.timelineHold
      };
      const calls = { reload: 0, stop: 0 };
      psynetTemplateData.flags.inplaceTimelineTransitions = true;
      psynet.timelineHold = {};
      psynet.log.error = () => {};
      psynet.stopTimelineHold = () => {
        calls.stop += 1;
        psynet.timelineHold = null;
      };
      psynet.loadNextTimelinePageFromResponse = async () => {
        throw new Error("synthetic hold fragment failure");
      };
      psynet.loadNextTimelinePageWithReload = () => {
        calls.reload += 1;
      };
      try {
        const result = await psynet.handleApprovedResponse({
          page: {
            attributes: {
              page_uuid: "recovered-page",
              requires_full_page_reload: false,
              session_id: null
            }
          },
          timeline_fragment: { html: "<div>unused</div>" }
        });
        return { ...calls, result };
      } finally {
        psynetTemplateData.flags.inplaceTimelineTransitions =
          originals.inplaceTransitions;
        psynet.loadNextTimelinePageFromResponse = originals.loadFragment;
        psynet.loadNextTimelinePageWithReload = originals.loadReload;
        psynet.log.error = originals.logError;
        psynet.stopTimelineHold = originals.stopHold;
        psynet.timelineHold = originals.timelineHold;
      }
    });
    expect(holdTransitionRecovery).toEqual({
      reload: 1,
      stop: 1,
      result: true
    });
    await assertNoBackendError(experimentPage);
  });
});

test("timeline hold client overlay and busy retry stay on a live hold", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold_client"
  );

  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    const responses = startResponseSubmitTracker(experimentPage);
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Submit this page to start a hold that stays until the test finishes.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await experimentPage.locator("#next-button").click();
    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    // Silence before pageReady: a safety-poll resume during that wait can
    // POST /response and leave nextPagePending set for the client probe.
    await silenceTimelineHoldSafetyPoll(experimentPage);
    await waitForTimelinePageReady(experimentPage, STEP_TIMEOUT_MS);

    const holdClient = await probeTimelineHoldClientBehavior(experimentPage);
    expect(holdClient).toEqual({
      closedWithoutChannel: true,
      noticeClearedWithoutChannel: true,
      closedOnBeginHold: true,
      hopEnded: 0,
      hopReusedChip: true,
      hopKeptPageInert: true,
      hopPreservedCommentStash: true,
      updatedMessage: "Updated wait copy",
      silentIgnoredArrival: true,
      sendCount: 2,
      approved: 1,
      passed: true,
      clocksReset: true,
      reloadedHoldPayload: 1,
      lucidHoldPausedClocks: true
    });

    await experimentPage.waitForTimeout(500);
    const settledResponseCount = responses.getCount();
    await experimentPage.waitForTimeout(700);
    expect(responses.getCount()).toBeLessThanOrEqual(settledResponseCount + 1);

    const blockedBaseline = responses.getCount();
    expect(
      await experimentPage.evaluate(() => psynet.nextPage("unexpected"))
    ).toBe(false);
    await experimentPage.waitForTimeout(200);
    expect(responses.getCount()).toBeLessThanOrEqual(blockedBaseline + 1);

    const rejectedHoldEffects = await experimentPage.evaluate(async () => {
      const originalAlert = psynet.alert;
      const originalResponseEnable = psynet.response.enable;
      const originalSubmitEnable = psynet.submit.enable;
      const originalStopHold = psynet.stopTimelineHold;
      const originalReload = psynet.loadNextTimelinePageWithReload;
      const effects = {
        alerts: 0,
        responseEnables: 0,
        submitEnables: 0,
        holdStops: 0,
        reloads: 0
      };
      psynet.alert = () => {
        effects.alerts += 1;
      };
      psynet.response.enable = () => {
        effects.responseEnables += 1;
      };
      psynet.submit.enable = () => {
        effects.submitEnables += 1;
      };
      psynet.stopTimelineHold = () => {
        effects.holdStops += 1;
      };
      psynet.loadNextTimelinePageWithReload = () => {
        effects.reloads += 1;
      };
      await psynet.handleRejectedResponse(
        { message: "Rejected hold check" },
        undefined,
        { timelineHoldResume: true }
      );
      psynet.alert = originalAlert;
      psynet.response.enable = originalResponseEnable;
      psynet.submit.enable = originalSubmitEnable;
      psynet.stopTimelineHold = originalStopHold;
      psynet.loadNextTimelinePageWithReload = originalReload;
      return effects;
    });
    expect(rejectedHoldEffects).toEqual({
      alerts: 0,
      responseEnables: 0,
      submitEnables: 0,
      holdStops: 1,
      reloads: 1
    });

    const busyHoldEffects = await experimentPage.evaluate(async () => {
      const originalAlert = psynet.alert;
      const originalResponseEnable = psynet.response.enable;
      const originalSubmitEnable = psynet.submit.enable;
      const originalSchedule = psynet.scheduleTimelineHoldCheck;
      const effects = {
        alerts: 0,
        responseEnables: 0,
        submitEnables: 0,
        scheduleCalls: 0
      };
      // The client-behavior probe reconnects the hold websocket. Wait for
      // that onOpen resume to settle; swallowing resumeTimelineHold so a
      // late open cannot start another in-flight POST during the probe.
      const controller = psynet.timelineHold;
      const originalResume = psynet.resumeTimelineHold;
      const pendingBefore = psynet.nextPagePending;
      psynet.resumeTimelineHold = async () => false;
      try {
        if (controller) {
          const deadline = Date.now() + 5000;
          while (controller.resumeInFlight && Date.now() < deadline) {
            await new Promise((resolve) => setTimeout(resolve, 25));
          }
          if (controller.resumeInFlight) {
            throw new Error("hold resume still in flight before the busy probe");
          }
          controller.resumeRequested = false;
          clearTimeout(controller.busyRetryTimer);
          controller.busyRetryTimer = null;
        }
        psynet.nextPagePending = false;
        psynet.alert = () => {
          effects.alerts += 1;
        };
        psynet.response.enable = () => {
          effects.responseEnables += 1;
        };
        psynet.submit.enable = () => {
          effects.submitEnables += 1;
        };
        psynet.scheduleTimelineHoldCheck = () => {
          effects.scheduleCalls += 1;
        };
        const request = {
          status: 503,
          response: JSON.stringify({
            status: "busy",
            submission: "busy",
            message: "The experiment is temporarily busy. Please try again."
          })
        };
        const isBusy = psynet.isBusyResponse(request);
        await psynet.handleBusyResponse(request, { timelineHoldResume: true });
        const resumeRequested = Boolean(psynet.timelineHold?.resumeRequested);
        const busyRetryUsed = Boolean(psynet.timelineHold?.busyRetryUsed);
        const delayedWakeMs = psynet.timelineHoldBusyRetryMs;
        clearTimeout(psynet.timelineHold?.busyRetryTimer);
        if (psynet.timelineHold) {
          psynet.timelineHold.busyRetryTimer = null;
        }
        return {
          isBusy,
          resumeRequested,
          busyRetryUsed,
          delayedWakeMs,
          ...effects
        };
      } finally {
        psynet.alert = originalAlert;
        psynet.response.enable = originalResponseEnable;
        psynet.submit.enable = originalSubmitEnable;
        psynet.scheduleTimelineHoldCheck = originalSchedule;
        psynet.resumeTimelineHold = originalResume;
        psynet.nextPagePending = pendingBefore;
      }
    });
    expect(busyHoldEffects).toEqual({
      isBusy: true,
      resumeRequested: false,
      busyRetryUsed: true,
      delayedWakeMs: 250,
      scheduleCalls: 0,
      alerts: 0,
      responseEnables: 0,
      submitEnables: 0
    });

    const transportFailureHoldEffects = await experimentPage.evaluate(
      async () => {
        const originalAlert = psynet.alert;
        const originalErrorPage = window.psynetErrorPage;
        const originalReload = psynet.loadNextTimelinePageWithReload;
        const originalSchedule = psynet.scheduleTimelineHoldCheck;
        const effects = {
          alerts: 0,
          reloads: 0,
          errorPages: 0,
          scheduleCalls: 0,
          timeoutMs: psynet.timelineHoldResumeTimeoutMs
        };
        psynet.alert = () => {
          effects.alerts += 1;
        };
        window.psynetErrorPage = {
          go() {
            effects.errorPages += 1;
          }
        };
        psynet.loadNextTimelinePageWithReload = () => {
          effects.reloads += 1;
        };
        psynet.scheduleTimelineHoldCheck = () => {
          effects.scheduleCalls += 1;
        };
        const request = { status: 500, response: "Internal Server Error" };
        await psynet.handleHoldResumeTransportFailure(request);
        const resumeRequested = Boolean(psynet.timelineHold?.resumeRequested);
        const holdStillActive = Boolean(psynet.timelineHold);
        psynet.alert = originalAlert;
        window.psynetErrorPage = originalErrorPage;
        psynet.loadNextTimelinePageWithReload = originalReload;
        psynet.scheduleTimelineHoldCheck = originalSchedule;
        return { resumeRequested, holdStillActive, ...effects };
      }
    );
    expect(transportFailureHoldEffects).toEqual({
      resumeRequested: false,
      holdStillActive: true,
      timeoutMs: 30000,
      scheduleCalls: 1,
      alerts: 0,
      reloads: 0,
      errorPages: 0
    });

    const busyLivelock = await experimentPage.evaluate(async () => {
      const controller = psynet.timelineHold;
      const originalNextPage = psynet.nextPage;
      const originalSchedule = psynet.scheduleTimelineHoldCheck;
      const originalResume = psynet.resumeTimelineHold;
      const request = {
        status: 503,
        response: JSON.stringify({
          status: "busy",
          submission: "busy",
          message: "The experiment is temporarily busy. Please try again."
        })
      };
      const effects = { queuedWakes: 0, scheduleCalls: 0 };
      // Websocket onOpen from the client-behavior probe can leave a resume
      // in flight. Swallow new resumes, wait for that POST to settle, then
      // measure handleBusyResponse rather than the resumeInFlight
      // early-return that only sets resumeRequested.
      const pendingBefore = psynet.nextPagePending;
      psynet.resumeTimelineHold = async () => false;
      try {
        const deadline = Date.now() + 5000;
        while (controller.resumeInFlight && Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        if (controller.resumeInFlight) {
          throw new Error(
            "hold resume still in flight before the busy livelock probe"
          );
        }
        controller.resumeRequested = false;
        clearTimeout(controller.safetyTimer);
        controller.busyRetryUsed = true;
        clearTimeout(controller.busyRetryTimer);
        controller.busyRetryTimer = null;
        psynet.nextPagePending = false;
        psynet.scheduleTimelineHoldCheck = () => {
          effects.scheduleCalls += 1;
        };
        psynet.resumeTimelineHold = async function (reason) {
          if (reason === "queued hold wake") {
            effects.queuedWakes += 1;
          }
          return originalResume.apply(this, arguments);
        };
        psynet.nextPage = async function (
          _button,
          _answer,
          _metadata,
          _blobs,
          options
        ) {
          await psynet.handleBusyResponse(request, options);
          return false;
        };
        await originalResume.call(psynet, "busy livelock");
        await new Promise((resolve) => setTimeout(resolve, 0));
        return {
          queuedWakes: effects.queuedWakes,
          scheduleCalls: effects.scheduleCalls,
          resumeRequested: Boolean(psynet.timelineHold?.resumeRequested),
          busyRetryUsed: Boolean(psynet.timelineHold?.busyRetryUsed)
        };
      } finally {
        clearTimeout(controller.busyRetryTimer);
        controller.busyRetryTimer = null;
        psynet.nextPage = originalNextPage;
        psynet.scheduleTimelineHoldCheck = originalSchedule;
        psynet.resumeTimelineHold = originalResume;
        psynet.nextPagePending = pendingBefore;
      }
    });
    expect(busyLivelock).toEqual({
      queuedWakes: 0,
      scheduleCalls: 1,
      resumeRequested: false,
      busyRetryUsed: true
    });

    const pendingEffects = await experimentPage.evaluate(async () => {
      const controller = psynet.timelineHold;
      const originalNextPage = psynet.nextPage;
      const originalSchedule = psynet.scheduleTimelineHoldCheck;
      const effects = { nextPageCalls: 0, scheduleCalls: 0 };
      clearTimeout(controller.safetyTimer);
      psynet.nextPage = () => {
        effects.nextPageCalls += 1;
      };
      psynet.scheduleTimelineHoldCheck = () => {
        effects.scheduleCalls += 1;
      };
      try {
        psynet.nextPagePending = true;
        effects.result = await psynet.resumeTimelineHold("test pending request");
      } finally {
        psynet.nextPagePending = false;
        psynet.nextPage = originalNextPage;
        psynet.scheduleTimelineHoldCheck = originalSchedule;
      }
      return effects;
    });
    expect(pendingEffects).toEqual({
      nextPageCalls: 0,
      scheduleCalls: 1,
      result: false
    });
    await experimentPage.evaluate(() => {
      if (psynet.timelineHold) {
        psynet.resumeTimelineHold("test after pending probe");
      }
    });

    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible();
    expect(
      await experimentPage.evaluate(() => Boolean(psynet.timelineHold))
    ).toBe(true);
    responses.stop();
    await assertNoBackendError(experimentPage);
  });
});

test("timeline hold restores its accessible fallback after refresh", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold"
  );

  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    await startBackgroundHold(experimentPage);
    await experimentPage.reload();

    const indicator = experimentPage.locator("#psynet-timeline-hold-indicator");
    await expect(indicator).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await expect(indicator).toHaveAttribute("role", "status");
    await expect(indicator).toHaveAttribute("aria-live", "polite");
    expect(
      await experimentPage.evaluate(
        () => !document.getElementById("main-body").inert
      )
    ).toBe(true);

    await expect(experimentPage.locator("#main-body")).toContainText(
      "Background feedback processing finished.",
      { timeout: HOLD_WAKE_TIMEOUT_MS }
    );
    await assertNoBackendError(experimentPage);
  });
});

test("timeline hold uses the authoritative server timeout", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold_timeout"
  );

  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Start a timeline hold that will time out.",
      { timeout: STEP_TIMEOUT_MS }
    );
    const startedAt = Date.now();
    await experimentPage.locator("#next-button").click();
    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await expect(experimentPage.locator("#main-body")).toContainText(
      "The timeline hold timed out.",
      { timeout: STEP_TIMEOUT_MS }
    );
    const fixedCredit = await experimentPage
      .locator("#fixed-hold-credit")
      .evaluate((element) => Number(element.textContent));
    expect(fixedCredit).toBeCloseTo(0.5);
    expect(Date.now() - startedAt).toBeGreaterThanOrEqual(800);
    await assertNoBackendError(experimentPage);
  });
});

test("timeline hold preserves a reload-required page until release", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold_reload"
  );

  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "This page requires a full reload after its hold.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect
      .poll(
        () =>
          experimentPage.evaluate(
            () => typeof window.holdReloadMarker
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe("object");
    const markerPageUuid = await experimentPage.evaluate(
      () => window.holdReloadMarker.pageUuid
    );
    await experimentPage.locator("#next-button").click();
    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    expect(
      await experimentPage.evaluate(
        (uuid) =>
          window.holdReloadMarker.pageUuid === uuid &&
          window.pageUuid === uuid,
        markerPageUuid
      )
    ).toBe(true);

    await expect(experimentPage.locator("#main-body")).toContainText(
      "The reload-required hold finished.",
      { timeout: HOLD_WAKE_TIMEOUT_MS }
    );
    expect(
      await experimentPage.evaluate(
        () => typeof window.holdReloadMarker === "undefined"
      )
    ).toBe(true);
    await assertNoBackendError(experimentPage);
  });
});

test("timeline hold preserves same-session page identity", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold_same_session"
  );

  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#hold-session-marker")).toHaveText(
      "First session page",
      { timeout: STEP_TIMEOUT_MS }
    );
    await experimentPage.locator("#next-button").click();
    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });

    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => ({
            messageCount: window.holdSessionMessages.length,
            step: psynet.page.contents.step
          })),
        { timeout: HOLD_WAKE_TIMEOUT_MS }
      )
      .toEqual({ messageCount: 1, step: 2 });
    await expect(experimentPage.locator("#hold-session-marker")).toHaveText(
      "First session page"
    );
    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toHaveCount(0);
    // Same-session updates keep the existing DOM; hold resume must re-enable
    // controls (Unity listens for pageUpdated; HTML Next is for non-Unity use).
    await expect(experimentPage.locator("#next-button")).toBeEnabled();
    const controlsDisabled = await experimentPage.evaluate(() => ({
      next: document.querySelector("#next-button")?.disabled ?? null,
      response: document.querySelector(".response")?.disabled ?? null,
    }));
    expect(controlsDisabled.next).toBe(false);
    await expect(
      experimentPage.locator("#intentionally-disabled-response")
    ).toBeDisabled();
    await expect(experimentPage.locator("#next-button-spinner")).toBeHidden();
    await expect(experimentPage.locator("#next-button-text")).toBeVisible();
    const nextButtonInlineSize = await experimentPage
      .locator("#next-button")
      .evaluate((button) => ({
        height: button.style.height,
        width: button.style.width
      }));
    expect(nextButtonInlineSize).toEqual({ height: "", width: "" });
    await assertNoBackendError(experimentPage);
  });
});

test("trial feedback processing uses an in-place timeline hold", { tag: "@both" }, async ({
  page,
  context
}) => {
  const experimentDir = path.resolve(
    "tests/playwright/experiments/timeline_hold_feedback"
  );

  await withExperiment(page, context, experimentDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Choose a response before feedback processing.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await experimentPage
      .getByRole("button", { name: "response", exact: true })
      .click();

    await expect(
      experimentPage.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Choose a response before feedback processing."
    );
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Asynchronous feedback is ready.",
      { timeout: HOLD_WAKE_TIMEOUT_MS }
    );
    await assertNoBackendError(experimentPage);
  });
});

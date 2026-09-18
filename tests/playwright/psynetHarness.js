const { spawn } = require("child_process");
const fs = require("fs");
const net = require("net");
const path = require("path");
const readline = require("readline");
const { expect } = require("@playwright/test");

const URL_IN_TEXT_RE = /https?:\/\/[^\s"'<>]+/g;

const PSYNET_ERROR_SELECTORS = ["#error-text", "#error-text-main"];
let latestBackendLogPath = null;
const DEBUG_PORT = Number(process.env.PSYNET_DEBUG_PORT || 5000);

function parseBoolEnv(name, defaultValue = false) {
  if (process.env[name] === undefined) {
    return defaultValue;
  }
  const value = String(process.env[name]).trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}

function normalizeLogUrl(urlLike) {
  if (!urlLike) {
    return null;
  }
  // Strip trailing punctuation frequently attached in log lines.
  return urlLike.replace(/[),.;]+$/, "");
}

function extractRecruitmentUrlFromLine(line) {
  if (!line) {
    return null;
  }
  const urls = line.match(URL_IN_TEXT_RE) || [];
  for (const rawUrl of urls) {
    const candidate = normalizeLogUrl(rawUrl);
    try {
      const parsed = new URL(candidate);
      if (!/^https?:$/.test(parsed.protocol)) {
        continue;
      }
      if (!["localhost", "127.0.0.1"].includes(parsed.hostname)) {
        continue;
      }
      if (parsed.pathname !== "/ad") {
        continue;
      }
      const requiredParams = ["recruiter", "assignmentId", "hitId", "workerId"];
      if (!requiredParams.every((param) => parsed.searchParams.has(param))) {
        continue;
      }
      return parsed.toString();
    } catch (error) {
      // Ignore malformed tokens from log output.
    }
  }
  return null;
}

function getPsynetDebugArgs() {
  const args = ["debug", "local"];

  // Optional compatibility switch for local troubleshooting. We do not force legacy mode.
  if (parseBoolEnv("PSYNET_USE_LEGACY_DEBUG")) {
    args.push("--legacy");
  }

  // Optional extra flags for local debugging; split on whitespace.
  const extraFlags = String(process.env.PSYNET_DEBUG_EXTRA_FLAGS || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  args.push(...extraFlags);

  return args;
}

function isPortInUse(port) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(400);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    const onUnavailable = () => resolve(false);
    socket.once("error", onUnavailable);
    socket.once("timeout", onUnavailable);
    socket.connect(port, "127.0.0.1");
  });
}

async function waitForPortToBeFree(port, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!(await isPortInUse(port))) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return !(await isPortInUse(port));
}

function killProcessTree(proc, signal) {
  if (!proc || !proc.pid) {
    return;
  }
  try {
    process.kill(-proc.pid, signal);
  } catch (error) {
    if (!error || error.code !== "ESRCH") {
      throw error;
    }
  }
}

function isParticipantPageUrl(url) {
  if (!url) {
    return false;
  }
  return /http:\/\/(?:localhost|127\.0\.0\.1):\d+\/(ad|consent|start|timeline|questionnaire|recruiter-exit)\b/.test(
    url
  );
}

async function closeAuxiliaryPages(context, keepPage) {
  for (const existingPage of context.pages()) {
    if (existingPage === keepPage || existingPage.isClosed()) {
      continue;
    }
    if (!isParticipantPageUrl(existingPage.url())) {
      await existingPage.close().catch(() => {});
    }
  }
}

async function resolveParticipantPage(context, fallbackPage, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const pages = context.pages();
    for (const candidate of pages) {
      if (!candidate.isClosed() && isParticipantPageUrl(candidate.url())) {
        return candidate;
      }
    }
    if (!fallbackPage.isClosed() && isParticipantPageUrl(fallbackPage.url())) {
      return fallbackPage;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return fallbackPage;
}

function resolvePsynetCommand() {
  if (process.env.PSYNET_CMD) {
    return process.env.PSYNET_CMD;
  }
  const venvPsynet = path.join(process.cwd(), ".venv", "bin", "psynet");
  if (fs.existsSync(venvPsynet)) {
    return venvPsynet;
  }
  return "psynet";
}

function resolvePsynetLaunch() {
  const debugArgs = getPsynetDebugArgs();
  const psynetCmd = resolvePsynetCommand();

  // In some environments, psynet debug local is only reliable when launched through uv.
  if (parseBoolEnv("PSYNET_USE_UV_RUN")) {
    const uvRunTarget = process.env.PSYNET_UV_RUN_TARGET || psynetCmd;
    return {
      cmd: "uv",
      args: ["run", uvRunTarget, ...debugArgs]
    };
  }

  return {
    cmd: psynetCmd,
    args: debugArgs
  };
}

// ---- Backend process lifecycle ---------------------------------------------
function startExperiment(experimentDir) {
  const launch = resolvePsynetLaunch();
  if (!launch || !launch.cmd) {
    throw new Error("Unable to resolve psynet command.");
  }
  const logsDir = path.join(process.cwd(), "test-results", "psynet-backend-logs");
  fs.mkdirSync(logsDir, { recursive: true });
  const experimentName = path.basename(experimentDir);
  const logPath = path.join(logsDir, `${experimentName}-${Date.now()}.log`);
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  latestBackendLogPath = logPath;

  const proc = spawn(launch.cmd, launch.args, {
    detached: true,
    cwd: experimentDir,
    env: {
      ...process.env,
      KEEP_OLD_CHROME_WINDOWS_IN_DEBUG_MODE: "1",
      BROWSER: "false",
      SKIP_PYTHON_VERSION_CHECK: "1"
    },
    stdio: ["ignore", "pipe", "pipe"]
  });

  const outputLines = [];
  let resolveUrl;
  let rejectUrl;
  const urlPromise = new Promise((resolve, reject) => {
    resolveUrl = resolve;
    rejectUrl = reject;
  });

  const handleLine = (line) => {
    outputLines.push(line);
    logStream.write(`${line}\n`);

    if (line.includes("Address already in use")) {
      rejectUrl(
        new Error(
          `Startup failed because port ${DEBUG_PORT} is already in use.\n` +
            `Recent output:\n${outputLines.slice(-50).join("\n")}\n` +
            `Backend log: ${logPath}`
        )
      );
    }
    if (outputLines.length > 200) {
      outputLines.shift();
    }
    const recruitmentUrl = extractRecruitmentUrlFromLine(line);
    if (recruitmentUrl) {
      resolveUrl(recruitmentUrl);
    }
  };

  const rlOut = readline.createInterface({ input: proc.stdout });
  rlOut.on("line", handleLine);

  const rlErr = readline.createInterface({ input: proc.stderr });
  rlErr.on("line", handleLine);

  const timeoutMs = Number(process.env.PSYNET_RECRUITMENT_TIMEOUT_MS || 120000);
  const timeoutHandle = setTimeout(() => {
    const tail = outputLines.slice(-50).join("\n");
    rejectUrl(
      new Error(
        `Timed out waiting for recruitment URL after ${timeoutMs}ms.\n` +
          `Command: ${launch.cmd} ${launch.args.join(" ")}\n` +
          `Recent output:\n${tail}\n` +
          `Backend log: ${logPath}`
      )
    );
  }, timeoutMs);

  urlPromise.finally(() => clearTimeout(timeoutHandle));

  proc.on("exit", (code) => {
    logStream.end();
    if (code !== 0) {
      const tail = outputLines.slice(-50).join("\n");
      rejectUrl(
        new Error(
          `psynet debug local exited with code ${code}.\n` +
            `Command: ${launch.cmd} ${launch.args.join(" ")}\n` +
            `Recent output:\n${tail}\n` +
            `Backend log: ${logPath}`
        )
      );
    }
  });

  return {
    proc,
    urlPromise
  };
}

async function stopExperiment(proc) {
  if (!proc) {
    return;
  }

  const waitForExit = (timeoutMs) =>
    new Promise((resolve) => {
      if (proc.exitCode !== null || proc.signalCode !== null) {
        resolve(true);
        return;
      }
      let finished = false;
      const done = (didExit) => {
        if (finished) {
          return;
        }
        finished = true;
        resolve(didExit);
      };
      const timer = setTimeout(() => {
        proc.off("exit", onExit);
        done(false);
      }, timeoutMs);
      const onExit = () => {
        clearTimeout(timer);
        done(true);
      };
      proc.once("exit", onExit);
    });

  let exited = proc.exitCode !== null || proc.signalCode !== null;
  if (!exited) {
    killProcessTree(proc, "SIGINT");
    exited = await waitForExit(3000);
  }

  if (!exited) {
    killProcessTree(proc, "SIGKILL");
    await waitForExit(3000);
  }

  // Detached child processes can outlive the parent; ensure the port is actually free.
  await waitForPortToBeFree(DEBUG_PORT, 10000);
  if (await isPortInUse(DEBUG_PORT)) {
    killProcessTree(proc, "SIGKILL");
    await waitForPortToBeFree(DEBUG_PORT, 10000);
  }
}

// ---- Browser page selection / backend error detection ----------------------
async function beginExperiment(page, context, url) {
  const isPostAdParticipantPageUrl = (candidateUrl) =>
    /http:\/\/(?:localhost|127\.0\.0\.1):\d+\/(consent|start|timeline|questionnaire|recruiter-exit)\b/.test(
      candidateUrl || ""
    );

  const waitForPostAdParticipantPage = async (timeoutMs = 20000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      for (const candidate of context.pages()) {
        if (candidate.isClosed()) {
          continue;
        }
        if (isPostAdParticipantPageUrl(candidate.url())) {
          return candidate;
        }
      }
      await page.waitForTimeout(100);
    }
    return null;
  };

  await page.goto(url);
  await page.waitForSelector("#begin-button, button.btn-primary", { timeout: 30000 });
  await page.click("#begin-button, button.btn-primary");

  let targetPage = await waitForPostAdParticipantPage(20000);
  if (!targetPage) {
    targetPage = page;
  }
  targetPage = await resolveParticipantPage(context, targetPage);
  await targetPage.waitForLoadState("domcontentloaded");
  await closeAuxiliaryPages(context, targetPage);
  return targetPage;
}

async function getPossibleBackendError(page) {
  if (!page || page.isClosed()) {
    return null;
  }

  const details = await page
    .evaluate((selectors) => {
      const hasErrorTemplate = selectors.every(
        (selector) => document.querySelector(selector) !== null
      );
      const title = (document?.title || "").trim();
      const headerText = (document.querySelector("#header")?.textContent || "").trim();
      const errorText = (document.querySelector("#error-text")?.textContent || "").trim();
      const detailText = (
        document.querySelector("#error-text-main")?.textContent || ""
      ).trim();

      return {
        hasErrorTemplate,
        title,
        headerText,
        errorText,
        detailText
      };
    }, PSYNET_ERROR_SELECTORS)
    .catch(() => null);

  if (!details || !details.hasErrorTemplate) {
    return null;
  }

  return {
    title: details.title,
    headerText: details.headerText,
    errorText: details.errorText,
    detailText: details.detailText
  };
}

async function assertNoBackendError(page) {
  const error = await getPossibleBackendError(page);
  if (!error) {
    return;
  }

  throw new Error(
    `PsyNet backend error page detected.\n` +
      `URL: ${page.url()}\n` +
      `Title: ${error.title || "<none>"}\n` +
      `Header: ${error.headerText || "<none>"}\n` +
      `Error text: ${error.errorText || "<none>"}\n` +
      `Details: ${error.detailText || "<none>"}\n` +
      `Backend log: ${latestBackendLogPath || "<unknown>"}`
  );
}

async function getPageUuid(page) {
  try {
    return await page.evaluate(() => window.pageUuid);
  } catch (e) {
    return null;
  }
}

// ---- Timeline interaction helpers ------------------------------------------
async function waitForPageChange(page, oldUuid, timeoutMs) {
  if (!oldUuid) {
    await page.waitForTimeout(500);
    return;
  }
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await assertNoBackendError(page);
    const changed = await page
      .evaluate((uuid) => window.pageUuid && window.pageUuid !== uuid, oldUuid)
      .catch(() => false);
    if (changed) {
      return;
    }
    await page.waitForTimeout(200);
  }
  throw new Error(`Timed out waiting for page change after ${timeoutMs}ms.`);
}

async function waitForTimelinePageReady(page, timeoutMs = 30000) {
  await expect
    .poll(
      async () => {
        await assertNoBackendError(page);
        return page
          .evaluate(() => ({
            readyFlag: !!window.psynet?.pageReady,
            readyMarker:
              document.getElementById("main-body")?.getAttribute("data-page-ready") ||
              null
          }))
          .catch(() => ({ readyFlag: false, readyMarker: null }));
      },
      { timeout: timeoutMs }
    )
    .toEqual({
      readyFlag: true,
      readyMarker: "true"
    });
}

async function assertInplaceTimelinePathActive(page, timeoutMs = 10000) {
  await waitForTimelinePageReady(page, Math.max(timeoutMs, 5000));
  await expect
    .poll(
      async () => {
        await assertNoBackendError(page);
        return page
          .evaluate(() => ({
            flag:
              window.psynetTemplateData?.flags?.inplaceTimelineTransitions ?? null,
            directFragmentTransport:
              typeof window.psynet?.loadNextTimelinePageFromResponse === "function"
          }))
          .catch(() => ({ flag: null, directFragmentTransport: false }));
      },
      { timeout: timeoutMs }
    )
    .toEqual({
      flag: true,
      directFragmentTransport: true
    });
}

async function assertLegacyTimelinePathActive(page, timeoutMs = 10000) {
  await waitForTimelinePageReady(page, Math.max(timeoutMs, 5000));
  await expect
    .poll(
      async () => {
        await assertNoBackendError(page);
        return page
          .evaluate(() => ({
            flag:
              window.psynetTemplateData?.flags?.inplaceTimelineTransitions ?? null
          }))
          .catch(() => ({ flag: null }));
      },
      { timeout: timeoutMs }
    )
    .toEqual({
      flag: false
    });
}

function isInplaceTimelineModeEnabled() {
  return parseBoolEnv("inplace_timeline_transitions", true);
}

async function assertExpectedTimelinePathActive(page, timeoutMs = 10000) {
  if (isInplaceTimelineModeEnabled()) {
    await assertInplaceTimelinePathActive(page, timeoutMs);
    return;
  }
  await assertLegacyTimelinePathActive(page, timeoutMs);
}

async function kickoffTrial(page) {
  await waitForTimelinePageReady(page, 30000);
  if ((await page.locator("#audio-prompt-play").count()) > 0) {
    if (await page.locator("#audio-prompt-play").isEnabled()) {
      await page.click("#audio-prompt-play", { force: true }).catch(() => {});
    }
  }
  if ((await page.locator("#btn-record-record").count()) > 0) {
    if (await page.locator("#btn-record-record").isEnabled()) {
      await page.click("#btn-record-record", { force: true }).catch(() => {});
    }
  }
  if ((await page.locator("#buttonStart").count()) > 0) {
    if (await page.locator("#buttonStart").isEnabled()) {
      await page.click("#buttonStart", { force: true }).catch(() => {});
    }
  }
}

async function clickNext(page, timeoutMs) {
  const oldUuid = await getPageUuid(page);
  await page.click("#next-button");
  await waitForPageChange(page, oldUuid, timeoutMs);
}

async function clickNextAndWait(page, timeoutMs = 60000) {
  await waitForNextEnabled(page, timeoutMs);
  await clickNext(page, timeoutMs);
}

async function waitForNextEnabled(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await assertNoBackendError(page);
    const isEnabled = await page
      .evaluate(() => {
        const btn = document.getElementById("next-button");
        return !!btn && !btn.hasAttribute("disabled");
      })
      .catch(() => false);
    if (isEnabled) {
      return;
    }
    await page.waitForTimeout(200);
  }
  const debugInfo = await getNextButtonDebugInfo(page);
  throw new Error(
    `Timed out waiting for next button to be enabled after ${timeoutMs}ms.\n` +
      `Debug context: ${JSON.stringify(debugInfo, null, 2)}`
  );
}

async function waitForAudioRecordingReady(page, timeoutMs = 45000) {
  await expect
    .poll(
      async () => {
        const [blobInfo, playEnabled, nextEnabled] = await Promise.all([
          page
            .evaluate(() => {
              const blob = psynet?.response?.staged?.blobs?.audioRecording || null;
              return {
                exists: !!blob,
                size: blob && typeof blob.size === "number" ? blob.size : 0
              };
            })
            .catch(() => ({ exists: false, size: 0 })),
          page
            .locator("#btn-record-play-recording")
            .isEnabled()
            .catch(() => false),
          page.locator("#next-button").isEnabled().catch(() => false)
        ]);
        return (blobInfo.exists && blobInfo.size > 0) || playEnabled || nextEnabled;
      },
      { timeout: timeoutMs }
    )
    .toBe(true);
}

async function waitForVideoRecordingReady(
  page,
  { timeoutMs = 45000, requireScreen = false } = {}
) {
  await expect
    .poll(
      async () => {
        const [blobInfo, playEnabled, nextEnabled] = await Promise.all([
          page
            .evaluate(() => {
              const camera = psynet?.response?.staged?.blobs?.cameraRecording || null;
              const screen = psynet?.response?.staged?.blobs?.screenRecording || null;
              return {
                cameraExists: !!camera,
                cameraSize:
                  camera && typeof camera.size === "number" ? camera.size : 0,
                screenExists: !!screen,
                screenSize:
                  screen && typeof screen.size === "number" ? screen.size : 0
              };
            })
            .catch(() => ({
              cameraExists: false,
              cameraSize: 0,
              screenExists: false,
              screenSize: 0
            })),
          page
            .locator("#btn-record-play-recording")
            .isEnabled()
            .catch(() => false),
          page.locator("#next-button").isEnabled().catch(() => false)
        ]);
        const cameraReady = blobInfo.cameraExists && blobInfo.cameraSize > 0;
        const screenReady = blobInfo.screenExists && blobInfo.screenSize > 0;
        return (
          (cameraReady && (!requireScreen || screenReady)) ||
          playEnabled ||
          nextEnabled
        );
      },
      { timeout: timeoutMs }
    )
    .toBe(true);
}

async function getNextButtonDebugInfo(page) {
  const url = page.url();
  const pageInfo = await page
    .evaluate(() => {
      const button = document.getElementById("next-button");
      const slider = document.getElementById("sliderpage_slider");
      const promptText = (document.getElementById("prompt-text")?.textContent || "")
        .replace(/\s+/g, " ")
        .trim();
      const mainBodyPreview = (document.getElementById("main-body")?.textContent || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 250);
      const trialEvents = (psynet?.trial?.eventLog || []).slice(-20).map((event) => ({
        eventType: event.eventType,
        localTime: new Date(event.localTime).toISOString(),
        info: event.info ?? null
      }));

      return {
        promptText,
        mainBodyPreview,
        trialState: psynet?.trial?.state ?? null,
        trialInProgress: !!psynet?.trial?.inProgress,
        nextButton: button
          ? {
              text: (button.textContent || "").trim(),
              disabled: button.hasAttribute("disabled"),
              className: button.className
            }
          : null,
        slider: slider
          ? {
              value: slider.value,
              rawValue: slider.getAttribute("raw-value"),
              outputValue: slider.getAttribute("output-value"),
              disabled: slider.hasAttribute("disabled")
            }
          : null,
        activeSounds: (psynet?.media?.sounds || []).map((sound) => sound.stimulusId),
        trialEvents
      };
    })
    .catch((error) => ({ evaluateError: error.message }));
  return { url, ...pageInfo };
}

async function getPromptText(page) {
  const prompt = page.locator("#prompt-text");
  if ((await prompt.count()) === 0) {
    return "";
  }
  return (await prompt.first().innerText()).trim();
}

async function advanceOneStep(page, options = {}) {
  const timeoutMs = options.timeoutMs ?? 60000;

  const nextButton = page.locator("#next-button");
  if ((await nextButton.count()) === 0) {
    return false;
  }

  if (!(await nextButton.isEnabled())) {
    await kickoffTrial(page);
    await waitForNextEnabled(page, Math.min(timeoutMs, 15000)).catch(() => {});
  }

  if (!(await nextButton.isEnabled())) {
    return false;
  }

  await clickNext(page, timeoutMs);
  return true;
}

async function advanceUntilPromptContains(page, text, options = {}) {
  const maxSteps = options.maxSteps ?? 20;
  const stallLimit = options.stallLimit ?? 6;
  const timeoutMs = options.timeoutMs ?? 60000;
  let stalledAttempts = 0;

  for (let step = 0; step < maxSteps; step += 1) {
    const promptText = await getPromptText(page);
    if (promptText.includes(text)) {
      return;
    }

    const progressed = await advanceOneStep(page, { timeoutMs });
    if (progressed) {
      stalledAttempts = 0;
      continue;
    }

    stalledAttempts += 1;
    if (stalledAttempts >= stallLimit) {
      throw new Error(
        `Could not progress to prompt containing "${text}". Current prompt: "${promptText}".`
      );
    }
    await page.waitForTimeout(1000);
  }

  throw new Error(`Did not reach prompt containing "${text}" within ${maxSteps} steps.`);
}

async function waitForPromptContains(page, text, timeout = 90000) {
  await expect
    .poll(
      () =>
        page
          .evaluate((expectedText) => {
            const promptText = document.getElementById("prompt-text")?.innerText || "";
            const mainBodyText = document.getElementById("main-body")?.innerText || "";
            return (
              promptText.includes(expectedText) || mainBodyText.includes(expectedText)
            );
          }, text)
          .catch(() => false),
      { timeout }
    )
    .toBe(true);
}

async function waitForMainBodyContains(page, text, timeout = 90000) {
  await expect
    .poll(
      () =>
        page
          .evaluate((expectedText) => {
            const mainBodyText = document.getElementById("main-body")?.innerText || "";
            return mainBodyText.includes(expectedText);
          }, text)
          .catch(() => false),
      { timeout }
    )
    .toBe(true);
}

async function withExperiment(page, context, experimentDir, runTest) {
  const reuseRecruitmentUrl = process.env.PSYNET_RECRUITMENT_URL || null;
  const usingExistingBackend = !!reuseRecruitmentUrl;
  const experimentHandle = usingExistingBackend
    ? { proc: null, urlPromise: Promise.resolve(reuseRecruitmentUrl) }
    : startExperiment(experimentDir);
  const { proc, urlPromise } = experimentHandle;

  let experimentPage = null;
  try {
    const url = await urlPromise;
    const runUrl = usingExistingBackend ? withFreshParticipantIds(url) : url;
    experimentPage = await beginExperiment(page, context, runUrl);
    return await runTest(experimentPage);
  } finally {
    if (experimentPage && !experimentPage.isClosed()) {
      await experimentPage.goto("about:blank").catch(() => {});
    }
    if (!usingExistingBackend) {
      await stopExperiment(proc);
    }
  }
}

function startResponseSubmitTracker(page) {
  let count = 0;
  const onResponse = (response) => {
    const request = response.request();
    if (
      request.method() === "POST" &&
      response.ok() &&
      response.url().includes("/response")
    ) {
      count += 1;
    }
  };
  page.on("response", onResponse);
  return {
    getCount: () => count,
    stop: () => page.off("response", onResponse)
  };
}

async function waitForResponseSubmitIncrement(
  tracker,
  baselineCount,
  increment = 1,
  timeout = 120000
) {
  await expect
    .poll(() => tracker.getCount(), { timeout })
    .toBeGreaterThanOrEqual(baselineCount + increment);
}

async function waitForPageLoaded(page, timeoutMs = 120000) {
  await page.waitForFunction(() => window.psynet?.pageLoaded === true, {
    timeout: timeoutMs
  });
}

async function completeInitialGateway(page, timeout = 120000) {
  await expect(page.locator("body")).toContainText(
    "To proceed, click the button below.",
    { timeout }
  );
  const gatewayButton = page.locator("#consent");
  await expect(gatewayButton).toBeVisible({ timeout });
  await expect(gatewayButton).toBeEnabled({ timeout });
  await gatewayButton.click();
}

async function clickConsentButton(page, timeout = 120000) {
  const consentButton = page.locator("#consent");
  await expect(consentButton).toBeVisible({ timeout });
  await expect(consentButton).toBeEnabled({ timeout });
  await waitForPageLoaded(page, timeout);
  await consentButton.click();
}

async function captureTrialEventBaseline(page) {
  return page
    .evaluate(() => (psynet?.trial?.eventLog || []).length)
    .catch(() => 0);
}

async function waitForTrialEvents(
  page,
  eventTypes,
  { timeoutMs = 30000, baselineIndex = 0 } = {}
) {
  await expect
    .poll(
      async () => {
        const seenEventTypes = await page
          .evaluate((baseline) =>
            (() => {
              const eventLog = psynet?.trial?.eventLog || [];
              const startIndex = eventLog.length >= baseline ? baseline : 0;
              return eventLog.slice(startIndex).map((event) => event.eventType);
            })(),
            baselineIndex
          )
          .catch(() => []);
        return eventTypes.every((eventType) => seenEventTypes.includes(eventType));
      },
      { timeout: timeoutMs }
    )
    .toBe(true);
}

function withFreshParticipantIds(rawUrl, label = null) {
  const url = new URL(rawUrl);
  const randomSuffix = Math.random().toString(36).slice(2, 10);
  const suffix = label ? `${label}_${randomSuffix}` : randomSuffix;
  if (url.searchParams.has("assignmentId")) {
    url.searchParams.set("assignmentId", `a_${suffix}`);
  }
  if (url.searchParams.has("hitId")) {
    url.searchParams.set("hitId", `h_${suffix}`);
  }
  if (url.searchParams.has("workerId")) {
    url.searchParams.set("workerId", `w_${suffix}`);
  }
  return url.toString();
}

async function clickFinish(page, timeoutMs) {
  await page.click("#Finish");
  await page.waitForFunction(
    () => window.location.href.includes("recruiter-exit"),
    { timeout: timeoutMs }
  ).catch(() => {});
}

async function advanceUntilFinish(page, options = {}) {
  const maxSteps = options.maxSteps ?? 120;
  const timeoutMs = options.timeoutMs ?? 90000;

  for (let i = 0; i < maxSteps; i += 1) {
    const finish = page.locator("#Finish");
    if ((await finish.count()) > 0 && (await finish.isVisible())) {
      await clickFinish(page, timeoutMs);
      return;
    }

    const nextButton = page.locator("#next-button");
    if ((await nextButton.count()) > 0) {
      if (await nextButton.isEnabled()) {
        await clickNext(page, timeoutMs);
        continue;
      }
      const oldUuid = await getPageUuid(page);
      await kickoffTrial(page);
      await page.waitForTimeout(1000);
      if (await nextButton.isEnabled()) {
        await clickNext(page, timeoutMs);
        continue;
      }

      // Some pages (e.g., recording/upload pages) need real-time processing before
      // the next button becomes available. Wait for natural readiness.
      await waitForNextEnabled(page, Math.min(timeoutMs, 30000)).catch(() => {});
      if (await nextButton.isEnabled()) {
        await clickNext(page, timeoutMs);
        continue;
      }

      const changed = await page
        .evaluate((uuid) => !!window.pageUuid && window.pageUuid !== uuid, oldUuid)
        .catch(() => false);
      if (changed) {
        continue;
      }

      await assertNoBackendError(page);
      await page.waitForTimeout(500);
      continue;
    }

    const oldUuid = await getPageUuid(page);
    await kickoffTrial(page);
    await waitForPageChange(page, oldUuid, Math.min(timeoutMs, 30000)).catch(
      () => {}
    );
    const changed = await page
      .evaluate((uuid) => !!window.pageUuid && window.pageUuid !== uuid, oldUuid)
      .catch(() => false);
    if (changed) {
      continue;
    }
    await assertNoBackendError(page);
    await page.waitForTimeout(500);
  }

  throw new Error("Experiment did not finish within expected steps.");
}

module.exports = {
  advanceUntilFinish,
  advanceUntilPromptContains,
  assertNoBackendError,
  beginExperiment,
  clickConsentButton,
  clickFinish,
  clickNextAndWait,
  completeInitialGateway,
  captureTrialEventBaseline,
  assertExpectedTimelinePathActive,
  assertInplaceTimelinePathActive,
  assertLegacyTimelinePathActive,
  getPageUuid,
  isInplaceTimelineModeEnabled,
  startExperiment,
  startResponseSubmitTracker,
  stopExperiment,
  waitForResponseSubmitIncrement,
  waitForMainBodyContains,
  waitForPromptContains,
  waitForTrialEvents,
  waitForAudioRecordingReady,
  waitForVideoRecordingReady,
  waitForTimelinePageReady,
  withExperiment,
  withFreshParticipantIds,
  waitForNextEnabled,
  waitForPageChange
};

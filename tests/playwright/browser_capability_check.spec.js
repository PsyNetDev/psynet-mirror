const path = require("path");
const { test, expect } = require("./fixtures");
const {
  assertNoBackendError,
  completeInitialGateway,
  withExperiment,
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const EXPERIMENT_DIR = "tests/playwright/experiments/browser_capability_check";
const NO_PRESCREENER_DIR = "tests/playwright/experiments/audio_no_prescreener";

test(
  "audio_playback: capability check passes in Chrome and reaches next page",
  { tag: "@both" },
  async ({ page, context }) => {
    const absDir = path.resolve(EXPERIMENT_DIR);
    await withExperiment(page, context, absDir, async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await expect(
        experimentPage.locator("#capability-check-passed")
      ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
      await assertNoBackendError(experimentPage);
    });
  }
);

test(
  "audio_playback: capability check fail routes to unsuccessful end page",
  { tag: "@both" },
  async ({ page, context }) => {
    // Remove AudioContext before any page script runs so the audio_playback
    // check in browser-capability-check.js returns false.
    await context.addInitScript(() => {
      delete window.AudioContext;
      delete window.webkitAudioContext;
    });

    const absDir = path.resolve(EXPERIMENT_DIR);
    await withExperiment(page, context, absDir, async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await expect(experimentPage.locator("body")).toContainText(
        "Unfortunately we have to stop early.",
        { timeout: STEP_TIMEOUT_MS }
      );
      await assertNoBackendError(experimentPage);
    });
  }
);

test(
  "audio_playback: missing AudioContext does not crash page init without prescreener",
  { tag: "@both" },
  async ({ page, context }) => {
    // Without BrowserCapabilityCheck in the timeline, a missing AudioContext
    // must not crash page initialisation. NullAudioContext replaces the null
    // that initAudioContext previously left behind, so trial.init() completes
    // and the page loads normally. Audio calls (decodeAudioData etc.) would
    // throw a descriptive error if reached, but that path requires an audio
    // control and is not exercised here.
    await context.addInitScript(() => {
      delete window.AudioContext;
      delete window.webkitAudioContext;
    });

    const absDir = path.resolve(NO_PRESCREENER_DIR);
    await withExperiment(page, context, absDir, async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await expect(
        experimentPage.locator("#page-loaded")
      ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
      await assertNoBackendError(experimentPage);
    });
  }
);

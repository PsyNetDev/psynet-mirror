const path = require("path");
const { test, expect } = require("./fixtures");
const {
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  waitForTimelinePageReady,
  withExperiment,
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 60000;
const EXPERIMENT_DIR = path.resolve("tests/playwright/experiments/enable_audio");

// Browsers keep audio suspended until the participant clicks on the page, and
// PsyNet asks for that click ("Turn on sound") only on pages that use audio.
// Playwright's own input counts as a click, so whether a real engine refuses
// audio is not reproducible here; the test makes the browser refuse instead:
// contexts report "suspended" and resume() never settles until allowed.
async function refuseAudioUntilAllowed(context) {
  await context.addInitScript(() => {
    if (!window.BaseAudioContext) {
      return;
    }
    const proto = BaseAudioContext.prototype;
    const state = Object.getOwnPropertyDescriptor(proto, "state").get;
    Object.defineProperty(proto, "state", {
      get() {
        return window.__allowAudio ? state.call(this) : "suspended";
      },
    });
    const resume = AudioContext.prototype.resume;
    AudioContext.prototype.resume = function () {
      return window.__allowAudio ? resume.call(this) : new Promise(() => {});
    };
  });
}

async function enableAudio(page) {
  await page.evaluate(() => {
    window.__allowAudio = true;
  });
  await page.locator("#resume-button").click();
  await waitForTimelinePageReady(page, STEP_TIMEOUT_MS);
  await expect(page.locator("#resume-modal")).toBeHidden();
  expect(await page.evaluate(() => window.psynet.media.audioContext.state)).toBe(
    "running"
  );
}

test(
  "asks to turn on sound only on audio pages the browser blocks",
  { tag: "@both" },
  async ({ page, context, browserName }) => {
    test.skip(
      browserName === "chromium",
      "The chromium project starts audio without a click."
    );
    await refuseAudioUntilAllowed(context);
    await withExperiment(page, context, EXPERIMENT_DIR, async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await expect(experimentPage.locator("#no-audio-page")).toBeVisible({
        timeout: STEP_TIMEOUT_MS,
      });
      await waitForTimelinePageReady(experimentPage, STEP_TIMEOUT_MS);
      await expect(experimentPage.locator("#resume-modal")).toBeHidden();

      await clickNextAndWait(experimentPage);
      await expect(experimentPage.locator("#audio-page")).toBeVisible({
        timeout: STEP_TIMEOUT_MS,
      });
      const enableButton = experimentPage.locator("#resume-button");
      await expect(enableButton).toBeVisible({ timeout: STEP_TIMEOUT_MS });

      // A click the browser still refuses brings the dialog back.
      await enableButton.click();
      await expect(enableButton).toBeVisible({ timeout: STEP_TIMEOUT_MS });
      await enableAudio(experimentPage);

      // The next page without audio does not ask, even if audio is blocked.
      await experimentPage.evaluate(() => {
        window.__allowAudio = false;
      });
      await clickNextAndWait(experimentPage);
      await expect(experimentPage.locator("#no-audio-again")).toBeVisible({
        timeout: STEP_TIMEOUT_MS,
      });
      await waitForTimelinePageReady(experimentPage, STEP_TIMEOUT_MS);
      await expect(experimentPage.locator("#resume-modal")).toBeHidden();

      // JSSynth plays through Tone.js and declares that it needs audio.
      await clickNextAndWait(experimentPage);
      await expect(experimentPage.locator("#synth-page")).toBeVisible({
        timeout: STEP_TIMEOUT_MS,
      });
      await expect(enableButton).toBeVisible({ timeout: STEP_TIMEOUT_MS });
      await enableAudio(experimentPage);
      await assertNoBackendError(experimentPage);
    });
  }
);

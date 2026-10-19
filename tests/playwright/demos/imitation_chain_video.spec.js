const path = require("path");
const { test, expect } = require("../fixtures");

const {
  advanceUntilPromptContains,
  captureTrialEventBaseline,
  clickFinish,
  clickNextAndWait,
  completeInitialGateway,
  startResponseSubmitTracker,
  waitForNextEnabled,
  waitForResponseSubmitIncrement,
  waitForPromptContains,
  waitForTrialEvents,
  waitForVideoRecordingReady,
  withExperiment
} = require("../psynetHarness");

const PROMPT_TIMEOUT_MS = 90000;
const STEP_TIMEOUT_MS = 120000;

/*
Step summary:
1. Intro gateway and calibration:
   participant clears entry, enters the chain timeline, and completes microphone calibration.
2. Seed trial recording:
   participant sees the first tracing task, records video, and submits the seed response.
3. Non-seed prompt and recording:
   participant watches the exemplar video prompt, records an imitation, and submits.
4. Remaining chain progression:
   participant advances through later chain nodes and reaches completion.

Intentionally not covered:
- Node/chain statistical properties across many participants.
- Detailed gesture/video-content correctness beyond recording existence and timing.
*/

async function expectMainBodyContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#main-body")).toContainText(text, { timeout });
}

async function getStagedCameraRecordingInfo(page) {
  return page.evaluate(() => {
    const blob = psynet?.response?.staged?.blobs?.cameraRecording || null;
    if (!blob) {
      return { exists: false, size: 0, type: null };
    }
    return {
      exists: true,
      size: typeof blob.size === "number" ? blob.size : 0,
      type: typeof blob.type === "string" ? blob.type : null
    };
  });
}

async function expectVideoPromptReady(page, timeout = PROMPT_TIMEOUT_MS) {
  const videoPrompt = page.locator("video#prompt");
  await expect(videoPrompt).toBeVisible({ timeout });
  await expect
    .poll(
      () =>
        videoPrompt.evaluate((video) => ({
          hasSource: Boolean(video.currentSrc),
          hasDuration: Number(video.duration) > 0
        })),
      { timeout }
    )
    .toMatchObject({ hasSource: true, hasDuration: true });
}

async function completeRemainingChain(page, timeout = STEP_TIMEOUT_MS) {
  const finishButton = page.locator("#Finish");

  for (let step = 0; step < 30; step += 1) {
    if ((await finishButton.count()) > 0 && (await finishButton.isVisible())) {
      await clickFinish(page, timeout);
      return;
    }

    const videoControl = page.locator("#video-control");
    if ((await videoControl.count()) > 0) {
      await waitForVideoRecordingReady(page, { timeoutMs: 45000 });
      await waitForNextEnabled(page, timeout);
      await clickNextAndWait(page, timeout);
      continue;
    }

    const promptText = await page
      .locator("#prompt-text")
      .innerText()
      .catch(() => "");
    if (
      promptText.includes(
        "When you are ready, press next to imitate the figure that you see."
      )
    ) {
      await expectVideoPromptReady(page);
      await clickNextAndWait(page, timeout);
      continue;
    }

    const nextButton = page.locator("#next-button");
    if ((await nextButton.count()) > 0) {
      await clickNextAndWait(page, timeout);
      continue;
    }

    await page.waitForTimeout(500);
  }

  throw new Error("Imitation chain did not reach Finish within expected steps.");
}

test("imitation_chain_video demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/experiments/imitation_chain_video");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    const submitTracker = startResponseSubmitTracker(experimentPage);
    try {
      // Section 0: complete deterministic gateway step.
      await completeInitialGateway(experimentPage);

      // Section 1: verify microphone calibration UI is present and gates progression.
      await expectMainBodyContains(experimentPage, "Please speak into your microphone");
      await expect(experimentPage.locator("#audio-meter")).toBeVisible({
        timeout: PROMPT_TIMEOUT_MS
      });
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // Section 2: verify actual webcam recording flow from UI to submit.
      await waitForPromptContains(experimentPage, "Please trace out a");
      await expect(experimentPage.locator("#video-control")).toBeVisible({
        timeout: PROMPT_TIMEOUT_MS
      });
      const playRecordingButton = experimentPage.locator("#btn-record-play-recording");
      const seedRecordEventBaseline = await captureTrialEventBaseline(experimentPage);
      await waitForVideoRecordingReady(experimentPage, { timeoutMs: 45000 });
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 45000,
        baselineIndex: seedRecordEventBaseline
      });
      await expect(playRecordingButton).toBeEnabled({ timeout: 45000 });
      const stagedRecording = await getStagedCameraRecordingInfo(experimentPage);
      expect(stagedRecording.exists).toBe(true);
      expect(stagedRecording.size).toBeGreaterThan(0);
      if (stagedRecording.type) {
        expect(stagedRecording.type).toContain("video");
      }
      await playRecordingButton.click();

      const seedBaselineResponses = submitTracker.getCount();
      await expect(experimentPage.locator("#next-button")).toBeEnabled({
        timeout: STEP_TIMEOUT_MS
      });
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        seedBaselineResponses,
        1,
        STEP_TIMEOUT_MS
      );

      // Section 3: verify a non-seed trial prompt/record sequence also exercises real UI.
      await advanceUntilPromptContains(
        experimentPage,
        "When you are ready, press next to imitate the figure that you see."
      );
      await expectVideoPromptReady(experimentPage);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expect(experimentPage.locator("#video-control")).toBeVisible({
        timeout: PROMPT_TIMEOUT_MS
      });
      const nonSeedRecordButton = experimentPage.locator("#btn-record-record");
      const nonSeedPlayRecordingButton = experimentPage.locator(
        "#btn-record-play-recording"
      );
      await expect(nonSeedRecordButton).toBeVisible();
      await expect(nonSeedRecordButton).toBeEnabled();

      // Let the auto-recording cycle finish before clicking "Record from start".
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 45000
      });
      const nonSeedRecordEventBaseline = await captureTrialEventBaseline(
        experimentPage
      );
      await nonSeedRecordButton.click();
      await waitForVideoRecordingReady(experimentPage, { timeoutMs: 45000 });
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 45000,
        baselineIndex: nonSeedRecordEventBaseline
      });
      await expect(nonSeedPlayRecordingButton).toBeEnabled({ timeout: 45000 });
      const nonSeedStagedRecording = await getStagedCameraRecordingInfo(experimentPage);
      expect(nonSeedStagedRecording.exists).toBe(true);
      expect(nonSeedStagedRecording.size).toBeGreaterThan(0);
      if (nonSeedStagedRecording.type) {
        expect(nonSeedStagedRecording.type).toContain("video");
      }
      await nonSeedPlayRecordingButton.click();
      const nonSeedBaselineResponses = submitTracker.getCount();
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        nonSeedBaselineResponses,
        1,
        STEP_TIMEOUT_MS
      );

      // Section 4: complete remaining trials after verifying core interaction.
      await completeRemainingChain(experimentPage);
    } finally {
      submitTracker.stop();
    }
  });
});

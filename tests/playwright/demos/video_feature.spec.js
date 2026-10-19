const path = require("path");
const { test, expect } = require("../fixtures");

const {
  advanceUntilFinish,
  captureTrialEventBaseline,
  clickNextAndWait,
  completeInitialGateway,
  startResponseSubmitTracker,
  waitForResponseSubmitIncrement,
  waitForAudioRecordingReady,
  waitForMainBodyContains,
  waitForTrialEvents,
  waitForVideoRecordingReady,
  withExperiment
} = require("../psynetHarness");

const PROMPT_TIMEOUT_MS = 90000;
const STEP_TIMEOUT_MS = 120000;

/*
Step summary:
1. Intro gateway and first video prompt:
   participant clears entry and sees the baseline video prompt page.
2. Video/audio prompt variants:
   participant navigates play-window, muted+audio, and synchronized AV prompt pages.
3. Audio response on video page:
   participant records an audio response, replays it, and submits.
4. Delayed video response page:
   participant records video after countdown behavior, verifies playback, and submits.
5. Dual camera+screen recording page:
   participant records with simultaneous camera and screen capture, replays, and submits.
6. Final playback and finish:
   participant reaches playback/closing pages and finishes the experiment.

Intentionally not covered:
- Exact audiovisual synchronization at sub-frame precision.
- Binary equality of captured camera/screen recordings.
*/

async function expectPromptContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#prompt-text")).toContainText(text, { timeout });
}

async function expectMainBodyContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#main-body")).toContainText(text, { timeout });
}

async function getActiveSoundIds(page) {
  return page.evaluate(() => {
    return (psynet?.media?.sounds || []).map((sound) => sound.stimulusId);
  });
}

async function getStagedAudioRecordingInfo(page) {
  return page.evaluate(() => {
    const blob = psynet?.response?.staged?.blobs?.audioRecording || null;
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

async function waitForAnyAudioPlayback(page, baselineActiveSounds, timeout = 10000) {
  await expect
    .poll(
      () =>
        page.evaluate((baselineCount) => {
          const activeSoundCount = (psynet?.media?.sounds || []).length;
          const domAudioPlaying = Array.from(document.querySelectorAll("audio")).some(
            (audio) =>
              !audio.paused &&
              !audio.ended &&
              Number.isFinite(audio.currentTime) &&
              audio.currentTime > 0
          );
          return activeSoundCount > baselineCount || domAudioPlaying;
        }, baselineActiveSounds),
      { timeout }
    )
    .toBe(true);
}

async function getStagedVideoRecordingInfo(page) {
  return page.evaluate(() => {
    const cameraBlob = psynet?.response?.staged?.blobs?.cameraRecording || null;
    const screenBlob = psynet?.response?.staged?.blobs?.screenRecording || null;
    return {
      cameraExists: !!cameraBlob,
      cameraSize: cameraBlob && typeof cameraBlob.size === "number" ? cameraBlob.size : 0,
      cameraType: cameraBlob && typeof cameraBlob.type === "string" ? cameraBlob.type : null,
      screenExists: !!screenBlob,
      screenSize: screenBlob && typeof screenBlob.size === "number" ? screenBlob.size : 0,
      screenType: screenBlob && typeof screenBlob.type === "string" ? screenBlob.type : null
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

test("video feature demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/features/video");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    const submitTracker = startResponseSubmitTracker(experimentPage);
    try {
      // Section 0: complete deterministic gateway step.
      await completeInitialGateway(experimentPage);

      // Section 1: validate first prompt page renders video.
      await expectVideoPromptReady(experimentPage);
      await expectPromptContains(experimentPage, "Example video prompt");
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // Section 2: verify subsequent prompt pages still render expected video/audio UI.
      await expectPromptContains(experimentPage, "play window");
      await expectVideoPromptReady(experimentPage);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(experimentPage, "video, muted, alongside an audio file");
      await expectVideoPromptReady(experimentPage);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(experimentPage, "well-synchronized");
      await expectVideoPromptReady(experimentPage);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // Section 3: validate audio-recording-on-video page by exercising record controls.
      await expectPromptContains(
        experimentPage,
        "record an audio response",
        PROMPT_TIMEOUT_MS
      );
      const audioRecordButton = experimentPage.locator("#btn-record-record");
      const audioPlayRecordingButton = experimentPage.locator(
        "#btn-record-play-recording"
      );
      await expect(audioRecordButton).toBeVisible();
      await expect(audioRecordButton).toBeEnabled();

      // Let the auto-recording cycle finish before clicking "Record from start".
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 45000
      });
      const audioRecordEventBaseline = await captureTrialEventBaseline(experimentPage);
      await audioRecordButton.click();
      await waitForAudioRecordingReady(experimentPage, 45000);
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 45000,
        baselineIndex: audioRecordEventBaseline
      });
      await expect(audioPlayRecordingButton).toBeEnabled({ timeout: 45000 });
      const audioRecordingBlob = await getStagedAudioRecordingInfo(experimentPage);
      expect(audioRecordingBlob.exists).toBe(true);
      expect(audioRecordingBlob.size).toBeGreaterThan(0);
      if (audioRecordingBlob.type) {
        expect(audioRecordingBlob.type).toContain("audio");
      }
      const activeSoundsBeforeAudioPlayback = (await getActiveSoundIds(experimentPage)).length;
      await audioPlayRecordingButton.click();
      await waitForAnyAudioPlayback(
        experimentPage,
        activeSoundsBeforeAudioPlayback,
        10000
      );
      const audioBaselineResponses = submitTracker.getCount();
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        audioBaselineResponses,
        1,
        STEP_TIMEOUT_MS
      );

      // Section 4: validate delayed video recording page timing and staged camera blob.
      await expectPromptContains(
        experimentPage,
        "record a video response after a countdown",
        PROMPT_TIMEOUT_MS
      );
      const videoRecordButton = experimentPage.locator("#btn-record-record");
      await expect(videoRecordButton).toBeVisible();
      await expect(videoRecordButton).toBeEnabled();
      const singlePlayRecordingButton = experimentPage.locator(
        "#btn-record-play-recording"
      );

      // No auto-recording cycle here (trialPrepare is_triggered_by=None).
      const singleVideoEventBaseline = await captureTrialEventBaseline(experimentPage);
      await videoRecordButton.click();
      await waitForVideoRecordingReady(experimentPage, { timeoutMs: 45000 });
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 45000,
        baselineIndex: singleVideoEventBaseline
      });
      const singleVideoRecording = await getStagedVideoRecordingInfo(experimentPage);
      expect(singleVideoRecording.cameraExists).toBe(true);
      expect(singleVideoRecording.cameraSize).toBeGreaterThan(0);
      if (singleVideoRecording.cameraType) {
        expect(singleVideoRecording.cameraType).toContain("video");
      }
      await expect(singlePlayRecordingButton).toBeEnabled({ timeout: 45000 });
      await singlePlayRecordingButton.click();
      const singleVideoBaselineResponses = submitTracker.getCount();
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        singleVideoBaselineResponses,
        1,
        STEP_TIMEOUT_MS
      );

      // Section 5: validate dual-source recording stores both camera and screen blobs.
      await expectMainBodyContains(
        experimentPage,
        "simultaneous screen recording",
        PROMPT_TIMEOUT_MS
      );
      const dualRecordButton = experimentPage.locator("#btn-record-record");
      await expect(dualRecordButton).toBeVisible();
      await expect(dualRecordButton).toBeEnabled();
      const dualPlayRecordingButton = experimentPage.locator(
        "#btn-record-play-recording"
      );

      // Let the auto-recording cycle finish before clicking "Record from start".
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 60000
      });
      const dualVideoEventBaseline = await captureTrialEventBaseline(experimentPage);
      await dualRecordButton.click();
      await waitForVideoRecordingReady(experimentPage, {
        timeoutMs: 60000,
        requireScreen: true
      });
      await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
        timeoutMs: 60000,
        baselineIndex: dualVideoEventBaseline
      });
      const dualRecording = await getStagedVideoRecordingInfo(experimentPage);
      expect(dualRecording.cameraExists).toBe(true);
      expect(dualRecording.cameraSize).toBeGreaterThan(0);
      expect(dualRecording.screenExists).toBe(true);
      expect(dualRecording.screenSize).toBeGreaterThan(0);
      await expect(dualPlayRecordingButton).toBeEnabled({ timeout: 45000 });
      await dualPlayRecordingButton.click();
      const dualVideoBaselineResponses = submitTracker.getCount();
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        dualVideoBaselineResponses,
        1,
        STEP_TIMEOUT_MS
      );

      // Section 6: ensure playback page appears and finish remaining timeline safely.
      await waitForMainBodyContains(
        experimentPage,
        "camera recording",
        STEP_TIMEOUT_MS
      );
      await expectVideoPromptReady(experimentPage, STEP_TIMEOUT_MS);
      await advanceUntilFinish(experimentPage);
    } finally {
      submitTracker.stop();
    }
  });
});

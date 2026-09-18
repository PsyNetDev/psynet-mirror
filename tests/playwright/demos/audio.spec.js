const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertExpectedTimelinePathActive,
  clickConsentButton,
  clickFinish,
  clickNextAndWait,
  completeInitialGateway,
  captureTrialEventBaseline,
  startResponseSubmitTracker,
  waitForResponseSubmitIncrement,
  waitForAudioRecordingReady,
  waitForNextEnabled,
  waitForTimelinePageReady,
  waitForTrialEvents,
  withExperiment
} = require("../psynetHarness");

const PROMPT_TIMEOUT_MS = 90000;
const STEP_TIMEOUT_MS = 120000;
const SNAPSHOT_OPTIONS = {
  animations: "disabled",
  caret: "hide",
  maxDiffPixelRatio: 0.02
};

/*
Step summary:
1. Intro / consent startup:
   participant clears the generic gateway page, accepts consent pages, and enters the demo timeline.
2. JS synth intro pages:
   participant hears synthesized sounds, uses play/stop/loop controls, and visits instrument/timbre variants.
3. Slider-controlled melody page:
   participant changes a slider to manipulate notes, then continues.
4. Audio prompt variants:
   participant experiences auto-play, looping, standard controls, and custom "Play again" control behavior.
5. Scripted audio sequence page:
   participant waits for a sequence that enables continuation after playback logic completes.
6. Play-window + meter pages:
   participant uses play-window controls and sees audio meter interfaces.
7. Audio recording page:
   participant records audio, plays it back, and submits.
8. Playback + delayed recording pages:
   participant listens back, then records again on a delayed-record page and submits.
9. Audio + video recording page:
   participant triggers a page that records video after audio prompt timing and sees recorded playback.
10. Meter calibration pages:
    participant sees default and tapping-specialized meter configurations.
11. Preloading page:
    participant can play/stop multiple preloaded audio assets.
12. Finish page:
    participant clicks Finish and exits via recruiter redirect.

Intentionally not covered:
- Pixel-perfect animation trajectories and frame-by-frame rendering.
- Exact audio waveform content or recording semantic quality.
*/

async function expectPromptContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#prompt-text")).toContainText(text, {
    timeout
  });
}

async function expectMainBodyContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#main-body")).toContainText(text, {
    timeout
  });
}

async function expectLocatorScreenshot(locator, snapshotName, options = SNAPSHOT_OPTIONS) {
  await expect(locator).toHaveScreenshot(snapshotName, options);
}

async function clickConsentAndWait(page, timeout = STEP_TIMEOUT_MS) {
  await clickConsentButton(page, timeout);
  await waitForTimelinePageReady(page, timeout);
}

async function reachInitialAudioPrompt(page, timeout = STEP_TIMEOUT_MS) {
  // Explicit deterministic startup sequence for audio demo:
  // 1) gateway page, 2) main consent, 3) audiovisual consent, 4) first prompt page.
  await completeInitialGateway(page, timeout);

  await expectMainBodyContains(page, "We need your consent to proceed", timeout);
  await clickConsentAndWait(page, timeout);

  // Match text unique to AudiovisualConsent ("In this experiment, ...")
  // to avoid false-matching the similar phrase on MainConsent.
  await expectMainBodyContains(
    page,
    "In this experiment, you may be asked to make a voice or video recording",
    timeout
  );
  await clickConsentAndWait(page, timeout);

  await expectPromptContains(page, "harmonic complex tone as the timbre", timeout);
}

async function getActiveSoundIds(page) {
  return page.evaluate(() => {
    return (psynet?.media?.sounds || []).map((sound) => sound.stimulusId);
  });
}

async function getStagedBlobInfo(page) {
  return page.evaluate(() => {
    const staged = psynet?.response?.staged?.blobs || {};
    const audioBlob = staged.audioRecording || null;
    const cameraBlob = staged.cameraRecording || null;
    return {
      audioExists: !!audioBlob,
      audioSize:
        audioBlob && typeof audioBlob.size === "number" ? audioBlob.size : 0,
      audioType:
        audioBlob && typeof audioBlob.type === "string" ? audioBlob.type : null,
      cameraExists: !!cameraBlob,
      cameraSize:
        cameraBlob && typeof cameraBlob.size === "number" ? cameraBlob.size : 0,
      cameraType:
        cameraBlob && typeof cameraBlob.type === "string" ? cameraBlob.type : null
    };
  });
}

async function waitForRecordingPlaybackReady(page, timeout = 45000) {
  await expect
    .poll(
      () =>
        page
          .evaluate(() => {
            const blob = psynet?.response?.staged?.blobs?.audioRecording || null;
            const recording = psynet?.audio?.recording || null;
            return {
              audioBlobExists: !!blob,
              audioBlobSize:
                blob && typeof blob.size === "number" ? blob.size : 0,
              recordingLoaded: !!recording?.loaded,
              playFn: typeof recording?.play === "function"
            };
          })
          .catch(() => ({
            audioBlobExists: false,
            audioBlobSize: 0,
            recordingLoaded: false,
            playFn: false
          })),
      { timeout }
    )
    .toMatchObject({
      audioBlobExists: true,
      recordingLoaded: true,
      playFn: true
    });
}

async function waitForSoundActiveState(
  page,
  stimulusId,
  expectedActive,
  timeout = PROMPT_TIMEOUT_MS
) {
  await expect
    .poll(
      async () => {
        const activeSoundIds = await getActiveSoundIds(page);
        return activeSoundIds.includes(stimulusId);
      },
      { timeout }
    )
    .toBe(expectedActive);
}

async function useStandardAudioControls(page, options = {}) {
  const stopAfterPlay = options.stopAfterPlay ?? true;
  const toggleLoop = options.toggleLoop ?? false;
  const playButton = page.locator("#audio-prompt-play");
  const stopButton = page.locator("#audio-prompt-stop");
  const loopToggle = page.locator("#audio-prompt-loop-input");
  await expect(playButton).toBeVisible();
  await expect(stopButton).toBeVisible();
  await expect(loopToggle).toBeVisible();
  await expect(playButton).toBeEnabled();

  await playButton.click();
  if (stopAfterPlay) {
    await stopButton.click();
  }

  if (toggleLoop) {
    const wasChecked = await loopToggle.isChecked();
    await loopToggle.click();
    if (wasChecked) {
      await expect(loopToggle).not.toBeChecked();
    } else {
      await expect(loopToggle).toBeChecked();
    }
  }
}

async function waitForSliderInteractionReady(page, timeoutMs = STEP_TIMEOUT_MS) {
  await waitForTrialEvents(page, ["responseEnable"], {
    timeoutMs
  });
  await expect(page.locator("#sliderpage_slider")).toBeEnabled({ timeout: timeoutMs });
}

async function completeRecordedPlaybackCheckpoint(
  page,
  checkpointEventBaseline = 0
) {
  await expectMainBodyContains(page, "Here's the recording you just made.");
  await waitForTrialEvents(page, ["promptStart", "promptEnd", "trialFinish"], {
    timeoutMs: STEP_TIMEOUT_MS,
    baselineIndex: checkpointEventBaseline
  });
  await expect(page.locator("#next-button")).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
  await expect(page.locator("#btn-record-record")).toHaveCount(0);
  await expect(page.locator("#btn-record-play-recording")).toHaveCount(0);
  await waitForNextEnabled(page, STEP_TIMEOUT_MS);
  await clickNextAndWait(page, STEP_TIMEOUT_MS);
}

test("audio demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/experiments/audio");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    const submitTracker = startResponseSubmitTracker(experimentPage);
    try {
      // Section 1: complete deterministic startup sequence (gateway + two consents).
      await reachInitialAudioPrompt(
        experimentPage,
        STEP_TIMEOUT_MS
      );

      await assertExpectedTimelinePathActive(experimentPage);

      // Section 2: validate default JS synth controls (play + loop toggle).
      await expectPromptContains(
        experimentPage,
        "harmonic complex tone as the timbre"
      );
      await useStandardAudioControls(experimentPage, {
        stopAfterPlay: false,
        toggleLoop: true
      });
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 3: validate an instrument page without explicit controls still progresses correctly.
    await expectPromptContains(experimentPage, "select various instrument sounds");
    await expect(experimentPage.locator("#audio-prompt-play")).toHaveCount(0);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 4: validate slider interaction updates UI value and corresponding timeline events.
    await expectPromptContains(
      experimentPage,
      "manipulate individual notes with a slider"
    );
    const slider = experimentPage.locator("#sliderpage_slider");
    await waitForSliderInteractionReady(experimentPage);
    await expect(slider).toBeVisible();
    const sliderValueBefore = Number(await slider.inputValue());
    await slider.focus();
    await experimentPage.keyboard.press("ArrowRight");
    await expect
      .poll(async () => Number(await slider.inputValue()), { timeout: 5000 })
      .not.toBe(sliderValueBefore);
    await waitForNextEnabled(experimentPage, 30000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 5: smoke-check additional timbre pages load and remain navigable.
    await expectPromptContains(experimentPage, "Shepard tones");
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await expectPromptContains(experimentPage, "custom sampler");
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 6: validate auto-play prompt without controls reaches completion via event timing.
    await expectPromptContains(
      experimentPage,
      "simple audio page with one stimulus"
    );
    await expect(experimentPage.locator("#audio-prompt-controls")).toHaveCount(0);
    await waitForNextEnabled(experimentPage, 45000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 7: validate looping prompt emits multiple completion events before submission.
    await expectPromptContains(experimentPage, "loops the same stimulus");
    await waitForNextEnabled(experimentPage, 45000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 8: validate manual-start controls gate trial start and unlock submission.
    await expectPromptContains(experimentPage, "adds audio playback controls");
    await expect(experimentPage.locator("#next-button")).toBeDisabled();
    await expectLocatorScreenshot(
      experimentPage.locator("#audio-prompt-controls"),
      "audio-controls-standard.png"
    );
    await useStandardAudioControls(experimentPage, { stopAfterPlay: false });
    await waitForNextEnabled(experimentPage, 45000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 9: validate customized control surface and explicit replay behavior.
    await expectPromptContains(experimentPage, "customizes the audio controls");
    await expect(experimentPage.locator("#audio-prompt-play")).toContainText(
      "Play again"
    );
    await expect(experimentPage.locator("#audio-prompt-stop")).toHaveCount(0);
    await expect(experimentPage.locator("#audio-prompt-loop-input")).toHaveCount(
      0
    );
    await expectLocatorScreenshot(
      experimentPage.locator("#audio-prompt-controls"),
      "audio-controls-play-again-only.png"
    );
    await experimentPage.locator("#audio-prompt-play").click();
    await waitForNextEnabled(experimentPage, 45000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 10: validate scripted multi-stimulus playback sequence and enable-order events.
    await expectPromptContains(
      experimentPage,
      "access audio stimuli outside of Audio Prompts"
    );
    await expect(experimentPage.locator("#audio-prompt-controls")).toHaveCount(0);
    await waitForNextEnabled(experimentPage, 60000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 11: validate play-window prompt is interactive via standard audio controls.
    await expectPromptContains(experimentPage, "play window");
    await useStandardAudioControls(experimentPage, { stopAfterPlay: false });
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 12: validate audio meter page renders the meter UI.
    await expectPromptContains(experimentPage, "shows an audio meter");
    await expect(experimentPage.locator("#audio-meter")).toBeVisible();
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 13: validate audio recording, stored blob metadata, and playback button behavior.
    await expectPromptContains(experimentPage, "lets you record audio");
    const firstRecordButton = experimentPage.locator("#btn-record-record");
    await expect(firstRecordButton).toBeVisible();
    await expect(firstRecordButton).toBeEnabled();
    const firstRecordBaselineResponses = submitTracker.getCount();
    const firstRecordEventBaseline = await captureTrialEventBaseline(experimentPage);
    await firstRecordButton.click();
    await waitForAudioRecordingReady(experimentPage, 45000);
    await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
      timeoutMs: 45000,
      baselineIndex: firstRecordEventBaseline
    });
    await waitForRecordingPlaybackReady(experimentPage, 45000);
    const firstPlayRecordingButton = experimentPage.locator(
      "#btn-record-play-recording"
    );
    const firstBlobInfo = await getStagedBlobInfo(experimentPage);
    expect(firstBlobInfo.audioExists).toBe(true);
    expect(firstBlobInfo.audioSize).toBeGreaterThan(0);
    if (firstBlobInfo.audioType) {
      expect(firstBlobInfo.audioType).toContain("audio");
    }
    if (await firstPlayRecordingButton.isEnabled().catch(() => false)) {
      await firstPlayRecordingButton.click();
    } else {
      await experimentPage.evaluate(() => psynet.page.control.playRecording());
    }
    await waitForSoundActiveState(experimentPage, "recording", true, 10000);
    const firstCheckpointEventBaseline = await captureTrialEventBaseline(
      experimentPage
    );
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForResponseSubmitIncrement(
      submitTracker,
      firstRecordBaselineResponses,
      1,
      STEP_TIMEOUT_MS
    );

    // Section 14: validate playback checkpoint page and continue deterministically.
    await completeRecordedPlaybackCheckpoint(
      experimentPage,
      firstCheckpointEventBaseline
    );

    // Section 15: validate delayed-record flow captions, timing, and playback availability.
    await expectPromptContains(experimentPage, "activate the recorder 3 seconds afterwards");
    const delayedRecordBaselineResponses = submitTracker.getCount();
    const delayedRecordEventBaseline = await captureTrialEventBaseline(experimentPage);
    await waitForAudioRecordingReady(experimentPage, 45000);
    await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
      timeoutMs: 45000,
      baselineIndex: delayedRecordEventBaseline
    });
    await waitForRecordingPlaybackReady(experimentPage, 45000);
    const delayedRecordButton = experimentPage.locator("#btn-record-record");
    const delayedPlayRecordingButton = experimentPage.locator(
      "#btn-record-play-recording"
    );
    await expect(delayedRecordButton).toBeEnabled();
    const delayedBlobInfo = await getStagedBlobInfo(experimentPage);
    expect(delayedBlobInfo.audioExists).toBe(true);
    expect(delayedBlobInfo.audioSize).toBeGreaterThan(0);
    if (delayedBlobInfo.audioType) {
      expect(delayedBlobInfo.audioType).toContain("audio");
    }
    if (await delayedPlayRecordingButton.isEnabled().catch(() => false)) {
      await delayedPlayRecordingButton.click();
    } else {
      await experimentPage.evaluate(() => psynet.page.control.playRecording());
    }
    await waitForSoundActiveState(experimentPage, "recording", true, 10000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForResponseSubmitIncrement(
      submitTracker,
      delayedRecordBaselineResponses,
      1,
      STEP_TIMEOUT_MS
    );

    // Section 16: validate combined audio+video recording timing and resulting playback prompt.
    await expectPromptContains(
      experimentPage,
      "plays audio and records video after a couple of seconds"
    );
    const videoRecordButton = experimentPage.locator("#btn-record-record");
    await expect(videoRecordButton).toBeVisible();
    await expect(videoRecordButton).toBeEnabled();
    const secondCheckpointEventBaseline = await captureTrialEventBaseline(
      experimentPage
    );
    await videoRecordButton.click();
    await expectMainBodyContains(
      experimentPage,
      "Here's the recording you just made.",
      STEP_TIMEOUT_MS
    );
    await completeRecordedPlaybackCheckpoint(
      experimentPage,
      secondCheckpointEventBaseline
    );

    // Section 17: validate calibrated meter variants expose expected slider controls.
    await expectPromptContains(
      experimentPage,
      "default meter parameters are designed to work well for music playback"
    );
    await expect(experimentPage.locator("#audio-meter")).toBeVisible();
    const audioMeterCalibrationSliderCount = await experimentPage
      .locator("#audio-meter-sliders .slider-range")
      .count();
    expect(audioMeterCalibrationSliderCount).toBeGreaterThanOrEqual(9);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await expectPromptContains(experimentPage, "TappingAudioMeterControl class");
    await expect(experimentPage.locator("#audio-meter")).toBeVisible();
    const tappingCalibrationSliderCount = await experimentPage
      .locator("#audio-meter-sliders .slider-range")
      .count();
    expect(tappingCalibrationSliderCount).toBeGreaterThanOrEqual(9);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 18: validate preloading controls are enabled and actually start/stop each asset.
    await expectMainBodyContains(experimentPage, "demonstrates audio preloading");
    const playBierButton = experimentPage.getByRole("button", {
      name: "Play 'bier'."
    });
    const stopBierButton = experimentPage.getByRole("button", {
      name: "Stop 'bier'."
    });
    await expect(playBierButton).toBeEnabled();
    await expect(stopBierButton).toBeEnabled();
    const preloadingButtons = experimentPage.locator(".wait-for-media-load");
    const preloadingButtonCount = await preloadingButtons.count();
    expect(preloadingButtonCount).toBeGreaterThan(0);
    for (let i = 0; i < preloadingButtonCount; i += 1) {
      await expect(preloadingButtons.nth(i)).toBeEnabled();
    }
    await expectLocatorScreenshot(
      experimentPage.locator("#audio-preloading-controls"),
      "audio-preloading-controls.png"
    );
    const preloadingStimuli = [
      { label: "bier", id: "bier" },
      { label: "funk_game_loop", id: "funk_game_loop" },
      { label: "honey_bee", id: "honey_bee" },
      { label: "there_it_is", id: "there_it_is" }
    ];
    for (const stimulus of preloadingStimuli) {
      const playButton = experimentPage.getByRole("button", {
        name: `Play '${stimulus.label}'.`
      });
      const stopButton = experimentPage.getByRole("button", {
        name: `Stop '${stimulus.label}'.`
      });
      await expect(playButton).toBeEnabled();
      await expect(stopButton).toBeEnabled();
      await playButton.click();
      await waitForSoundActiveState(experimentPage, stimulus.id, true, 10000);
      await stopButton.click();
      await waitForSoundActiveState(experimentPage, stimulus.id, false, 15000);
    }

    // Section 19: validate final finish action lands on recruiter exit.
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    const finishButton = experimentPage.locator("#Finish");
    await expect(finishButton).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await clickFinish(experimentPage, STEP_TIMEOUT_MS);
    } finally {
      submitTracker.stop();
    }
  });
});

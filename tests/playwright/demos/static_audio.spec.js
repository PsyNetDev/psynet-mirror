const path = require("path");
const { test, expect } = require("../fixtures");

const {
  advanceUntilFinish,
  captureTrialEventBaseline,
  clickNextAndWait,
  completeInitialGateway,
  startResponseSubmitTracker,
  waitForResponseSubmitIncrement,
  waitForTrialEvents,
  withExperiment
} = require("../psynetHarness");

const PROMPT_TIMEOUT_MS = 90000;
const STEP_TIMEOUT_MS = 120000;

/*
Step summary:
1. Intro gateway:
   participant clears the shared entry page and enters the static audio timeline.
2. Calibration/setup pages:
   participant listens to the setup sound, enables microphone flow, and sees the audio meter.
3. Task instructions:
   participant reads the imitation instructions before the trial loop starts.
4. First recording trial:
   participant clicks Start, records speech, and reaches the feedback step.
5. Feedback and submission:
   participant replays the trial feedback, continues, and submits one response.
6. Remaining trials and finish:
   participant progresses through the rest of the static trials to completion.

Intentionally not covered:
- Every single static-trial node variant (this spec validates the representative flow).
- Acoustic quality/content analysis of recorded audio.
*/

async function expectMainBodyContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#main-body")).toContainText(text, { timeout });
}

async function expectPromptContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#prompt-text")).toContainText(text, { timeout });
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

async function assertFeedbackPlayback(page) {
  await expectPromptContains(
    page,
    "Listen back to your recording. Did you do a good job?",
    STEP_TIMEOUT_MS
  );
  const promptEndBaseline = await page.evaluate(() =>
    (psynet?.trial?.eventLog || []).filter(
      (event) => event.eventType === "promptEnd"
    ).length
  );
  await page.evaluate(() => psynet.trial.restart({ from: "promptStart" }));
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          (psynet?.trial?.eventLog || []).filter(
            (event) => event.eventType === "promptEnd"
          ).length
        ),
      { timeout: 20000 }
    )
    .toBeGreaterThan(promptEndBaseline);
}

test("static_audio demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/experiments/static_audio");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    const submitTracker = startResponseSubmitTracker(experimentPage);
    try {
      // Section 0: gateway page.
      await completeInitialGateway(experimentPage);

      // Section 1: calibration pages and meter visibility.
      await expectMainBodyContains(experimentPage, "Please listen to the following sound");
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await expectMainBodyContains(experimentPage, "Please speak into your microphone");
      await expect(experimentPage.locator("#audio-meter")).toBeVisible({
        timeout: PROMPT_TIMEOUT_MS
      });
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // Section 2: info page before static-trial loop.
      await expectMainBodyContains(experimentPage, "repeat");
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // Section 3: first static trial recording flow.
      await expectPromptContains(experimentPage, "Please imitate the spoken word");
      const startButton = experimentPage.locator("#buttonStart");
      await expect(startButton).toBeVisible();
      await expect(startButton).toBeEnabled();
      const firstTrialBaselineResponses = submitTracker.getCount();
      const firstTrialEventBaseline = await captureTrialEventBaseline(experimentPage);
      await startButton.click();

      await expectPromptContains(
        experimentPage,
        "Listen back to your recording. Did you do a good job?",
        STEP_TIMEOUT_MS
      );
      await waitForTrialEvents(experimentPage, [
        "promptStart",
        "audioFinished: prompt",
        "promptEnd",
        "trialFinish"
      ], {
        timeoutMs: 45000,
        baselineIndex: firstTrialEventBaseline
      });
      const stagedAudio = await getStagedAudioRecordingInfo(experimentPage);
      if (stagedAudio.exists) {
        expect(stagedAudio.size).toBeGreaterThan(0);
      }
      if (stagedAudio.exists && stagedAudio.type) {
        expect(stagedAudio.type).toContain("audio");
      }

      // Section 4: feedback replay + submit continuation.
      await expect(experimentPage.locator("#btn-record-record")).toHaveCount(0);
      await assertFeedbackPlayback(experimentPage);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        firstTrialBaselineResponses,
        1,
        STEP_TIMEOUT_MS
      );

      // Section 5: complete remaining trials.
      await advanceUntilFinish(experimentPage);
    } finally {
      submitTracker.stop();
    }
  });
});

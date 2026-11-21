const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const SOUNDS = ["clarinet", "flute", "guitar", "piano", "trumpet", "violin"];

/*
Step summary:
1. Intro: participant clears the gateway and reads the instructions.
2. Trials: participant rates each of the six sounds after it plays. Each trial
   page lists the next trials' sounds, which download while the current one
   plays, so every sound is downloaded once and later trials don't fetch it.
3. Finish: participant reaches the thank-you page.
*/

test("the next sounds download while the participant rates this one", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const dir = path.resolve("demos/experiments/simple_audio_rating");

  await withExperiment(page, context, dir, async (participant) => {
    const downloads = [];
    participant.on("request", (request) => {
      const match = request.url().match(/instrument_sounds\/(\w+)\.mp3/);
      if (match) {
        downloads.push(match[1]);
      }
    });

    await completeInitialGateway(participant);
    await clickNextAndWait(participant, STEP_TIMEOUT_MS);

    for (let trial = 0; trial < SOUNDS.length; trial++) {
      const questions = participant.locator(".sd-question");
      await expect(questions).toHaveCount(2, { timeout: STEP_TIMEOUT_MS });
      if (trial > 0) {
        // This trial's sound came from the copy downloaded on an earlier page.
        expect(downloads.length).toBeGreaterThan(trial);
      }
      for (const index of [0, 1]) {
        await questions.nth(index).locator(".sd-rating__item").nth(2).click();
      }
      await clickNextAndWait(participant, STEP_TIMEOUT_MS);
    }

    await waitForMainBodyContains(participant, "Thank you", STEP_TIMEOUT_MS);
    expect([...downloads].sort()).toEqual(SOUNDS);
    await assertNoBackendError(participant);
  });
});

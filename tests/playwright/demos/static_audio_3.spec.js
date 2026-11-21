const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  postedResponse,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const N_TRIALS = 9;

/*
Step summary:
1. Intro: participant clears the gateway and reads the instructions.
2. Trials: participant rates each of the nine sounds with the push buttons.
   The trial maker prepares trials in advance, so pressing a button shows the
   next sound on the same page: the page is never replaced, each sound is
   downloaded once, finished sounds are freed, and every answer reaches /response in order with the
   sound's start and the button click in its event log.
3. Finish: participant reaches the thank-you page.
*/

test("push buttons show the next sound on the same page", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const dir = path.resolve("demos/experiments/static_audio_3");

  await withExperiment(page, context, dir, async (participant) => {
    const downloads = [];
    const answers = [];
    participant.on("request", (request) => {
      if (request.url().includes("/asset/")) {
        downloads.push(request.url());
      }
      if (request.method() === "POST" && request.url().includes("/response")) {
        const body = postedResponse(request);
        if (/^[1-5]$/.test(body.raw_answer)) {
          answers.push(body);
        }
      }
    });

    await completeInitialGateway(participant);
    await clickNextAndWait(participant, STEP_TIMEOUT_MS);

    const chosen = [];
    for (let trial = 0; trial < N_TRIALS; trial++) {
      await expect(participant.locator("#prompt-text")).toContainText(
        "How much did you like the sound?",
        { timeout: STEP_TIMEOUT_MS }
      );
      const button = participant.locator(".push-button").nth(trial % 5);
      await expect(button).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
      if (trial === 0) {
        await participant.locator("#main-body").evaluate((element) => {
          element.dataset.firstTrial = "true";
        });
      } else {
        // A page loaded from the server would have replaced #main-body.
        await expect(participant.locator("#main-body")).toHaveAttribute(
          "data-first-trial",
          "true"
        );
      }
      if (trial === N_TRIALS - 1) {
        // Only the page's own sound and the last one are still decoded.
        const decoded = await participant.evaluate(() => Object.keys(psynet.audio));
        expect(decoded.length).toBeLessThanOrEqual(2);
      }
      chosen.push(String(1 + (trial % 5)));
      await button.click();
    }

    await waitForMainBodyContains(participant, "Thank you", STEP_TIMEOUT_MS);
    expect(answers.map((body) => body.raw_answer)).toEqual(chosen);
    for (const body of answers) {
      const events = body.metadata.event_log.map((event) => event.eventType);
      expect(events.filter((type) => type === "promptStart")).toHaveLength(1);
      expect(events.filter((type) => type === "pushButtonClicked")).toHaveLength(1);
    }
    expect(new Set(downloads).size).toBe(downloads.length);
    await assertNoBackendError(participant);
  });
});

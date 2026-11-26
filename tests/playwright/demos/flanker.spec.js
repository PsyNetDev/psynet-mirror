const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const N_TRIALS = 16;

/*
Step summary:
1. Intro: participant clears the gateway and reads the instructions.
2. First half: participant answers each row of arrows with F or J. While the
   server's replies are held back, the next trials still appear.
3. Break: participant continues past the halfway break.
4. Second half and summary: participant answers the rest and sees accuracy
   and reaction times. Each trial's time_taken is its reaction time, so it is
   at least the time the participant waited before pressing.
*/

async function answerNextTrial(participant, { waitMs = 0 } = {}) {
  const stimulus = participant.locator("#flanker-stimulus");
  await expect(stimulus).toHaveText(/^[←→]{5}$/, { timeout: STEP_TIMEOUT_MS });
  const arrows = await stimulus.textContent();
  if (waitMs) {
    await participant.waitForTimeout(waitMs);
  }
  await participant.keyboard.press(arrows[2] === "←" ? "f" : "j");
  await expect(stimulus).not.toHaveText(arrows, { timeout: STEP_TIMEOUT_MS });
}

test("flanker trials follow each other without waiting for the server", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const dir = path.resolve("demos/experiments/flanker");

  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    await participant.getByRole("button", { name: "Next", exact: true }).click();

    let release;
    const held = new Promise((resolve) => (release = resolve));
    const reactionTimes = [];
    await participant.route("**/response", async (route) => {
      const json = route.request().postData().match(/name="json"\r\n\r\n(.*)\r\n/);
      reactionTimes.push(JSON.parse(json[1]).metadata.time_taken);
      await held;
      await route.continue();
    });

    await answerNextTrial(participant, { waitMs: 300 });
    await answerNextTrial(participant);
    await answerNextTrial(participant);
    expect(reactionTimes).toHaveLength(1);
    expect(reactionTimes[0]).toBeGreaterThanOrEqual(0.3);
    release();
    for (let trial = 3; trial < N_TRIALS / 2; trial++) {
      await answerNextTrial(participant);
    }

    await waitForMainBodyContains(participant, "Take a short break", STEP_TIMEOUT_MS);
    await participant.getByRole("button", { name: "Next", exact: true }).click();
    for (let trial = 0; trial < N_TRIALS / 2; trial++) {
      await answerNextTrial(participant);
    }

    await waitForMainBodyContains(participant, "You answered 100% of the trials correctly.", STEP_TIMEOUT_MS);
    await expect(participant.locator("#summary")).toContainText("Mean reaction time");
    await assertNoBackendError(participant);
  });
});

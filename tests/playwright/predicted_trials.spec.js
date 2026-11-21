const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

// hold() delays /response requests until release() is called.
async function responseGate(page) {
  const gate = { held: null, release: null, posted: 0 };
  gate.hold = () => {
    gate.posted = 0;
    gate.held = new Promise((resolve) => (gate.release = resolve));
  };
  await page.route("**/response", async (route) => {
    gate.posted += 1;
    await gate.held;
    await route.continue();
  });
  return gate;
}

test("prepared trials advance while the server's replies are held back", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve("tests/playwright/experiments/predicted_trials");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    const word = experimentPage.locator("#word");
    const answer = experimentPage.locator("#answer-button");
    await expect(word).toHaveText("apple", { timeout: STEP_TIMEOUT_MS });
    const gate = await responseGate(experimentPage);

    // Answers go one at a time; the break before the fourth trial stops the
    // prediction after "cloud".
    gate.hold();
    await answer.click();
    await expect(word).toHaveText("brick");
    await answer.click();
    await expect(word).toHaveText("cloud");
    await answer.click();
    expect(gate.posted).toBe(1);
    gate.release();
    await waitForMainBodyContains(experimentPage, "Take a break.", STEP_TIMEOUT_MS);
    await experimentPage.locator("#next-button").click();

    // A rejected answer brings its trial back and drops the later answers.
    await expect(word).toHaveText("drum", { timeout: STEP_TIMEOUT_MS });
    gate.hold();
    await experimentPage.locator("#reject-button").click();
    await expect(word).toHaveText("eagle");
    await answer.click();
    await expect(word).toHaveText("flute");
    gate.release();
    await expect(experimentPage.locator("#alert-message")).toHaveText("Rejected.", {
      timeout: STEP_TIMEOUT_MS
    });
    await experimentPage.locator("#alert-button").click();
    await expect(word).toHaveText("drum");

    for (const next of ["eagle", "flute"]) {
      await answer.click();
      await expect(word).toHaveText(next);
    }
    await answer.click();
    await waitForMainBodyContains(
      experimentPage,
      "Answers: apple,brick,cloud,drum,eagle,flute",
      STEP_TIMEOUT_MS
    );
    await assertNoBackendError(experimentPage);
  });
});

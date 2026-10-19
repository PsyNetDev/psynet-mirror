const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertExpectedTimelinePathActive,
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("jsPsych uses clean documents on entry and exit", { tag: "@both" }, async ({
  page,
  context
}) => {
  await context.addInitScript(() => {
    window.__documentToken = `${Date.now()}-${Math.random()}`;
  });

  await withExperiment(
    page,
    context,
    path.resolve("demos/experiments/jspsych"),
    async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await assertExpectedTimelinePathActive(experimentPage, 20000);
      await expect(experimentPage.locator("#main-body")).toContainText(
        "quick jsPsych task begins",
        { timeout: STEP_TIMEOUT_MS }
      );
      const introToken = await experimentPage.evaluate(
        () => window.__documentToken
      );
      let navigations = 0;
      experimentPage.on("framenavigated", (frame) => {
        if (frame === experimentPage.mainFrame()) {
          navigations += 1;
        }
      });

      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await expect(experimentPage.locator("#main-body")).toContainText(
        "quick jsPsych task completed",
        { timeout: STEP_TIMEOUT_MS }
      );
      const checkpointToken = await experimentPage.evaluate(
        () => window.__documentToken
      );
      expect(checkpointToken).not.toBe(introToken);
      expect(navigations).toBeGreaterThanOrEqual(2);

      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await expect(experimentPage.locator("#js-psych")).toContainText(
        "Welcome to the experiment",
        { timeout: STEP_TIMEOUT_MS }
      );
      const mainTaskToken = await experimentPage.evaluate(
        () => window.__documentToken
      );
      expect(mainTaskToken).not.toBe(checkpointToken);
      await assertNoBackendError(experimentPage);
    }
  );
});

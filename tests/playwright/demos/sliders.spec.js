const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertExpectedTimelinePathActive,
  assertNoBackendError,
  completeInitialGateway,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("slider page module activates", { tag: "@both" }, async ({ page, context }) => {
  await withExperiment(
    page,
    context,
    path.resolve("demos/features/slider"),
    async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await assertExpectedTimelinePathActive(experimentPage, 20000);
      await expect(experimentPage.locator("input.slider-range")).toBeVisible({
        timeout: STEP_TIMEOUT_MS
      });
      await expect(
        experimentPage.locator("#slider-output-value")
      ).not.toHaveText("NA", { timeout: STEP_TIMEOUT_MS });
      await assertNoBackendError(experimentPage);
    }
  );
});

const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertExpectedTimelinePathActive,
  clickNextAndWait,
  completeInitialGateway,
  isInplaceTimelineModeEnabled,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("managed page JavaScript works in both transition modes", { tag: "@both" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/deferred_page_scripts"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertExpectedTimelinePathActive(experimentPage, 20000);

    const marker = experimentPage.locator("#managed-javascript-marker");
    await expect(marker).toHaveAttribute("data-first-active", "true");
    await expect(marker).toHaveAttribute("data-second-active", "true");
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => window.__psynetManagedJavascript || null),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        dependencyLoads: 1,
        events: ["activate:first", "activate:second"]
      });
    expect(
      await experimentPage.evaluate(
        () =>
          window.__psynetManagedJavascript.pageUuids.at(-1) === window.pageUuid
      )
    ).toBe(true);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await expect(marker).toContainText("Managed JavaScript activated");
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => window.__psynetManagedJavascript || null),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        dependencyLoads: 1,
        events: isInplaceTimelineModeEnabled()
          ? [
              "activate:first",
              "activate:second",
              "cleanup:second",
              "cleanup:first",
              "activate:first",
              "activate:second"
            ]
          : ["activate:first", "activate:second"]
      });
    expect(
      await experimentPage.evaluate(
        () =>
          window.__psynetManagedJavascript.pageUuids.at(-1) === window.pageUuid
      )
    ).toBe(true);
  });
});

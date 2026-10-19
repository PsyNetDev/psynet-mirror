const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

const CASES = [
  {
    name: "js_page_modules",
    dir: "tests/playwright/experiments/broken_page_module"
  },
  {
    name: "js_dependencies",
    dir: "tests/playwright/experiments/broken_page_dependency"
  }
];

for (const { name, dir } of CASES) {
  test(`full-page ${name} failures show a refresh prompt`, { tag: "@both" }, async ({
    page,
    context
  }) => {
    const absDir = path.resolve(dir);

    await withExperiment(page, context, absDir, async (experimentPage) => {
      await completeInitialGateway(experimentPage);

      await expect(experimentPage.locator("#alert-message")).toContainText(
        "This page could not be loaded. Please refresh the page and try again.",
        { timeout: STEP_TIMEOUT_MS }
      );
      await expect
        .poll(
          () =>
            experimentPage.evaluate(() => ({
              pageReady: window.psynet?.pageReady === true,
              nextDisabled: document
                .getElementById("next-button")
                ?.hasAttribute("disabled")
            })),
          { timeout: 10000 }
        )
        .toEqual({
          pageReady: false,
          nextDisabled: true
        });

      await experimentPage.locator("#alert-button").click();
      await assertNoBackendError(experimentPage);
    });
  });
}

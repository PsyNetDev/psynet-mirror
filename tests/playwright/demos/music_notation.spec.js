const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertExpectedTimelinePathActive,
  assertNoBackendError,
  completeInitialGateway,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("music notation loads package-owned resources", { tag: "@both" }, async ({ page, context }) => {
  await withExperiment(
    page,
    context,
    path.resolve("demos/features/music_notation"),
    async (experimentPage) => {
      const packagePaths = [];
      experimentPage.on("request", (request) => {
        const pathname = new URL(request.url()).pathname;
        if (pathname.startsWith("/static/packages/psynet/")) {
          packagePaths.push(pathname);
        }
      });
      await completeInitialGateway(experimentPage);
      await assertExpectedTimelinePathActive(experimentPage, 20000);
      await expect(experimentPage.locator("#abcScore svg")).toBeVisible({
        timeout: STEP_TIMEOUT_MS
      });
      expect(packagePaths).toEqual(
        expect.arrayContaining([
          "/static/packages/psynet/libraries/abc-js/abcjs-basic.js",
          "/static/packages/psynet/scripts/music-notation-prompt.js"
        ])
      );
      await assertNoBackendError(experimentPage);
    }
  );
});

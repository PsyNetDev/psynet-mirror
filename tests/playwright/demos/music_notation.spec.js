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

test("the next score is swapped in before the server replies", { tag: "@inplace-only" }, async ({ page, context }) => {
  await withExperiment(
    page,
    context,
    path.resolve("demos/features/music_notation"),
    async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await expect(experimentPage.locator("#abcScore svg")).toBeVisible({
        timeout: STEP_TIMEOUT_MS
      });
      let release;
      const held = new Promise((resolve) => (release = resolve));
      let replied;
      await experimentPage.route("**/response", async (route) => {
        replied = (async () => {
          const response = await route.fetch();
          await held;
          await route.fulfill({ response });
        })();
        await replied;
      });
      try {
        await experimentPage.getByRole("button", { name: "Next", exact: true }).click();
        await expect(experimentPage.getByText("And here's a scale:")).toBeVisible({ timeout: 30000 });
        await expect(experimentPage.locator("#abcScore svg")).toBeVisible({ timeout: 30000 });
      } finally {
        release();
      }
      await replied;
      // The server's reply confirms the swapped-in page rather than replacing it.
      await expect(experimentPage.locator("#alert-message")).toBeHidden();
      await expect(experimentPage.getByText("And here's a scale:")).toBeVisible();
      await assertNoBackendError(experimentPage);
    }
  );
});

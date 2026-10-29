const path = require("path");
const { test, expect } = require("./fixtures");

const { assertNoBackendError, completeInitialGateway, withExperiment } = require("./psynetHarness");

test("psynet.websocket connects with the page token as its scope", { tag: "@both" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve("tests/experiments/live_session");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#socket-status")).toHaveText("Connected", {
      timeout: 60000
    });

    const state = await experimentPage.evaluate(() => {
      const url = new URL(psynet.websocket.connect().raw.url);
      return {
        route: url.pathname,
        scope: url.searchParams.get("scope"),
        pageToken: psynet.var.pageToken,
        globalToken: Object.prototype.hasOwnProperty.call(window, "pageToken")
      };
    });
    expect(state.route).toBe("/experiment-socket");
    expect(state.pageToken).toMatch(/^[0-9a-f]{64}$/);
    expect(state.scope).toBe(state.pageToken);
    expect(state.globalToken).toBe(false);
    await assertNoBackendError(experimentPage);
  });
});

const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  withExperiment
} = require("./psynetHarness");

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

test("the server closes an old page's psynet.websocket", { tag: "@both" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve("tests/experiments/live_session");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#socket-status")).toHaveText("Connected", {
      timeout: 60000
    });
    const oldPage = await context.newPage();
    await oldPage.goto(experimentPage.url());
    await expect(oldPage.locator("#socket-status")).toHaveText("Connected", { timeout: 60000 });

    await clickNextAndWait(experimentPage);

    await oldPage.waitForFunction(
      () => psynet.websocket.connect().raw.readyState === WebSocket.CLOSED,
      null,
      { timeout: 30000 }
    );
    // Longer than ReconnectingWebSocket's first retry delay.
    await oldPage.waitForTimeout(3000);
    expect(
      await oldPage.evaluate(() => psynet.websocket.connect().raw.readyState === WebSocket.CLOSED)
    ).toBe(true);
    await oldPage.close();
    await assertNoBackendError(experimentPage);
  });
});

test("the server refuses an old page's token and a wrong one with 1008", { tag: "@both" }, async ({
  page,
  context
}) => {
  // Flask's development server writes an HTTP response after the close
  // frame, so browsers see 1006 instead of the code. CI runs gunicorn.
  test.skip(
    !process.env.PSYNET_USE_LEGACY_DEBUG,
    "needs PSYNET_USE_LEGACY_DEBUG=1, which serves the experiment with gunicorn"
  );
  const absDir = path.resolve("tests/experiments/live_session");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#socket-status")).toHaveText("Connected", {
      timeout: 60000
    });
    const oldToken = await experimentPage.evaluate(() => psynet.var.pageToken);
    await clickNextAndWait(experimentPage);

    const refusals = await experimentPage.evaluate(
      (scopes) =>
        Promise.all(
          scopes.map(
            (scope) =>
              new Promise((resolve) => {
                // The server accepts the websocket before it can close it
                // with a code, so the socket opens even when it is refused.
                const socket = dallinger.openExperimentSocket({ scope });
                socket.onRefused((code) => resolve(code));
                setTimeout(() => resolve("not refused"), 10000);
              })
          )
        ),
      [oldToken, "not-a-page-token"]
    );
    expect(refusals).toEqual([1008, 1008]);
    await assertNoBackendError(experimentPage);
  });
});

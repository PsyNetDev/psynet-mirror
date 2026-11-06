const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  beginExperiment,
  clickNextAndWait,
  completeInitialGateway,
  isInplaceTimelineModeEnabled,
  startExperiment,
  stopExperiment,
  withFreshParticipantIds
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

async function reachTheGame(participant) {
  await completeInitialGateway(participant);
  await expect(participant.locator("#socket-status")).toHaveText("Connected", {
    timeout: STEP_TIMEOUT_MS
  });
  await clickNextAndWait(participant);
  await clickNextAndWait(participant);
  await expect(participant.locator("#game-status")).toHaveText("Pick a number", {
    timeout: STEP_TIMEOUT_MS
  });
}

test("a live session page joins its session beside the page socket, shows a rejected message and moves on once the result is saved", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("tests/experiments/live_session"));
  const contexts = [await browser.newContext(), await browser.newContext()];

  try {
    const recruitmentUrl = await experiment.urlPromise;
    const participants = [];
    for (const [index, context] of contexts.entries()) {
      participants.push(
        await beginExperiment(
          await context.newPage(),
          context,
          withFreshParticipantIds(recruitmentUrl, `live_session_${index}`)
        )
      );
    }
    await Promise.all(participants.map(reachTheGame));
    const [first, second] = participants;

    await expect(first.locator("#page-socket-status")).toHaveText("Connected", {
      timeout: STEP_TIMEOUT_MS
    });
    const scopes = await first.evaluate(() => {
      const scopeOf = (socket) => new URL(socket.raw.url).searchParams.get("scope");
      return {
        game: scopeOf(psynet.liveSession.socket),
        page: scopeOf(psynet.websocket.connect()),
        token: psynet.var.pageToken,
        pageScope: dallinger.pageScope
      };
    });
    expect(scopes.game).toBe(scopes.token + "." + scopes.pageScope);
    expect(scopes.page).toBe(scopes.token);
    // A framework variable, so no deprecated window copy.
    expect(await first.evaluate(() => "liveSession" in window)).toBe(false);

    await first.evaluate(() => psynet.liveSession.send("pick", { number: "seven" }));
    await expect(first.locator("#game-error")).toHaveText(
      "Invalid 'pick' message: number: Input should be a valid integer.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect(first.locator("#game-status")).toHaveText("Pick a number");

    await first.locator("#pick").click();
    await expect(first.locator("#game-status")).toHaveText("Picked", {
      timeout: STEP_TIMEOUT_MS
    });

    await first.evaluate(() => {
      window.gameSockets = [psynet.liveSession.socket, psynet.websocket.connect()];
    });
    // The session goes on until the second player picks, so the first page
    // can't move on yet, and sends its response again by itself.
    await first.locator("#next-button").click();
    await expect(first.locator("#psynet-retry-notice")).toHaveText(
      "Please wait while the game finishes...",
      { timeout: STEP_TIMEOUT_MS }
    );
    await second.locator("#pick").click();
    await expect(first.locator("#main-body")).toContainText("The page after the game.", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(first.locator("#psynet-retry-notice")).toHaveCount(0);
    // The second page moves on by itself once the result is saved.
    await expect(second.locator("#main-body")).toContainText("The page after the game.", {
      timeout: STEP_TIMEOUT_MS
    });
    if (isInplaceTimelineModeEnabled()) {
      await expect
        .poll(
          () =>
            first.evaluate(() =>
              window.gameSockets.map((socket) => socket.raw.readyState >= WebSocket.CLOSING)
            ),
          { timeout: STEP_TIMEOUT_MS }
        )
        .toEqual([true, true]);
    } else {
      // The next page is a new window, which closed the old one's sockets.
      expect(await first.evaluate(() => window.gameSockets)).toBeUndefined();
    }
    for (const participant of participants) {
      await assertNoBackendError(participant);
    }
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});

const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  clickNextAndWait,
  isInplaceTimelineModeEnabled,
  startExperiment,
  startParticipantsTogether,
  stopExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

// Takes a participant who has a partner on to the game page.
async function reachTheGame(participant) {
  await clickNextAndWait(participant);
  await expect(participant.locator("#game-status")).toHaveText("Pick a number", {
    timeout: STEP_TIMEOUT_MS
  });
}

test("a live game page joins its game, shows a rejected message and moves on once the result is saved", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("tests/experiments/live_game"));
  const contexts = [await browser.newContext(), await browser.newContext()];

  try {
    const participants = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "psynet"
    );
    await Promise.all(participants.map(reachTheGame));
    const [first, second] = participants;

    const scopes = await first.evaluate(() => ({
      game: new URL(psynet.liveGame.socket.raw.url).searchParams.get("scope"),
      participant: psynetTemplateData.websocketScope,
      pageScope: dallinger.pageScope
    }));
    expect(scopes.game).toBe(scopes.participant + "." + scopes.pageScope + ".1");
    // A framework variable, so no deprecated window copy.
    expect(await first.evaluate(() => "liveGame" in window)).toBe(false);

    await first.evaluate(() => psynet.liveGame.send("pick", { number: "seven" }));
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
      window.gameSocket = psynet.liveGame.socket;
    });
    // The page moves on by itself, so its Next button is hidden. Page code
    // can still submit it, but it can't move on until the second player
    // picks, and it sends its response again by itself.
    await expect(first.locator("#next-button")).toBeHidden();
    await first.evaluate(() => {
      psynet.nextPage();
    });
    await expect(first.locator("#psynet-retry-notice")).toHaveText(
      "The game isn't over yet. The page will move on once it is.",
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
            first.evaluate(() => window.gameSocket.raw.readyState >= WebSocket.CLOSING),
          { timeout: STEP_TIMEOUT_MS }
        )
        .toBe(true);
    } else {
      // The next page is a new window, which closed the old one's socket.
      expect(await first.evaluate(() => window.gameSocket)).toBeUndefined();
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

test("a game page open in two tabs moves the participant on once", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("tests/experiments/live_game"));
  const contexts = [await browser.newContext(), await browser.newContext()];

  try {
    const participants = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "live_game_tabs"
    );
    await Promise.all(participants.map(reachTheGame));
    const [first, second] = participants;
    await first.locator("#pick").click();
    await expect(first.locator("#game-status")).toHaveText("Picked", {
      timeout: STEP_TIMEOUT_MS
    });

    // The other tab joins the game as the same player.
    const otherTab = await contexts[0].newPage();
    await otherTab.goto(first.url());
    await expect(otherTab.locator("#game-status")).toHaveText("Picked", {
      timeout: STEP_TIMEOUT_MS
    });

    // Both tabs hear that the result is saved and submit the page. Only one
    // submission counts, so the participant is on the page after the game,
    // not past it.
    await second.locator("#pick").click();
    await expect(second.locator("#main-body")).toContainText("The page after the game.", {
      timeout: STEP_TIMEOUT_MS
    });
    for (const tab of [first, otherTab]) {
      await expect
        .poll(
          async () => {
            try {
              const text = await tab.locator("#main-body").innerText();
              if (text.includes("The page after the game.")) {
                return text;
              }
              await tab.reload();
              return await tab.locator("#main-body").innerText();
            } catch (error) {
              // In legacy mode, the winning tab reloads on its own while we
              // poll, which can abort our reload or destroy the context.
              if (
                /ERR_ABORTED|NS_BINDING_ABORTED|Execution context was destroyed|frame was detached|Navigation interrupted|Frame load interrupted/i.test(
                  String(error)
                )
              ) {
                return "";
              }
              throw error;
            }
          },
          { timeout: STEP_TIMEOUT_MS }
        )
        .toContain("The page after the game.");
    }
    for (const page of [first, otherTab, second]) {
      await assertNoBackendError(page);
    }
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});

test("participants whose pair breaks up at the game barrier see one notice saying why and can move on", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("tests/experiments/live_game"));
  const contexts = [await browser.newContext(), await browser.newContext()];

  try {
    const participants = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "live_game_alone"
    );
    const [first, second] = participants;
    await Promise.all(
      participants.map(async (participant) => {
        await expect(participant.locator("#main-body")).toContainText("You have a partner.", {
          timeout: STEP_TIMEOUT_MS
        });
      })
    );
    // The partner stays on the page before the game barrier, so the first
    // participant waits there alone until the game barrier removes them from
    // the pair.
    await clickNextAndWait(first);

    // The barrier's notice says why, so the page adds no notice of its own.
    await expect(
      first.getByRole("status").filter({ hasText: "Your partner didn't arrive in time." })
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await expect(first.locator("#psynet-no-game-notice")).toHaveCount(0);
    await expect(first.locator("#game-status")).toHaveText("Joining...");
    expect(await first.evaluate(() => psynet.liveGame.hasGame)).toBe(false);

    // The notice goes when the participant moves on.
    await clickNextAndWait(first);
    await expect(first.locator("#main-body")).toContainText("The page after the game.", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(
      first.getByRole("status").filter({ hasText: "Your partner didn't arrive in time." })
    ).toHaveCount(0);

    // The partner, whose pair has ended, passes the game barrier without
    // waiting and has no game either.
    await clickNextAndWait(second);
    await expect(
      second.getByRole("status").filter({ hasText: "Your partner is no longer in your group." })
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await expect(second.locator("#psynet-no-game-notice")).toHaveCount(0);
    expect(await second.evaluate(() => psynet.liveGame.hasGame)).toBe(false);
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

const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  clickNextAndWait,
  startExperiment,
  startParticipantsTogether,
  stopExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

async function screenshot(page, name) {
  expect(await page.evaluate(() => window.psynetLayout.check()), name).toEqual([]);
  if (process.env.ARTIFACT_DIR) {
    await page.screenshot({ path: `${process.env.ARTIFACT_DIR}/${name}.png`, fullPage: true });
  }
}

// The demo's games: the first has five throws and the second three.
const THROWS = [5, 3];
// In the first game, the first player plays rock every throw, so they win
// throws 1, 3 and 5, draw throw 2 and lose throw 4.
const SECOND_PLAYER_ACTIONS = ["Scissors", "Rock", "Scissors", "Paper", "Scissors"];

async function waitForThrow(participant, number, throws = THROWS[0]) {
  await expect(participant.locator("#rps-status")).toHaveText(
    `Throw ${number} of ${throws}: choose your action`,
    { timeout: STEP_TIMEOUT_MS }
  );
}

// The first player plays rock and the second scissors, in every throw.
async function playGame(first, second, throws) {
  for (let number = 1; number <= throws; number++) {
    await waitForThrow(first, number, throws);
    await waitForThrow(second, number, throws);
    await first.getByRole("button", { name: "Rock" }).click();
    await second.getByRole("button", { name: "Scissors" }).click();
  }
}

test("two participants play rock_paper_scissors_live to the end, with rejected choices, a reload and a partner who leaves and comes back", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/rock_paper_scissors_live"));
  const contexts = [await browser.newContext(), await browser.newContext()];
  // While this is set, the first player's choices are held back from the
  // server, to be sent later.
  let holdChoices = false;
  const heldChoices = [];

  try {
    await contexts[0].routeWebSocket(/\/experiment-socket/, (route) => {
      const server = route.connectToServer();
      route.onMessage((message) => {
        if (holdChoices && String(message).includes('"choose"')) {
          heldChoices.push(() => server.send(message));
        } else {
          server.send(message);
        }
      });
    });
    const pair = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "rock_paper_scissors_live"
    );
    await Promise.all(pair.map((participant) => waitForThrow(participant, 1)));
    const [first] = pair;
    let [, second] = pair;

    // The first game's throws and stakes come from its trials' definition.
    for (const participant of [first, second]) {
      await expect(participant.locator("#rps-stakes")).toHaveText(
        "Game 1 of 2, of 5 throws. Each throw you win pays a bonus of $0.05."
      );
    }

    await first.getByRole("button", { name: "Rock" }).click();
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose");
    await expect(first.locator("#rps-results li")).toHaveCount(0);
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[0] }).click();
    await waitForThrow(first, 2);
    await expect(first.locator("#rps-results li")).toHaveText([
      "You played rock, your partner played scissors. You won the throw."
    ]);
    await expect(second.locator("#rps-results li")).toHaveText([
      "You played scissors, your partner played rock. You lost the throw."
    ]);
    await expect(first.locator("#rps-results li").last()).toHaveText(
      "You played rock, your partner played scissors. You won the throw."
    );
    await screenshot(first, "rock_paper_scissors_live_throw");
    // The page moves on by itself when the game ends, so its Next button is hidden.
    await expect(first.locator("#next-button")).toBeHidden();

    await expect(second.locator("#rps-score")).toHaveText(
      "Throws won: you 0, your partner 1"
    );

    await first.evaluate(() =>
      psynet.liveGame.send("choose", { throw: 1, action: "paper" })
    );
    await expect(first.locator("#rps-rejection")).toHaveText(
      "That isn't the current throw.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await first.getByRole("button", { name: "Rock" }).click();
    await expect(first.locator("#rps-rejection")).toHaveText("");
    await first.evaluate(() =>
      psynet.liveGame.send("choose", { throw: 2, action: "paper" })
    );
    await expect(first.locator("#rps-rejection")).toHaveText(
      "You've already chosen this throw.",
      { timeout: STEP_TIMEOUT_MS }
    );

    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[1] }).click();
    await waitForThrow(first, 3);
    // The rejection stays until the page sends its next choice.
    await expect(first.locator("#rps-rejection")).toHaveText(
      "You've already chosen this throw."
    );
    await expect(first.locator("#rps-results li").nth(1)).toHaveText(
      "You played rock, your partner played rock. The throw was a draw."
    );

    // The reloaded page gets the game as it stands from its first view.
    await first.getByRole("button", { name: "Rock" }).click();
    await expect(first.locator("#rps-rejection")).toHaveText("");
    await expect(second.locator("#rps-partner")).toHaveText("Your partner has chosen.", {
      timeout: STEP_TIMEOUT_MS
    });
    await first.reload();
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(first.getByRole("button", { name: "Rock" })).toBeDisabled();
    await expect(first.locator("#rps-results li")).toHaveCount(2);
    await expect(first.locator("#rps-score")).toHaveText("Throws won: you 1, your partner 0");
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[2] }).click();

    // The partner's choice is applied first, and its view reaches the first
    // page before the first player's own choice is applied.
    await waitForThrow(first, 4);
    await waitForThrow(second, 4);
    holdChoices = true;
    await first.getByRole("button", { name: "Rock" }).click();
    await expect.poll(() => heldChoices.length, { timeout: STEP_TIMEOUT_MS }).toBe(1);
    // No view can have come since the click, so this is the page's prediction.
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose");
    await expect(first.getByRole("button", { name: "Rock" })).toBeDisabled();
    // A choice for throw 4 that reaches the game after throw 4 is over.
    await first.evaluate(() =>
      psynet.liveGame.send("choose", { throw: 4, action: "paper" })
    );
    await expect.poll(() => heldChoices.length, { timeout: STEP_TIMEOUT_MS }).toBe(2);
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[3] }).click();
    await expect(first.locator("#rps-partner")).toHaveText("Your partner has chosen.", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose");
    await expect(first.getByRole("button", { name: "Rock" })).toBeDisabled();
    holdChoices = false;
    heldChoices.forEach((send) => send());

    await waitForThrow(first, 5);
    await expect(first.locator("#rps-rejection")).toHaveText(
      "That isn't the current throw.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await waitForThrow(second, 5);

    // While the partner's page is closed, the first page says so, and the
    // notice goes once the partner is back.
    const gamePage = second.url();
    await second.close();
    const away = first.locator("#psynet-player-away-notice");
    await expect(away).toHaveText(
      "Your partner has left the game. If they don't come back within 30 seconds, it will end.",
      { timeout: STEP_TIMEOUT_MS }
    );
    second = await contexts[1].newPage();
    await second.goto(gamePage);
    await waitForThrow(second, 5);
    await expect(away).toHaveCount(0, { timeout: STEP_TIMEOUT_MS });
    const participants = [first, second];

    await first.getByRole("button", { name: "Rock" }).click();
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[4] }).click();

    // Both pages move on by themselves once the result is saved.
    await expect(first.locator("#main-body")).toContainText("You won the game!", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(first.locator("#main-body")).toContainText(
      "You won 3 of the 5 throws played, and your partner won 1."
    );
    await expect(second.locator("#main-body")).toContainText("Your partner won the game.", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(second.locator("#main-body")).toContainText(
      "You won 1 of the 5 throws played, and your partner won 3."
    );
    // The trial pays its definition's bonus for each throw won.
    await expect(first.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.15."
    );
    await expect(second.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.05."
    );
    for (const participant of participants) {
      await assertNoBackendError(participant);
    }

    // The second game is a new trial for each player, with a new game
    // and the throws and stakes of its own definition.
    await Promise.all(participants.map((participant) => clickNextAndWait(participant)));
    for (const participant of participants) {
      await waitForThrow(participant, 1, THROWS[1]);
      await expect(participant.locator("#rps-stakes")).toHaveText(
        "Game 2 of 2, of 3 throws. Each throw you win pays a bonus of $0.10."
      );
      await expect(participant.locator("#rps-results li")).toHaveCount(0);
    }
    await playGame(first, second, THROWS[1]);
    await expect(first.locator("#main-body")).toContainText(
      "You won 3 of the 3 throws played, and your partner won 0.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect(first.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.30."
    );
    await expect(second.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.00.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await screenshot(first, "rock_paper_scissors_live_result");
    await Promise.all(participants.map((participant) => clickNextAndWait(participant)));
    for (const participant of participants) {
      await expect(participant.locator("#main-body")).toContainText("That's the end", {
        timeout: STEP_TIMEOUT_MS
      });
      await assertNoBackendError(participant);
    }
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});

const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  beginExperiment,
  clickNextAndWait,
  completeInitialGateway,
  startExperiment,
  stopExperiment,
  withFreshParticipantIds
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

// The demo's games: the first has five rounds and the second three.
const ROUNDS = [5, 3];
// How long a player waits at the start of a game for their partner, which is
// the demo's PARTNER_WAIT_SECONDS.
const PARTNER_WAIT_MS = 300000;

// In the first game, the first player plays rock every round, so they win
// rounds 1, 3 and 5, draw round 2 and lose round 4.
const SECOND_PLAYER_ACTIONS = ["Scissors", "Rock", "Scissors", "Paper", "Scissors"];

async function waitForRound(participant, round, rounds = ROUNDS[0]) {
  await expect(participant.locator("#rps-status")).toHaveText(
    `Round ${round} of ${rounds}: choose your action`,
    { timeout: STEP_TIMEOUT_MS }
  );
}

// The first player plays rock and the second scissors, in every round.
async function playGame(first, second, rounds) {
  for (let round = 1; round <= rounds; round++) {
    await waitForRound(first, round, rounds);
    await waitForRound(second, round, rounds);
    await first.getByRole("button", { name: "Rock" }).click();
    await second.getByRole("button", { name: "Scissors" }).click();
  }
}

// Starts two participants and takes them to the first game. ``prepare`` is
// called with their browser contexts before either opens a page.
async function startPair(browser, experiment, name, prepare = async () => {}) {
  const contexts = [await browser.newContext(), await browser.newContext()];
  await prepare(contexts);
  const recruitmentUrl = await experiment.urlPromise;
  const participants = [];
  for (const [index, context] of contexts.entries()) {
    participants.push(
      await beginExperiment(
        await context.newPage(),
        context,
        withFreshParticipantIds(recruitmentUrl, `${name}_${index}`)
      )
    );
  }
  await Promise.all(
    participants.map(async (participant) => {
      await completeInitialGateway(participant);
      await clickNextAndWait(participant);
      await waitForRound(participant, 1);
    })
  );
  return { contexts, participants };
}

test("two participants play rock_paper_scissors_live to the end, with rejected choices, a reload and a partner who leaves and comes back", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/rock_paper_scissors_live"));
  let contexts = [];
  // While this is set, the first player's choices are held back from the
  // server, to be sent later.
  let holdChoices = false;
  const heldChoices = [];

  try {
    const pair = await startPair(
      browser,
      experiment,
      "rock_paper_scissors_live",
      async (created) => {
        contexts = created;
        await created[0].routeWebSocket(/\/experiment-socket/, (route) => {
          const server = route.connectToServer();
          route.onMessage((message) => {
            if (holdChoices && String(message).includes('"choose"')) {
              heldChoices.push(() => server.send(message));
            } else {
              server.send(message);
            }
          });
        });
      }
    );
    contexts = pair.contexts;
    const [first] = pair.participants;
    let [, second] = pair.participants;

    // The first game's rounds and stakes come from its trials' definition.
    for (const participant of [first, second]) {
      await expect(participant.locator("#rps-stakes")).toHaveText(
        "Game 1 of 2, of 5 rounds. Each round you win pays a bonus of $0.05."
      );
    }

    await first.getByRole("button", { name: "Rock" }).click();
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose");
    await expect(first.locator("#rps-results li")).toHaveCount(0);
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[0] }).click();
    await waitForRound(first, 2);
    await expect(first.locator("#rps-results li")).toHaveText([
      "You played rock, your partner played scissors. You won the round."
    ]);
    await expect(second.locator("#rps-results li")).toHaveText([
      "You played scissors, your partner played rock. You lost the round."
    ]);
    await expect(first.locator("#rps-last")).toHaveText(
      "Round 1: You played rock, your partner played scissors. You won the round."
    );
    // The page moves on by itself when the game ends, so its Next button is hidden.
    await expect(first.locator("#next-button")).toBeHidden();

    await expect(second.locator("#rps-score")).toHaveText(
      "Rounds won: you 0, your partner 1"
    );

    await first.evaluate(() =>
      psynet.liveSession.send("choose", { round: 1, action: "paper" })
    );
    await expect(first.locator("#rps-rejection")).toHaveText(
      "That isn't the current round.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await first.getByRole("button", { name: "Rock" }).click();
    await expect(first.locator("#rps-rejection")).toHaveText("");
    await first.evaluate(() =>
      psynet.liveSession.send("choose", { round: 2, action: "paper" })
    );
    await expect(first.locator("#rps-rejection")).toHaveText(
      "You've already chosen this round.",
      { timeout: STEP_TIMEOUT_MS }
    );

    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[1] }).click();
    await waitForRound(first, 3);
    // A new round clears the last round's rejection.
    await expect(first.locator("#rps-rejection")).toHaveText("");
    await expect(first.locator("#rps-results li").nth(1)).toHaveText(
      "You played rock, your partner played rock. The round was a draw."
    );

    // The reloaded page gets the game as it stands from its first view.
    await first.getByRole("button", { name: "Rock" }).click();
    await expect(second.locator("#rps-partner")).toHaveText("Your partner has chosen.", {
      timeout: STEP_TIMEOUT_MS
    });
    await first.reload();
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(first.getByRole("button", { name: "Rock" })).toBeDisabled();
    await expect(first.locator("#rps-results li")).toHaveCount(2);
    await expect(first.locator("#rps-score")).toHaveText("Rounds won: you 1, your partner 0");
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[2] }).click();

    // The partner's choice is applied first, and its view reaches the first
    // page before the first player's own choice is applied.
    await waitForRound(first, 4);
    await waitForRound(second, 4);
    holdChoices = true;
    await first.getByRole("button", { name: "Rock" }).click();
    await expect.poll(() => heldChoices.length, { timeout: STEP_TIMEOUT_MS }).toBe(1);
    // No view can have come since the click, so this is the page's prediction.
    await expect(first.locator("#rps-status")).toHaveText("Waiting for your partner to choose");
    await expect(first.getByRole("button", { name: "Rock" })).toBeDisabled();
    // A choice for round 4 that reaches the game after round 4 is over.
    await first.evaluate(() =>
      psynet.liveSession.send("choose", { round: 4, action: "paper" })
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

    await waitForRound(first, 5);
    await expect(first.locator("#rps-rejection")).toHaveText(
      "That isn't the current round.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await waitForRound(second, 5);

    // While the partner's page is closed, the first page says so, and the
    // notice goes once the partner is back.
    const gamePage = second.url();
    await second.close();
    const away = first.locator("#psynet-player-away-notice");
    await expect(away).toHaveText(
      "Your partner has left the game. If they don't come back, it will end in a few minutes.",
      { timeout: STEP_TIMEOUT_MS }
    );
    second = await contexts[1].newPage();
    await second.goto(gamePage);
    await waitForRound(second, 5);
    await expect(away).toHaveCount(0, { timeout: STEP_TIMEOUT_MS });
    const participants = [first, second];

    await first.getByRole("button", { name: "Rock" }).click();
    await second.getByRole("button", { name: SECOND_PLAYER_ACTIONS[4] }).click();

    // Both pages move on by themselves once the result is saved.
    await expect(first.locator("#main-body")).toContainText("You won the game!", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(first.locator("#main-body")).toContainText(
      "You won 3 of the 5 rounds played, and your partner won 1."
    );
    await expect(second.locator("#main-body")).toContainText("Your partner won the game.", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(second.locator("#main-body")).toContainText(
      "You won 1 of the 5 rounds played, and your partner won 3."
    );
    // The trial pays its definition's bonus for each round won.
    await expect(first.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.15."
    );
    await expect(second.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.05."
    );
    for (const participant of participants) {
      await assertNoBackendError(participant);
    }

    // The second game is a new trial for each player, with a new session
    // and the rounds and stakes of its own definition.
    await Promise.all(participants.map((participant) => clickNextAndWait(participant)));
    for (const participant of participants) {
      await waitForRound(participant, 1, ROUNDS[1]);
      await expect(participant.locator("#rps-stakes")).toHaveText(
        "Game 2 of 2, of 3 rounds. Each round you win pays a bonus of $0.10."
      );
      await expect(participant.locator("#rps-results li")).toHaveCount(0);
    }
    await playGame(first, second, ROUNDS[1]);
    await expect(first.locator("#main-body")).toContainText(
      "You won 3 of the 3 rounds played, and your partner won 0.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect(first.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.30."
    );
    await expect(second.locator("#main-body")).toContainText(
      "Your bonus for this game is $0.00.",
      { timeout: STEP_TIMEOUT_MS }
    );
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

test("a player whose partner doesn't come back for the second game plays no more games", { tag: "@both" }, async ({
  browser
}) => {
  // The player waits PARTNER_WAIT_MS for their partner.
  test.setTimeout(PARTNER_WAIT_MS + 10 * 60 * 1000);
  const experiment = startExperiment(path.resolve("demos/experiments/rock_paper_scissors_live"));
  let contexts = [];

  try {
    const pair = await startPair(browser, experiment, "rock_paper_scissors_live_alone");
    contexts = pair.contexts;
    const [first, second] = pair.participants;
    await playGame(first, second, ROUNDS[0]);
    await expect(first.locator("#main-body")).toContainText("You won the game!", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(second.locator("#main-body")).toContainText("Your partner won the game.", {
      timeout: STEP_TIMEOUT_MS
    });

    // The partner leaves. The first player waits for them at the start of
    // the second game, then leaves the pair and reaches the game page
    // without a session, where there is no game to see.
    await second.close();
    await first.locator("#next-button").click();
    await expect(first.locator("#psynet-no-session-notice")).toHaveText(
      "This game can't be played without your partner.",
      { timeout: PARTNER_WAIT_MS + STEP_TIMEOUT_MS }
    );
    await expect(first.locator("#rps-game")).toBeHidden();

    // The trial has no answer, so it shows no feedback, and the page after
    // the games says why there are no more, with the first game's bonus.
    await clickNextAndWait(first);
    await expect(first.locator("#main-body")).toContainText(
      "Your partner didn't come back for the next game. Your bonus is $0.25.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await clickNextAndWait(first);
    await expect(first.locator("#main-body")).toContainText("That's the end", {
      timeout: STEP_TIMEOUT_MS
    });
    await assertNoBackendError(first);
  } finally {
    for (const context of contexts) {
      await context.close();
    }
    await stopExperiment(experiment.proc);
  }
});

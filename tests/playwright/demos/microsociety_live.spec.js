const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  checkLayoutAndScreenshot,
  clickNextAndWait,
  startExperiment,
  startParticipantsTogether,
  stopExperiment,
  waitForPromptContains
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

function spot(player, number) {
  return player.getByRole("button", { name: `Spot ${"ABCDEFGH"[number - 1]}`, exact: true });
}

// The boats (all, or only the player's own) whose centres are over a spot; boats glide over the lake, outside the spots.
function boatsAt(player, number, selector = ".fish-boat-wrapper") {
  return player.evaluate(
    ([number, selector]) => {
      let area = document.querySelectorAll(".fish-spot")[number - 1].getBoundingClientRect();
      return [...document.querySelectorAll(selector)].filter((boat) => {
        let box = boat.getBoundingClientRect();
        let x = box.left + box.width / 2;
        let y = box.top + box.height / 2;
        return x >= area.left && x <= area.right && y >= area.top && y <= area.bottom;
      }).length;
    },
    [number, selector]
  );
}

test("newcomers sail onto the lake while the founder fishes, and fish on after it leaves", { tag: "@both" }, async ({
  browser
}) => {
  // The lake ticks, so it runs on gunicorn, as a deployed experiment does.
  const experiment = startExperiment(path.resolve("demos/experiments/microsociety_live"), { legacy: true });
  const contexts = await Promise.all([0, 1, 2].map(() => browser.newContext()));
  try {
    const url = await experiment.urlPromise;
    // The first participant founds the society and opens the lake alone,
    // without waiting for anyone.
    const [founder] = await startParticipantsTogether(contexts.slice(0, 1), url, "microsociety_live");
    await expect(spot(founder, 1)).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    await spot(founder, 6).click();
    // Moving to the spot the boat is already at is rejected.
    await expect.poll(() => boatsAt(founder, 6, ".fish-boat-wrapper:has(.fish-who-you)")).toBe(1);
    await founder.evaluate(() => psynet.liveGame.send("move", { spot: 6 }));
    await expect(founder.locator("#fish-rejection")).toHaveText("Your boat is already there.");

    // Once the founder has caught something, so the society has a history,
    // two newcomers join while the founder fishes, read it, and sail onto
    // the running lake without waiting.
    await expect(founder.locator(".fish-boat-wrapper .fish-count.fish-who-you")).not.toHaveText(
      "You 🐟 0",
      { timeout: STEP_TIMEOUT_MS }
    );
    const newcomers = await startParticipantsTogether(contexts.slice(1), url, "microsociety_live_newcomer");
    for (const newcomer of newcomers) {
      await waitForPromptContains(newcomer, "The others are already fishing");
    }
    await checkLayoutAndScreenshot(newcomers[0], "microsociety_live_history");
    await Promise.all(newcomers.map((newcomer) => clickNextAndWait(newcomer)));
    for (const newcomer of newcomers) {
      await expect(spot(newcomer, 1)).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    }
    const [newcomer, other] = newcomers;
    await spot(newcomer, 6).click();
    await spot(other, 3).click();
    // Each member sees every boat on the lake, the newcomers' included.
    await expect.poll(() => boatsAt(founder, 6)).toBe(2);
    await expect.poll(() => boatsAt(newcomer, 3)).toBe(1);
    await expect(newcomer.locator(".fish-boat-wrapper .fish-count")).toHaveCount(3);
    await expect(newcomer.locator(".fish-boat-wrapper .fish-count.fish-who-you")).toHaveText(/^You 🐟 \d+$/);
    await newcomer.locator(".fish-catch").first().waitFor({ timeout: 10000 }).catch(() => {});
    await checkLayoutAndScreenshot(newcomer, "microsociety_live_lake");

    // The founder's time on the lake ends first: they see their results,
    // then leave a tip, while the newcomers fish on.
    await expect(founder.locator("#fish-results .fish-results-boat")).not.toHaveCount(0, {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(founder.locator("#fish-status")).toHaveText("Your time on the lake is up.");
    await checkLayoutAndScreenshot(founder, "microsociety_live_results");
    for (const player of newcomers) {
      await expect(player.locator(".fish-boat-wrapper")).toHaveCount(2, { timeout: STEP_TIMEOUT_MS });
      await expect(spot(player, 1)).toBeEnabled();
    }
    await waitForPromptContains(founder, "Leave one tip", STEP_TIMEOUT_MS);
    for (const player of [founder, ...newcomers]) {
      await assertNoBackendError(player);
    }
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    await stopExperiment(experiment.proc);
  }
});

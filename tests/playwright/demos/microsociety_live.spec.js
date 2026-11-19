const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  clickNextAndWait,
  startExperiment,
  startParticipantsTogether,
  stopExperiment,
  waitForPromptContains
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

async function screenshot(page, name) {
  expect(await page.evaluate(() => window.psynetLayout.check()), name).toEqual([]);
  if (process.env.ARTIFACT_DIR) {
    await page.screenshot({ path: `${process.env.ARTIFACT_DIR}/${name}.png`, fullPage: true });
  }
}

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

test("a newcomer sails onto the lake while the founders fish, and fishes on after they leave", { tag: "@both" }, async ({
  browser
}) => {
  // The lake ticks, so it runs on gunicorn, as a deployed experiment does.
  const experiment = startExperiment(path.resolve("demos/experiments/microsociety_live"), { legacy: true });
  const contexts = await Promise.all([0, 1, 2].map(() => browser.newContext()));
  try {
    const url = await experiment.urlPromise;
    const founders = await startParticipantsTogether(contexts.slice(0, 2), url, "microsociety_live");
    for (const player of founders) {
      await expect(spot(player, 1)).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    }
    const [first, second] = founders;
    await spot(first, 6).click();
    await spot(second, 3).click();
    // Moving to the spot the boat is already at is rejected.
    await expect.poll(() => boatsAt(first, 6, ".fish-boat-wrapper:has(.fish-who-you)")).toBe(1);
    await first.evaluate(() => psynet.liveGame.send("move", { spot: 6 }));
    await expect(first.locator("#fish-rejection")).toHaveText("Your boat is already there.");

    // Once the first player has caught something, so the society has a
    // history, a newcomer joins while the founders fish, reads it, and
    // sails onto the running lake without waiting.
    await expect(first.locator(".fish-boat-wrapper .fish-count.fish-who-you")).not.toHaveText(
      "You 🐟 0",
      { timeout: STEP_TIMEOUT_MS }
    );
    const [newcomer] = await startParticipantsTogether(contexts.slice(2), url, "microsociety_live_newcomer");
    await waitForPromptContains(newcomer, "The others are already fishing");
    await screenshot(newcomer, "microsociety_live_history");
    await clickNextAndWait(newcomer);
    await expect(spot(newcomer, 1)).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    await spot(newcomer, 6).click();
    // Each member sees every boat on the lake, the newcomer's included.
    await expect.poll(() => boatsAt(first, 6)).toBe(2);
    await expect.poll(() => boatsAt(newcomer, 3)).toBe(1);
    await expect(newcomer.locator(".fish-boat-wrapper .fish-count")).toHaveCount(3);
    await expect(newcomer.locator(".fish-boat-wrapper .fish-count.fish-who-you")).toHaveText(/^You 🐟 \d+$/);
    await newcomer.locator(".fish-catch").first().waitFor({ timeout: 10000 }).catch(() => {});
    await screenshot(newcomer, "microsociety_live_lake");

    // The founders' time on the lake ends first: each sees their results,
    // then leaves a tip, while the newcomer fishes on alone.
    for (const player of founders) {
      await expect(player.locator("#fish-results .fish-results-boat")).not.toHaveCount(0, {
        timeout: STEP_TIMEOUT_MS
      });
      await expect(player.locator("#fish-status")).toHaveText("Your time on the lake is up.");
    }
    await first
      .locator("#fish-results")
      .evaluate((panel) => Promise.all(panel.getAnimations().map((animation) => animation.finished)));
    await screenshot(first, "microsociety_live_results");
    await expect(newcomer.locator(".fish-boat-wrapper")).toHaveCount(1, { timeout: STEP_TIMEOUT_MS });
    await expect(spot(newcomer, 1)).toBeEnabled();
    for (const player of founders) {
      await waitForPromptContains(player, "Leave one tip", STEP_TIMEOUT_MS);
      await assertNoBackendError(player);
    }
    await assertNoBackendError(newcomer);
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    await stopExperiment(experiment.proc);
  }
});

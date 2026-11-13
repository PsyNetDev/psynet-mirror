const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
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

test("a team of three plays a round of public_goods_live, seeing each other's contributions live", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/public_goods_live"));
  const contexts = await Promise.all([0, 1, 2].map(() => browser.newContext()));
  try {
    const team = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "public_goods_live"
    );
    for (const player of team) {
      await expect(player.locator("#pg-tokens")).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    }
    const [first, second, third] = team;

    await first.locator("#pg-tokens").fill("6");
    await second.locator("#pg-tokens").fill("2");
    // Each player sees the others' contributions as they change, the others
    // in the order they joined.
    await expect(third.locator(".pg-row .pg-count")).toHaveText([
      "0 in the pot",
      "6 in the pot",
      "2 in the pot"
    ]);
    await expect(third.locator("#pg-pot")).toHaveText("Pot: 8 tokens × 1.5 = 12");
    await expect(third.locator("#pg-earn")).toHaveText(
      "If the round ended now, each player would get 4 tokens from the pot, " +
        "and you would earn 14 tokens."
    );
    await expect(first.locator("#pg-earn")).toContainText("you would earn 8 tokens");
    await screenshot(third, "public_goods_live_round");

    // When the time is up, the page moves on to the round's results.
    for (const player of team) {
      await expect(player.locator("#main-body")).toContainText(
        "The group put 8 tokens in the pot",
        { timeout: STEP_TIMEOUT_MS }
      );
      await assertNoBackendError(player);
    }
    await expect(first.locator("#main-body")).toContainText("you earned 8 tokens");
    await screenshot(first, "public_goods_live_results");
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    await stopExperiment(experiment.proc);
  }
});

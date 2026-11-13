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

function spot(player, number) {
  return player.getByRole("button", { name: `Spot ${number}`, exact: true });
}

test("a society of three fishes live on the lake, seeing each other's boats and catches", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/microsociety_live"));
  const contexts = await Promise.all([0, 1, 2].map(() => browser.newContext()));
  try {
    const society = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "microsociety_live"
    );
    for (const player of society) {
      await expect(spot(player, 1)).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    }
    const [first, second, third] = society;

    await spot(first, 6).click();
    await spot(second, 3).click();
    await spot(third, 6).click();
    // Each member sees every boat where it is.
    await expect(spot(third, 6).locator(".fish-boat")).toHaveCount(2);
    await expect(spot(third, 3).locator(".fish-boat")).toHaveCount(1);
    await expect(spot(first, 6).locator(".fish-who-you")).toHaveCount(1);
    await expect(third.locator(".fish-score")).toHaveText([
      /^You: \d+ 🐟$/,
      /^Member B: \d+ 🐟$/,
      /^Member C: \d+ 🐟$/
    ]);

    // Moving to the spot the boat is already at is rejected.
    await first.evaluate(() => psynet.liveSession.send("move", { spot: 6 }));
    await expect(first.locator("#fish-rejection")).toHaveText("Your boat is already there.");

    // A catch shows on the lake for a moment; the screenshot catches it if it can.
    await third.locator(".fish-catch").first().waitFor({ timeout: 10000 }).catch(() => {});
    await screenshot(third, "microsociety_live_lake");

    // When the round's time is up, every member sees their results.
    for (const player of society) {
      await expect(player.locator("#main-body")).toContainText(/You caught \d+ fish this round/, {
        timeout: STEP_TIMEOUT_MS
      });
      await assertNoBackendError(player);
    }
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    await stopExperiment(experiment.proc);
  }
});

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

async function propose(player, keep) {
  await player.locator("#bargain-keep").fill(String(keep));
  await player.getByRole("button", { name: "Propose" }).click();
}

test("a cohort of four bargains live in pairs, and a proposal that changed can't be accepted by mistake", { tag: "@both" }, async ({
  browser
}) => {
  const experiment = startExperiment(path.resolve("demos/experiments/bargaining_live"));
  const contexts = await Promise.all([0, 1, 2, 3].map(() => browser.newContext()));
  try {
    const cohort = await startParticipantsTogether(
      contexts,
      await experiment.urlPromise,
      "bargaining_live"
    );
    for (const player of cohort) {
      await expect(player.locator("#bargain-propose")).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
    }

    // Each player proposes to keep a different amount, so each page's
    // partner's proposal says who its partner is.
    for (const [i, player] of cohort.entries()) {
      await propose(player, 5 + i);
    }
    const partnerOf = [];
    for (const player of cohort) {
      const theirs = player.locator("#bargain-theirs");
      await expect(theirs).toHaveText(/^They keep \d+/);
      partnerOf.push(Number((await theirs.textContent()).match(/They keep (\d+)/)[1]) - 5);
    }
    const first = cohort[0];
    const partner = cohort[partnerOf[0]];
    expect(partnerOf[partnerOf[0]]).toBe(0);
    await expect(first.locator("#bargain-mine-coins .bargain-coin-you")).toHaveCount(5);
    await screenshot(first, "bargaining_live_proposals");

    // The partner changes their proposal, to one that no player opened
    // with, just before the first player accepts the old one, so the game
    // rejects the acceptance. Each pair's stake is 10 or 20 coins, chosen at
    // random.
    const stake = Number(await first.locator("#bargain-keep").getAttribute("max"));
    expect([10, 20]).toContain(stake);
    const old = 5 + partnerOf[0];
    await propose(partner, 9);
    await expect(first.locator("#bargain-theirs")).toHaveText(
      `They keep 9, you get ${stake - 9}.`
    );
    await first.evaluate((keep) => psynet.liveSession.send("accept", { keep }), old);
    await expect(first.locator("#bargain-rejection")).toHaveText(
      "Your partner has just changed their proposal."
    );

    await first.getByRole("button", { name: "Accept" }).click();
    for (const player of [first, partner]) {
      await expect(player.locator("#bargain-deal")).toBeVisible();
    }
    await expect(first.locator("#bargain-deal")).toHaveText(
      `Deal! You get ${stake - 9} coins and your partner gets 9.`
    );
    await screenshot(first, "bargaining_live_deal");

    // The other pair makes a deal too, and everyone sees their results.
    const others = cohort.filter((player) => player !== first && player !== partner);
    await others[0].getByRole("button", { name: "Accept" }).click();
    await expect(first.locator("#main-body")).toContainText(
      `You made a deal: you get ${stake - 9} coins and your partner gets 9.`,
      { timeout: STEP_TIMEOUT_MS }
    );
    for (const player of cohort) {
      await expect(player.locator("#main-body")).toContainText("You made a deal", {
        timeout: STEP_TIMEOUT_MS
      });
      await assertNoBackendError(player);
    }
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    await stopExperiment(experiment.proc);
  }
});

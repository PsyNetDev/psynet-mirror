const path = require("path");
const { test, expect } = require("../fixtures");
const { completeInitialGateway, withExperiment } = require("../psynetHarness");

test("the live staircase follows the answers and restores the current pair", { tag: "@both" }, async ({ page, context }) => {
  await withExperiment(page, context, path.resolve("demos/features/live_trial_game_adaptive"), async (p) => {
    await completeInitialGateway(p);
    await p.getByRole("button", { name: "Next", exact: true }).click();
    const patches = p.locator("#patches");
    for (const [slot, gap] of [24, 16, 24, 32, 48, 48, 32, 24].entries()) {
      await expect(patches).toBeVisible();
      const view = await p.evaluate(() => psynet.liveGame.predictedView());
      expect(view.completed).toBe(slot);
      expect(view.deck).toBeUndefined();
      if (slot === 1) {
        await p.reload();
        await expect(patches).toBeVisible();
        const resumed = await p.evaluate(() => psynet.liveGame.predictedView());
        expect(resumed.completed).toBe(slot);
        expect(resumed.definition).toEqual(view.definition);
      }
      const { left, right } = view.definition;
      expect(Math.abs(left - right)).toBe(gap);
      await expect(p.locator("#left-patch")).toHaveCSS("background-color", `rgb(${left}, ${left}, ${left})`);
      const correct = slot === 0 || slot >= 5;
      await p.keyboard.press((right > left) === correct ? "ArrowRight" : "ArrowLeft");
    }
    await expect(p.getByText("You got 4 of 8 correct.")).toBeVisible();
  });
});

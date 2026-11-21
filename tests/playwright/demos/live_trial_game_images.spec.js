const path = require("path");
const { test, expect } = require("../fixtures");
const { completeInitialGateway, withExperiment } = require("../psynetHarness");

test("the bird round preloads every photo before accepting answers", { tag: "@both" }, async ({ page, context }) => {
  const dir = path.resolve("demos/features/live_trial_game_images");
  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    await expect(participant.getByText(/For each photograph/)).toBeVisible();
    const requests = [];
    const finished = [];
    const photos = /\/static\/birds\/[^/]+\.jpg$/;
    participant.on("requestfinished", request => {
      if (photos.test(request.url())) finished.push(request.url());
    });
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    await participant.route(photos, async route => {
      const url = route.request().url();
      requests.push(url);
      if (url.endsWith("/waxwing.jpg")) await gate;
      await route.continue();
    });
    try {
      await participant.getByRole("button", { name: "Next", exact: true }).click();
      await expect.poll(() => finished.length).toBe(5);
      await expect(participant.locator("#birds img:visible")).toHaveCount(0);
      await participant.keyboard.press("ArrowLeft");
    } finally {
      release();
    }
    const shown = participant.locator("#birds img:visible");
    await expect(shown).toHaveCount(1);
    const deck = await participant.evaluate(() => psynet.liveGame.predictedView().deck);
    expect(deck).toHaveLength(6);
    expect(new Set(finished).size).toBe(6);
    for (const { bird } of deck) {
      await expect(shown).toHaveAttribute("id", bird);
      await participant.keyboard.press("ArrowLeft");
    }
    await expect(participant.getByText("You got 3 of 6 correct.")).toBeVisible();
    expect(requests).toHaveLength(6);
  });
});

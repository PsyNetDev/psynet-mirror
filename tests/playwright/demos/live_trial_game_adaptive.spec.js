const path = require("path");
const { test, expect } = require("../fixtures");
const { completeInitialGateway, withExperiment } = require("../psynetHarness");

test("a running staircase deals native trials and recovers a lost reply", { tag: "@both" }, async ({ page, context }) => {
  await withExperiment(page, context, path.resolve("demos/features/live_trial_game_adaptive"), async (p) => {
    await completeInitialGateway(p);
    await p.getByRole("button", { name: "Next", exact: true }).click();
    const patches = p.locator("#patches");
    const readGrey = (side) => p.locator(`#${side}-patch`).evaluate(
      el => Number(getComputedStyle(el).backgroundColor.match(/^rgb\((\d+)/)[1])
    );
    let firstRequest;
    let firstReply;
    const answers = [];
    await p.route("**/live_game/trial", async route => {
      const body = route.request().postDataJSON();
      if (body.response) answers.push(body.response);
      if (body.response?.position === 0 && !firstRequest) {
        firstRequest = body;
        const committed = await route.fetch();
        expect(committed.ok()).toBeTruthy();
        firstReply = await committed.json();
        await route.abort("failed");
      } else {
        await route.continue();
      }
    });

    for (const [position, gap] of [24, 16, 24, 32, 48, 48, 32, 24].entries()) {
      await expect(patches).toHaveAttribute("data-position", String(position));
      await expect(patches).toBeVisible();
      const left = await readGrey("left");
      const right = await readGrey("right");
      expect(Math.abs(left - right)).toBe(gap);
      if (position === 1) {
        expect(answers).toEqual([firstRequest.response, firstRequest.response]);
        expect(firstReply.definition).toEqual({ left, right });
        const post = (data) => p.request.post(new URL("/live_game/trial", p.url()).href, {data});
        // Two tabs retry the acknowledged answer at the same time.
        const replies = await Promise.all([post(firstRequest), post(firstRequest)]);
        for (const reply of replies) expect(await reply.json()).toEqual(firstReply);
        const conflicting = await post({...firstRequest, response: {...firstRequest.response, answer:
          firstRequest.response.answer === "left" ? "right" : "left"}});
        expect(conflicting.status()).toBe(409);
        await p.reload();
        await expect(patches).toHaveAttribute("data-position", "1");
        await expect(patches).toBeVisible();
        expect([await readGrey("left"), await readGrey("right")]).toEqual([left, right]);
      }
      const correct = position === 0 || position >= 5;
      await p.keyboard.press((right > left) === correct ? "ArrowRight" : "ArrowLeft");
    }
    await expect(p.getByText("You got 4 of 8 correct.")).toBeVisible();
  });
});

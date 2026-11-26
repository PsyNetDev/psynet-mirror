const path = require("path");
const { test, expect } = require("../fixtures");
const {
  completeInitialGateway,
  isInplaceTimelineModeEnabled,
  withExperiment
} = require("../psynetHarness");

// The trial pages draw and answer through the JSPage module's update() export.
test("the staircase answers each trial page on a key press", { tag: "@both" }, async ({ page, context }) => {
  const dir = path.resolve("demos/features/staircase_on_one_page");
  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    await participant.getByRole("button", { name: "Next", exact: true }).click();

    const patches = participant.locator("#patches");
    const grey = (side) =>
      participant
        .locator(`#${side}-patch`)
        .evaluate((el) => Number(getComputedStyle(el).backgroundColor.match(/\d+/)[0]));
    await expect(patches).toBeVisible();
    // Each next trial comes from the server, but the page stays on screen,
    // unless every page change reloads the page.
    const kept = isInplaceTimelineModeEnabled();
    await patches.evaluate((el) => (el.dataset.firstTrial = "true"));
    for (let trial = 0; trial < 8; trial++) {
      await expect(patches).toBeVisible();
      if (kept) await expect(patches).toHaveAttribute("data-first-trial", "true");
      const brighter = (await grey("left")) > (await grey("right")) ? "ArrowLeft" : "ArrowRight";
      await participant.keyboard.press(brighter);
    }
    await expect(participant.getByText("You got 8 of 8 correct.")).toBeVisible();
  });
});

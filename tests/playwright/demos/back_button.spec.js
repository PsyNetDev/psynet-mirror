const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("Back shows the previous timeline page at once and replaces its answer", {
  tag: "@inplace-only"
}, async ({ page, context }) => {
  const dir = path.resolve("demos/features/back_button");

  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    const back = participant.locator("#back-button");
    const nextButton = participant.getByRole("button", { name: "Next", exact: true });
    const show = (text) => waitForMainBodyContains(participant, text, STEP_TIMEOUT_MS);
    const answersSent = () =>
      participant.waitForFunction(
        () => psynet.previousPage && !psynet.answers.queue.length && !psynet.answers.sending
      );

    let held = null;
    let posted = 0;
    await participant.route("**/response", async (route) => {
      posted += 1;
      await held;
      await route.continue();
    });

    await show("Welcome!");
    await expect(back).toHaveCount(0);
    const nextBox = await nextButton.boundingBox();
    await nextButton.click();
    await show("Instructions, page 1 of 3");

    // Back sits beside Next, which stays where it was.
    const [newNextBox, backBox] = [await nextButton.boundingBox(), await back.boundingBox()];
    expect(Math.abs(newNextBox.x - nextBox.x)).toBeLessThan(1);
    expect(backBox.x + backBox.width).toBeLessThanOrEqual(newNextBox.x);

    // The browser has the previous page, so Back doesn't wait for the server.
    await answersSent();
    let release;
    held = new Promise((resolve) => (release = resolve));
    posted = 0;
    await back.click();
    await show("Welcome!");
    await expect.poll(() => posted).toBe(1);
    release();

    for (const text of ["page 1 of 3", "page 2 of 3", "page 3 of 3", "Pick a colour."]) {
      await nextButton.click();
      await show(text);
    }
    await participant.getByRole("button", { name: "red" }).click();
    await show("Pick an animal.");
    await answersSent();
    await back.click();
    await show("Pick a colour.");
    await participant.getByRole("button", { name: "blue" }).click();
    await show("Pick an animal.");
    await participant.getByRole("button", { name: "owl" }).click();

    await show("Your answers are now final");
    await expect(back).toHaveCount(0);
    await nextButton.click();
    await show("You chose blue and owl.");
    await expect(back).toHaveCount(0);
    await assertNoBackendError(participant);
  });
});

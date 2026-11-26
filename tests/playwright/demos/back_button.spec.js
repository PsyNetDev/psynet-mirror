const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("Back shows the previous page at once and never returns to a question", {
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

    // A page that the next page can go back to shows Back disabled, so it
    // doesn't appear from nowhere on the next page.
    await show("Welcome!");
    await expect(back).toBeDisabled();
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

    for (const text of ["page 1 of 3", "page 2 of 3", "page 3 of 3", "Which colour"]) {
      await nextButton.click();
      await show(text);
    }
    // The question can go back to the instructions...
    await answersSent();
    await back.click();
    await show("page 3 of 3");
    await nextButton.click();
    await show("Which colour");
    await participant.getByRole("textbox").fill("green");
    await nextButton.click();

    // ...but nothing goes back to the question, and the last page opts out.
    await show("Thanks!");
    await expect(back).toBeDisabled();
    await nextButton.click();
    await show("a run of just two pages");
    await expect(back).toBeEnabled();
    await nextButton.click();
    await show("hides its Back button");
    await expect(back).toHaveCount(0);
    await assertNoBackendError(participant);
  });
});

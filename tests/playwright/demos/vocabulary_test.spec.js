const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertNoBackendError,
  completeInitialGateway,
  waitForTimelinePageReady,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("vocabulary words follow each other on one page", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const dir = path.resolve("demos/experiments/vocabulary_test");

  await withExperiment(page, context, dir, async (participant) => {
    await completeInitialGateway(participant);
    const next = participant.getByRole("button", { name: "Next", exact: true });
    const onPage = (text) =>
      expect(participant.getByText(text).first()).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await onPage("Welcome to the experiment!");
    await next.click();
    await onPage("We will perform a test to check your language abilities.");
    await next.click();
    await onPage("You should not pay attention to subtle spelling differences.");
    await next.click();
    await onPage("You can use the following keys");
    // The page only counts key presses once it is ready.
    await waitForTimelinePageReady(participant, STEP_TIMEOUT_MS);
    await participant.keyboard.press("a");
    await participant.keyboard.press("l");
    await next.click();
    await onPage("The test will start on the next page.");
    await next.click();

    const word = participant.locator("#test-stimulus img");
    await expect(word).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    // A full page load would drop this marker.
    await participant.evaluate(() => (window.vocabSamePage = true));
    let previous = await word.getAttribute("src");
    for (const key of ["a", "l", "a"]) {
      await participant.keyboard.press(key);
      await expect(word).not.toHaveAttribute("src", previous);
      await expect(word).toBeVisible();
      previous = await word.getAttribute("src");
    }
    expect(await participant.evaluate(() => window.vocabSamePage)).toBe(true);
    await assertNoBackendError(participant);
  });
});

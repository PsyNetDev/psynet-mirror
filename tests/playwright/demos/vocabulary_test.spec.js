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

    await expect(participant.locator("#test-stimulus img")).toBeVisible({
      timeout: STEP_TIMEOUT_MS
    });
    // Each word hides after a second, so record the words as they are shown.
    // A full page load would drop these globals.
    await participant.evaluate(() => {
      const target = document.querySelector("#test-stimulus");
      window.vocabShown = [target.querySelector("img").src];
      new MutationObserver(() => {
        const img = target.querySelector("img");
        if (img && img.src !== window.vocabShown.at(-1)) window.vocabShown.push(img.src);
      }).observe(target, { childList: true });
    });
    const saved = [];
    participant.on("response", (response) => {
      if (response.url().endsWith("/response") && response.request().method() === "POST") {
        saved.push(response.status());
      }
    });
    const shown = () => participant.evaluate(() => window.vocabShown?.length);
    for (const [index, key] of ["a", "l", "a"].entries()) {
      await participant.keyboard.press(key);
      await expect.poll(shown, { timeout: STEP_TIMEOUT_MS }).toBe(index + 2);
    }
    await expect.poll(() => saved.length, { timeout: STEP_TIMEOUT_MS }).toBe(3);
    expect(saved).toEqual([200, 200, 200]);
    await assertNoBackendError(participant);
  });
});

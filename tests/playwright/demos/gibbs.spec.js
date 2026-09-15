const path = require("path");
const { test, expect } = require("../fixtures");

const { completeInitialGateway, withExperiment } = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

/*
Regression coverage for the migrated color-slider page (js_page_modules) under the
default in-place timeline transitions.

The gibbs color-slider control ships its page JavaScript as a managed ES module
(static/color-slider.js). Its activate hook runs after the slider control exists,
and reaching this page must not raise an uncaught error. The failOnPageErrors
fixture turns such an error into a test failure. Bot tests do not execute JS.
*/

test("gibbs color-slider page activates without uncaught page errors", { tag: "@both" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve("demos/experiments/gibbs");

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);

    // First timeline page: choose a participant group.
    await expect(experimentPage.locator(".push-button").first()).toBeVisible({
      timeout: STEP_TIMEOUT_MS
    });
    await experimentPage.locator(".push-button").first().click();

    // Reaching the color-slider trial page activates static/color-slider.js.
    // If it throws, the failOnPageErrors fixture fails this test at teardown.
    await expect(experimentPage.locator("#color-box")).toBeVisible({
      timeout: STEP_TIMEOUT_MS
    });

    // And the live-update hook (color-slider.js) must have taken effect: moving
    // the slider recolours the box. If the onSliderEvent assignment was lost,
    // the box colour never changes.
    const colorBox = experimentPage.locator("#color-box");
    const slider = experimentPage.locator("input.slider-range").first();
    await expect(slider).toBeVisible({ timeout: STEP_TIMEOUT_MS });

    const before = await colorBox.evaluate(
      (el) => getComputedStyle(el).backgroundColor
    );
    await slider.evaluate((el) => {
      el.value = String((Number(el.value) + 60) % 256);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await expect
      .poll(
        () => colorBox.evaluate((el) => getComputedStyle(el).backgroundColor),
        { timeout: STEP_TIMEOUT_MS }
      )
      .not.toBe(before);
  });
});

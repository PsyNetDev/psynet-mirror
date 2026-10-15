const path = require("path");
const { test, expect } = require("../fixtures");

const {
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;

// SurveyJS registers itself as a jQuery plugin on the head jQuery. A second
// jQuery (e.g. Dallinger's base-layout copy) would replace it and leave the
// survey blank, so check the plugin both after an in-place transition and
// after a full reload.
async function expectSurveyOnSingleJQuery(page, label) {
  await expect(page.locator("#surveyContainer .sd-question").first()).toBeVisible({
    timeout: STEP_TIMEOUT_MS
  });
  const state = await page.evaluate(() => ({
    jqueryScripts: [...document.querySelectorAll("script[src]")].filter((s) =>
      /\/jquery-\d[\d.]*(\.min)?\.js/.test(s.src)
    ).length,
    surveyPlugin: typeof window.jQuery?.fn?.Survey
  }));
  expect(state, label).toEqual({ jqueryScripts: 1, surveyPlugin: "function" });
}

test("survey_js demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/experiments/survey_js");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);

    await waitForMainBodyContains(experimentPage, "simple SurveyJS example", STEP_TIMEOUT_MS);
    await expectSurveyOnSingleJQuery(experimentPage, "after the transition from consent");

    await experimentPage.reload();
    await waitForMainBodyContains(experimentPage, "simple SurveyJS example", STEP_TIMEOUT_MS);
    await expectSurveyOnSingleJQuery(experimentPage, "after a full reload");

    const survey = experimentPage.locator("#surveyContainer");
    await survey.locator('[data-name="name"] input.sd-input').fill("Beatrix");
    await survey.locator("input.sd-navigation__next-btn").click();
    await survey.locator('[data-name="final_question"] input.sd-input').fill("Goodbye");
    await survey.locator("input.sd-navigation__complete-btn").click();

    await waitForMainBodyContains(experimentPage, "Answer", STEP_TIMEOUT_MS);
    await expect(experimentPage.locator("#main-body pre").first()).toContainText("Beatrix");
    await expect(experimentPage.locator("#main-body pre").first()).toContainText("Goodbye");
  });
});

const path = require("path");
const { test, expect } = require("../fixtures");

const {
  advanceUntilFinish,
  assertExpectedTimelinePathActive,
  clickNextAndWait,
  completeInitialGateway,
  startResponseSubmitTracker,
  waitForNextEnabled,
  waitForResponseSubmitIncrement,
  withExperiment
} = require("../psynetHarness");

const PROMPT_TIMEOUT_MS = 90000;
const STEP_TIMEOUT_MS = 120000;

async function expectPromptContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#prompt-text")).toContainText(text, { timeout });
}

async function expectMainBodyContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#main-body")).toContainText(text, { timeout });
}

async function answerSingleRating(page, value) {
  const question = page.locator(".sd-question").first();
  await expect(question).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });

  const ratingItems = question.locator(".sd-rating__item");
  if ((await ratingItems.count()) > 0) {
    const item = ratingItems.nth(value - 1);
    await expect(item).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
    await item.click();
    return;
  }

  const select = question.locator("select").first();
  if ((await select.count()) > 0) {
    await select.selectOption(String(value));
    return;
  }

  const dropdown = question.locator(".sd-dropdown, input[role='combobox']").first();
  if ((await dropdown.count()) > 0) {
    await dropdown.click();
    const option = page.locator(
      `.sv-popup:visible .sd-item__control-label:has-text("${value}"), ` +
        `.sv-popup:visible .sd-list__item:has-text("${value}"), ` +
        `.sv-popup:visible [role="option"]:has-text("${value}")`,
    ).first();
    await expect(option).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
    await option.click();
    return;
  }

  throw new Error("Could not find a supported single-rating input.");
}

async function answerMultiRating(page, answers) {
  const questions = page.locator(".sd-question");
  await expect(questions).toHaveCount(2, { timeout: PROMPT_TIMEOUT_MS });
  for (const [index, value] of answers.entries()) {
    const question = questions.nth(index);
    const ratingItems = question.locator(".sd-rating__item");
    if ((await ratingItems.count()) > 0) {
      await ratingItems.nth(value - 1).click();
      continue;
    }

    const select = question.locator("select").first();
    if ((await select.count()) > 0) {
      await select.selectOption(String(value));
      continue;
    }

    const dropdown = question.locator(".sd-dropdown, input[role='combobox']").first();
    if ((await dropdown.count()) > 0) {
      await dropdown.click();
      const option = page.locator(
        `.sv-popup:visible .sd-item__control-label:has-text("${value}"), ` +
          `.sv-popup:visible .sd-list__item:has-text("${value}"), ` +
          `.sv-popup:visible [role="option"]:has-text("${value}")`,
      ).first();
      await expect(option).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
      await option.click();
      continue;
    }

    throw new Error(`Could not find a supported rating input for question ${index}.`);
  }
}

async function nudgeSlider(page, selector) {
  const slider = page.locator(selector);
  await expect(slider).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
  const changeResult = await slider.evaluate((element) => {
    const before = Number(element.value);
    const min = Number(element.min);
    const max = Number(element.max);
    const candidates = [min, max].filter(
      (candidate) => Number.isFinite(candidate) && candidate !== before
    );

    for (const candidate of candidates) {
      element.value = String(candidate);
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      const after = Number(element.value);
      if (after !== before) {
        return { before, after };
      }
    }

    return null;
  });

  if (!changeResult) {
    throw new Error(`Could not change slider value for ${selector}.`);
  }
}

test("modular_page feature demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/features/modular_page");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    const submitTracker = startResponseSubmitTracker(experimentPage);
    try {
      await completeInitialGateway(experimentPage);
      await assertExpectedTimelinePathActive(experimentPage, 20000);

      await expectMainBodyContains(
        experimentPage,
        "simple text page",
        PROMPT_TIMEOUT_MS
      );
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectMainBodyContains(
        experimentPage,
        "simple formatting",
        PROMPT_TIMEOUT_MS
      );
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "RatingControl",
        PROMPT_TIMEOUT_MS
      );
      await answerSingleRating(experimentPage, 3);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectMainBodyContains(experimentPage, "Page type", PROMPT_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "MultiRatingControl",
        PROMPT_TIMEOUT_MS
      );
      await answerMultiRating(experimentPage, [4, 5]);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectMainBodyContains(experimentPage, "Metadata", PROMPT_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "audio prompt combined with a push button control",
        PROMPT_TIMEOUT_MS
      );
      await expect(experimentPage.locator(".push-button").first()).toBeVisible({
        timeout: PROMPT_TIMEOUT_MS
      });
      await experimentPage.locator(".push-button").first().click();
      await expectMainBodyContains(experimentPage, "Page type", STEP_TIMEOUT_MS);

      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "timed push button control",
        PROMPT_TIMEOUT_MS
      );
      await experimentPage.locator(".push-button").nth(1).click();
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectMainBodyContains(experimentPage, "Answer", PROMPT_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "frame slider",
        PROMPT_TIMEOUT_MS
      );
      await waitForNextEnabled(experimentPage, STEP_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectMainBodyContains(experimentPage, "Metadata", PROMPT_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "video slider page",
        PROMPT_TIMEOUT_MS
      );
      await expect(experimentPage.locator("#sliderpage_slider")).toBeEnabled({
        timeout: STEP_TIMEOUT_MS
      });
      await nudgeSlider(experimentPage, "#sliderpage_slider");
      await waitForNextEnabled(experimentPage, STEP_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectMainBodyContains(experimentPage, "Answer", PROMPT_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(experimentPage, "adds 'Hello'", PROMPT_TIMEOUT_MS);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await expectPromptContains(
        experimentPage,
        "custom control interface",
        PROMPT_TIMEOUT_MS
      );
      const customText = "P4 override survives page N and stops at page N+1.";
      await experimentPage.locator("#text-input").fill(customText);
      const overrideSubmitBaseline = submitTracker.getCount();
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await waitForResponseSubmitIncrement(
        submitTracker,
        overrideSubmitBaseline,
        1,
        STEP_TIMEOUT_MS
      );

      await expectMainBodyContains(experimentPage, "Page type", PROMPT_TIMEOUT_MS);
      await expectMainBodyContains(experimentPage, customText, PROMPT_TIMEOUT_MS);
      await expectMainBodyContains(
        experimentPage,
        "aquamarine",
        PROMPT_TIMEOUT_MS
      );
      await expect
        .poll(
          () =>
            experimentPage.evaluate(() =>
              window.psynet?.stageResponse === null
                ? "null"
                : typeof window.psynet?.stageResponse
            ),
          { timeout: 10000 }
        )
        .toMatch(/^(null|undefined)$/);

      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
      await advanceUntilFinish(experimentPage, { timeoutMs: STEP_TIMEOUT_MS });
    } finally {
      submitTracker.stop();
    }
  });
});

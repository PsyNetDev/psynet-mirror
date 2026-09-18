const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertExpectedTimelinePathActive,
  clickFinish,
  clickNextAndWait,
  completeInitialGateway,
  captureTrialEventBaseline,
  startResponseSubmitTracker,
  waitForResponseSubmitIncrement,
  waitForTrialEvents,
  waitForNextEnabled,
  withExperiment
} = require("../psynetHarness");

const PROMPT_TIMEOUT_MS = 90000;
const STEP_TIMEOUT_MS = 120000;

/*
Step summary:
1. Intro gateway and overview:
   participant clears the entry page, sees the graphics intro, and enters the demo sequence.
2. GraphicPrompt primitives:
   participant sees path/circle/ellipse/rectangle rendering on the geometric objects page.
3. GraphicControl click selection:
   participant clicks interactive graphics, submits answers, and sees debug output with click coordinates.
4. Synchronized audio graphics:
   participant visits the graphic prompt with timed audio and proceeds once playback has started.
5. Typography comparison:
   participant views the big/small text rendering page and continues.
6. Mixed prompt+control page:
   participant answers by clicking one of the graphic text options and submits.
7. Recorder setup page:
   participant enables microphone flow via the audio meter setup step.
8. Graphic-timed recording page:
   participant reaches the countdown/sing/stop flow, completes recording, and submits recorded audio.
9. Finish page:
   participant clicks Finish and exits through the recruiter redirect.

Intentionally not covered:
- Full animation path validation over time for each SVG element.
- Exact audio content produced by user/bot recording.
*/

async function clickUiAndWaitForPageChange(page, locator, timeoutMs = 60000) {
  const oldUuid = await page.evaluate(() => window.pageUuid || null);
  await expect(locator).toHaveCount(1, { timeout: PROMPT_TIMEOUT_MS });
  await expect(locator).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
  await locator.click();
  await page.waitForFunction(
    (uuid) => window.pageUuid && window.pageUuid !== uuid,
    oldUuid,
    { timeout: timeoutMs }
  );
}

function extractClickCoordinates(debugText) {
  const match = debugText.match(
    /'click_coordinates':\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]/
  );
  expect(match).not.toBeNull();
  return [Number(match[1]), Number(match[2])];
}

async function expectPromptContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#prompt-text")).toContainText(text, { timeout });
}

async function expectMainBodyContains(page, text, timeout = PROMPT_TIMEOUT_MS) {
  await expect(page.locator("#main-body")).toContainText(text, { timeout });
}

async function waitForAnyAudioStartSignal(page, timeout = PROMPT_TIMEOUT_MS) {
  await expect
    .poll(
      () => page.evaluate(() => (psynet?.media?.sounds || []).length),
      { timeout }
    )
    .toBeGreaterThan(0);
}

async function getStagedAudioRecordingInfo(page) {
  return page.evaluate(() => {
    const blob = psynet?.response?.staged?.blobs?.audioRecording || null;
    if (!blob) {
      return { exists: false, size: 0, type: null };
    }
    return {
      exists: true,
      size: typeof blob.size === "number" ? blob.size : 0,
      type: typeof blob.type === "string" ? blob.type : null
    };
  });
}

async function getGraphicAttribute(locator, attribute) {
  return locator.first().evaluate((el, attr) => {
    const raw = el.getAttribute(attr);
    const num = Number.parseFloat(raw ?? "");
    return Number.isFinite(num) ? num : raw;
  }, attribute);
}

async function expectAtLeastOne(page, selector, timeout = PROMPT_TIMEOUT_MS) {
  await expect
    .poll(() => page.locator(selector).count(), { timeout })
    .toBeGreaterThan(0);
}

async function expectResponseSubmitCount(tracker, expectedCount, timeout = 3000) {
  await expect.poll(() => tracker.getCount(), { timeout }).toBe(expectedCount);
}

async function getRenderedTextHeight(locator) {
  return locator.first().evaluate((el) => {
    const bboxHeight =
      typeof el.getBBox === "function" ? Number(el.getBBox().height) : NaN;
    if (Number.isFinite(bboxHeight) && bboxHeight > 0) {
      return bboxHeight;
    }

    const computedFontSize = Number.parseFloat(getComputedStyle(el).fontSize);
    if (Number.isFinite(computedFontSize) && computedFontSize > 0) {
      return computedFontSize;
    }

    const attrFontSize = Number.parseFloat(el.getAttribute("font-size") || "");
    if (Number.isFinite(attrFontSize) && attrFontSize > 0) {
      return attrFontSize;
    }

    return NaN;
  });
}

test("graphics demo", { tag: "@both" }, async ({ page, context }) => {
  const absDir = path.resolve("demos/experiments/graphics");
  await withExperiment(page, context, absDir, async (experimentPage) => {
    const submitTracker = startResponseSubmitTracker(experimentPage);
    try {
    // Section 0: complete deterministic gateway step.
    await completeInitialGateway(experimentPage);
    await assertExpectedTimelinePathActive(experimentPage, 20000);

    // Section 1: smoke-check intro page and move into graphics-specific pages.
    await expectMainBodyContains(experimentPage, "Graphic components");
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 2: verify core GraphicPrompt rendering (shape primitives from Python timeline).
    await expectPromptContains(experimentPage, "different kinds of geometric objects");
    await expectAtLeastOne(experimentPage, "#main-body svg path");
    await expectAtLeastOne(experimentPage, "#main-body svg circle");
    await expectAtLeastOne(experimentPage, "#main-body svg ellipse");
    await expectAtLeastOne(experimentPage, "#main-body svg rect");
    const animatedCircle = experimentPage.locator("#main-body svg circle").first();
    const circleCx = await getGraphicAttribute(animatedCircle, "cx");
    expect(circleCx).not.toBeNull();
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 3: verify GraphicControl click path through real UI and persisted server answer.
    await expectPromptContains(experimentPage, "Click on one of the objects");
    await expectAtLeastOne(experimentPage, "#main-body svg image");
    const titleGraphic = experimentPage.locator("#main-body svg text").filter({
      hasText: "PsyNet is great!"
    });
    const firstClickBaselineResponses = submitTracker.getCount();
    await clickUiAndWaitForPageChange(experimentPage, titleGraphic);
    await waitForResponseSubmitIncrement(
      submitTracker,
      firstClickBaselineResponses,
      1,
      STEP_TIMEOUT_MS
    );
    await expectResponseSubmitCount(submitTracker, firstClickBaselineResponses + 1);

    const firstDebugAnswer = await experimentPage.locator("#main-body").innerText();
    await expect(experimentPage.locator("#main-body")).toContainText("'clicked_object': 'title'");
    await expect(experimentPage.locator("#main-body svg")).toHaveCount(0);
    const [firstX, firstY] = extractClickCoordinates(firstDebugAnswer);
    expect(firstX).toBeGreaterThan(0);
    expect(firstY).toBeGreaterThan(0);
    expect(firstX).toBeLessThanOrEqual(100);
    expect(firstY).toBeLessThanOrEqual(100);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 4: verify synchronized-audio graphics page starts expected stimulus without controls.
    await expectPromptContains(experimentPage, "synchronized audio");
    await expect(experimentPage.locator("#audio-prompt-controls")).toHaveCount(0);
    await waitForAnyAudioStartSignal(experimentPage, 30000);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 5: verify font-size rendering differences survive frontend pipeline.
    await expectPromptContains(experimentPage, "different font sizes");
    const bigText = experimentPage.locator("#main-body svg text").filter({
      hasText: "Big text"
    });
    const smallText = experimentPage.locator("#main-body svg text").filter({
      hasText: "Small text"
    });
    await expect(bigText).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
    await expect(smallText).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
    const [bigTextHeight, smallTextHeight] = await Promise.all([
      getRenderedTextHeight(bigText),
      getRenderedTextHeight(smallText)
    ]);
    expect(Number.isFinite(bigTextHeight)).toBe(true);
    expect(Number.isFinite(smallTextHeight)).toBe(true);
    expect(bigTextHeight).toBeGreaterThan(smallTextHeight);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 6: verify mixed GraphicPrompt + GraphicControl page and chosen-answer integrity.
    await expectPromptContains(experimentPage, "both a GraphicPrompt and a GraphicControl");
    await expect(
      experimentPage
        .locator("#main-body svg text")
        .filter({ hasText: "What's up? Click to answer." })
    ).toBeVisible({ timeout: PROMPT_TIMEOUT_MS });
    const lotsGraphic = experimentPage.locator("#main-body svg text").filter({
      hasText: "Lots."
    });
    const secondClickBaselineResponses = submitTracker.getCount();
    await clickUiAndWaitForPageChange(experimentPage, lotsGraphic);
    await waitForResponseSubmitIncrement(
      submitTracker,
      secondClickBaselineResponses,
      1,
      STEP_TIMEOUT_MS
    );
    await expectResponseSubmitCount(submitTracker, secondClickBaselineResponses + 1);

    const secondDebugAnswer = await experimentPage.locator("#main-body").innerText();
    await expect(experimentPage.locator("#main-body")).toContainText(
      "'clicked_object': 'lots'"
    );
    await expect(experimentPage.locator("#main-body svg")).toHaveCount(0);
    const [secondX, secondY] = extractClickCoordinates(secondDebugAnswer);
    expect(secondX).toBeGreaterThan(0);
    expect(secondY).toBeGreaterThan(0);
    expect(secondX).toBeLessThanOrEqual(300);
    expect(secondY).toBeLessThanOrEqual(100);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 7: verify transition into recorder setup still renders expected UI components.
    await expectMainBodyContains(experimentPage, "enable your sound recorder");
    await expect(experimentPage.locator("#audio-meter")).toBeVisible();
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    // Section 8: verify graphic-timed recording flow enables response, records, and exposes playback.
    await expectPromptContains(
      experimentPage,
      "trigger timing in the Control object"
    );
    const graphicsRecordBaselineResponses = submitTracker.getCount();
    const graphicsRecordEventBaseline = await captureTrialEventBaseline(
      experimentPage
    );
    await expect(experimentPage.locator("#btn-record-record")).toHaveCount(0);
    await waitForNextEnabled(experimentPage, 45000);
    await waitForTrialEvents(experimentPage, ["recordStart", "recordEnd"], {
      timeoutMs: 45000,
      baselineIndex: graphicsRecordEventBaseline
    });
    const recordedAudio = await getStagedAudioRecordingInfo(experimentPage);
    expect(recordedAudio.exists).toBe(true);
    expect(recordedAudio.size).toBeGreaterThan(0);
    if (recordedAudio.type) {
      expect(recordedAudio.type).toContain("audio");
    }
    await expect(experimentPage.locator("#next-button")).toBeEnabled({
      timeout: STEP_TIMEOUT_MS
    });
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForResponseSubmitIncrement(
      submitTracker,
      graphicsRecordBaselineResponses,
      1,
      STEP_TIMEOUT_MS
    );

    // Section 9: verify normal experiment termination route remains intact after assertions above.
    const finishButton = experimentPage.locator("#Finish");
    await expect(finishButton).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await clickFinish(experimentPage, STEP_TIMEOUT_MS);
    } finally {
      submitTracker.stop();
    }
  });
});

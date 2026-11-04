const path = require("path");
const { test, expect } = require("../fixtures");

const {
  assertExpectedTimelinePathActive,
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  waitForPromptContains,
  withExperiment
} = require("../psynetHarness");

const STEP_TIMEOUT_MS = 120000;
const PLAYBACK_TIMEOUT_MS = 30000;

test("slider page module activates", { tag: "@both" }, async ({ page, context }) => {
  await withExperiment(
    page,
    context,
    path.resolve("demos/features/slider"),
    async (experimentPage) => {
      await completeInitialGateway(experimentPage);
      await assertExpectedTimelinePathActive(experimentPage, 20000);
      await expect(experimentPage.locator("input.slider-range")).toBeVisible({
        timeout: STEP_TIMEOUT_MS
      });
      await expect(
        experimentPage.locator("#slider-output-value")
      ).not.toHaveText("NA", { timeout: STEP_TIMEOUT_MS });
      await assertNoBackendError(experimentPage);
    }
  );
});

async function moveSliderOnceMediaLoaded(page, mediaType, mediaId, value) {
  await expect
    .poll(() => page.evaluate(([type, id]) => !!psynet[type]?.[id], [mediaType, mediaId]), {
      timeout: STEP_TIMEOUT_MS
    })
    .toBe(true);
  const slider = page.locator("input.slider-range");
  await expect(slider).toBeEnabled({ timeout: STEP_TIMEOUT_MS });
  // The change handler starts playback synchronously, so read the active
  // PsyNet sounds before short clips can finish.
  return slider.evaluate((el, v) => {
    el.value = String(v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return psynet.media.sounds.map((sound) => sound.stimulusId);
  }, value);
}

test("generic MediaSliderControl plays video and audio when the slider moves", { tag: "@both" }, async ({
  page,
  context
}) => {
  await withExperiment(
    page,
    context,
    path.resolve("demos/features/simple_multimedia_slider"),
    async (experimentPage) => {
      await completeInitialGateway(experimentPage);

      // Video page: moving to location 5 shows and plays video_5.
      await waitForPromptContains(experimentPage, "Simple video example");
      await moveSliderOnceMediaLoaded(experimentPage, "video", "video_5", 5);
      await expect
        .poll(
          () =>
            experimentPage.evaluate(() => {
              const video = psynet.video.video_5.player;
              return video.style.display === "block" && !video.paused && video.currentTime > 0;
            }),
          { timeout: PLAYBACK_TIMEOUT_MS }
        )
        .toBe(true);

      await clickNextAndWait(experimentPage);
      await clickNextAndWait(experimentPage);

      // Audio page: moving to location 100 starts audio_100 as a PsyNet sound.
      await waitForPromptContains(experimentPage, "Same example but for audio");
      const activeSounds = await moveSliderOnceMediaLoaded(
        experimentPage,
        "audio",
        "audio_100",
        100
      );
      expect(activeSounds).toContain("audio_100");
      await assertNoBackendError(experimentPage);
    }
  );
});

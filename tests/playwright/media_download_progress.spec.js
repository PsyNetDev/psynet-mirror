const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertInplaceTimelinePathActive,
  clickNextAndWait,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

async function assertMediaDownloadProgressBarVisible(page) {
  const bar = page.locator("#media-download-progress-bar");
  await expect(bar).toBeVisible({ timeout: STEP_TIMEOUT_MS });

  const metrics = await page.evaluate(() => {
    const el = document.getElementById("media-download-progress-bar");
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return {
      inFooter: !!el.closest("#footer"),
      height: rect.height,
      width: rect.width,
      display: style.display,
      visibility: style.visibility,
      opacity: Number(style.opacity)
    };
  });

  expect(metrics.inFooter).toBe(true);
  expect(metrics.height).toBeGreaterThan(0);
  expect(metrics.width).toBeGreaterThan(0);
  expect(metrics.display).not.toBe("none");
  expect(metrics.visibility).not.toBe("hidden");
  expect(metrics.opacity).toBeGreaterThan(0);
}

async function waitForMediaDownloadComplete(page) {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const el = document.getElementById("media-download-progress-bar");
          const button = document.querySelector(".wait-for-media-load");
          return {
            widthPct: el?.style.width || null,
            buttonsEnabled: !!button && !button.hasAttribute("disabled")
          };
        }),
      { timeout: STEP_TIMEOUT_MS }
    )
    .toMatchObject({
      widthPct: "100%",
      buttonsEnabled: true
    });
}

test("media download progress bar displays on full load and inplace transition", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/media_download_progress"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);
    await waitForMainBodyContains(experimentPage, "Intro without media", STEP_TIMEOUT_MS);

    // Footer/bar should exist even before media pages.
    await assertMediaDownloadProgressBarVisible(experimentPage);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "First media page", STEP_TIMEOUT_MS);
    await assertMediaDownloadProgressBarVisible(experimentPage);
    await waitForMediaDownloadComplete(experimentPage);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "Second media page", STEP_TIMEOUT_MS);
    await assertMediaDownloadProgressBarVisible(experimentPage);
    await waitForMediaDownloadComplete(experimentPage);
  });
});

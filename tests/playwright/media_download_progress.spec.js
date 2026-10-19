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

async function assertMediaDownloadProgressBarVisible(page, expectedFooter) {
  const bar = page.locator("#media-download-progress-bar");
  await expect(bar).toBeVisible({ timeout: STEP_TIMEOUT_MS });

  const metrics = await page.evaluate(() => {
    const el = document.getElementById("media-download-progress-bar");
    const footer = document.getElementById("footer");
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return {
      inFooter: !!el.closest("#footer"),
      hasFooter: !!footer,
      atFooterTop:
        !footer ||
        Math.abs(
          rect.top -
            footer.getBoundingClientRect().top -
            parseFloat(getComputedStyle(footer).borderTopWidth)
        ) <= 1,
      atWindowBottom: Math.round(rect.bottom) === window.innerHeight,
      height: rect.height,
      width: rect.width,
      position: style.position,
      display: style.display,
      visibility: style.visibility,
      opacity: Number(style.opacity)
    };
  });

  // The bar rides the footer's top edge when there is a footer, and the bottom
  // edge of the window when there is not (rewards hidden, no footer buttons).
  if (metrics.hasFooter) {
    expect(metrics.inFooter).toBe(true);
    expect(metrics.atFooterTop).toBe(true);
    expect(metrics.position).toBe("absolute");
  } else {
    expect(metrics.atWindowBottom).toBe(true);
    expect(metrics.position).toBe("fixed");
  }
  expect(metrics.hasFooter).toBe(expectedFooter);
  expect(metrics.height).toBeGreaterThan(0);
  expect(metrics.width).toBeGreaterThan(0);
  expect(metrics.display).not.toBe("none");
  expect(metrics.visibility).not.toBe("hidden");
  expect(metrics.opacity).toBeGreaterThan(0);
}

async function assertMediaDownloadProgressBarAbsent(page) {
  await expect(page.locator("#media-download-progress-bar")).toHaveCount(0);
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
    await assertMediaDownloadProgressBarAbsent(experimentPage);
    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

    await waitForMainBodyContains(
      experimentPage,
      "We need your consent to proceed",
      STEP_TIMEOUT_MS
    );
    await experimentPage.setViewportSize({ width: 1280, height: 720 });
    const consentFooterIsBelowFold = await experimentPage.evaluate(() => {
      const footer = document.getElementById("footer");
      return footer.getBoundingClientRect().top >= window.innerHeight;
    });
    expect(consentFooterIsBelowFold).toBe(true);
    await assertMediaDownloadProgressBarVisible(experimentPage, true);
    await experimentPage.locator("#consent").click();

    await waitForMainBodyContains(experimentPage, "First media page", STEP_TIMEOUT_MS);
    // The first media page adds a termination button, moving the live bar
    // into the newly inserted footer before download progress reaches 100%.
    await assertMediaDownloadProgressBarVisible(experimentPage, true);
    await waitForMediaDownloadComplete(experimentPage);

    // Leave is the destructive action on the left; the passive Cancel action
    // on the right closes the confirmation without replacing the trial.
    const urlBeforeExit = experimentPage.url();
    await experimentPage.locator("#early-exit-button").click();
    await expect(experimentPage.locator("#early-exit-modal")).toBeVisible();
    await expect(experimentPage.locator("#early-exit-title")).toHaveText(
      "Leave without finishing?"
    );
    const actions = await experimentPage.evaluate(() => {
      const confirm = document.getElementById("early-exit-confirm");
      const cancel = document.getElementById("early-exit-cancel");
      const modal = document.querySelector("#early-exit-modal .modal-content");
      return {
        confirmLabel: confirm.textContent.trim(),
        cancelLabel: cancel.textContent.trim(),
        confirmLeft: confirm.getBoundingClientRect().left,
        cancelLeft: cancel.getBoundingClientRect().left,
        cancelBackground: getComputedStyle(cancel).backgroundColor,
        modalBackground: getComputedStyle(modal).backgroundColor
      };
    });
    expect(actions.confirmLabel).toBe("Leave");
    expect(actions.cancelLabel).toBe("Cancel");
    expect(actions.confirmLeft).toBeLessThan(actions.cancelLeft);
    expect(actions.cancelBackground).toBe(actions.modalBackground);
    await experimentPage.locator("#early-exit-cancel").click();
    await expect(experimentPage.locator("#early-exit-modal")).toBeHidden();
    await expect(experimentPage.locator("#main-body")).toContainText(
      "First media page"
    );
    expect(experimentPage.url()).toBe(urlBeforeExit);

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(experimentPage, "Second media page", STEP_TIMEOUT_MS);
    // The second removes the footer again. Its cached audio can complete before
    // this assertion, so assert durable lifecycle state rather than transient
    // visibility: one standalone bar reaches 100% and then hides.
    const standaloneBar = experimentPage.locator("#media-download-progress-bar");
    await expect(standaloneBar).toHaveCount(1);
    expect(
      await standaloneBar.evaluate((bar) => bar.closest("#footer") === null)
    ).toBe(true);
    await waitForMediaDownloadComplete(experimentPage);
    await expect(standaloneBar).toBeHidden();
  });
});

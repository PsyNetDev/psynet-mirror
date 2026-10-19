const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertInplaceTimelinePathActive,
  assertNoBackendError,
  completeInitialGateway,
  waitForMainBodyContains,
  waitForPageChange,
  waitForTimelinePageReady,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

async function dispatchWindowClick(page) {
  await page.evaluate(() => {
    window.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function nextPageFromBrowser(page, answer = null) {
  const oldUuid = await page.evaluate(() => window.pageUuid || null);
  const result = await page.evaluate((rawAnswer) => window.psynet.nextPage(rawAnswer), answer);
  if (result) {
    await waitForPageChange(page, oldUuid, STEP_TIMEOUT_MS);
    await waitForTimelinePageReady(page, STEP_TIMEOUT_MS);
  }
  return result;
}

test("adversarial lifecycle handles rejection retry and page listener cleanup", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  const absDir = path.resolve(
    "tests/playwright/experiments/adversarial_lifecycle"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);

    // Rejected responses should leave the page active and unlock submission state.
    await waitForMainBodyContains(
      experimentPage,
      "Rejection retry page",
      STEP_TIMEOUT_MS
    );

    const rejected = await nextPageFromBrowser(experimentPage, "rejected");
    expect(rejected).toBe(false);
    await expect(experimentPage.locator("#alert-message")).toContainText(
      "Please submit the accepted answer.",
      { timeout: STEP_TIMEOUT_MS }
    );
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() => ({
            nextPagePending: window.psynet.nextPagePending,
            stillOnRejectionPage: Boolean(
              document.getElementById("adversarial-rejection-page")
            )
          })),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toEqual({
        nextPagePending: false,
        stillOnRejectionPage: true
      });
    await experimentPage.locator("#alert-button").click();

    const accepted = await nextPageFromBrowser(experimentPage, "accepted");
    expect(accepted).toBe(true);

    // Once the SPA transition reaches the checkpoint page, page-scoped timers
    // from the previous page must no longer keep ticking or trigger stale navigation.
    await waitForMainBodyContains(experimentPage, "Tracked timer page", STEP_TIMEOUT_MS);
    await experimentPage.evaluate(() => window.__scheduleTrackedLifecycleTimers());
    expect(await nextPageFromBrowser(experimentPage, "manual-timer-advance")).toBe(true);
    await waitForMainBodyContains(
      experimentPage,
      "Timer cleanup checkpoint",
      STEP_TIMEOUT_MS
    );
    const ticksAfterTransition = await experimentPage.evaluate(
      () => window.__trackedTimerLifecycle.intervalTicks
    );
    await experimentPage.waitForTimeout(1200);
    await expect(experimentPage.locator("#main-body")).toContainText(
      "Timer cleanup checkpoint"
    );
    const lifecycleAfterWait = await experimentPage.evaluate(
      () => window.__trackedTimerLifecycle
    );
    expect(lifecycleAfterWait.started).toBe(true);
    expect(lifecycleAfterWait.intervalTicks).toBe(ticksAfterTransition);

    // Audio cleanup must settle even if the source ends before its stop timer.
    expect(await nextPageFromBrowser(experimentPage)).toBe(true);
    await waitForMainBodyContains(experimentPage, "Audio fade-out page", STEP_TIMEOUT_MS);
    await expect
      .poll(
        () =>
          experimentPage.evaluate(
            () => window.__audioFadeOutLifecycle?.ready === true
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);
    const stopSettled = await experimentPage.evaluate(async () => {
      const sound = window.psynet.media.sounds.find(
        (candidate) => candidate.stimulusId === "fadeout_stale_audio"
      );
      const stopping = window.psynet.media.stopAllAudio({ fadeOut: 0 });
      sound.source.dispatchEvent(new Event("ended"));
      return Promise.race([
        stopping.then(() => true),
        new Promise((resolve) => setTimeout(() => resolve(false), 1000))
      ]);
    });
    expect(stopSettled).toBe(true);

    // Audio stopped during a transition must not report completion on the next
    // trial, even if the original sound was in a fade-out window.
    await experimentPage.evaluate(() => {
      window.psynet.audio.fadeout_stale_audio.play({
        fadeOut: 0.3,
        gain: 0.001
      });
    });
    expect(await nextPageFromBrowser(experimentPage, "advance-during-audio")).toBe(
      true
    );
    await waitForMainBodyContains(
      experimentPage,
      "Audio fade-out checkpoint",
      STEP_TIMEOUT_MS
    );
    await experimentPage.waitForTimeout(500);
    await expect
      .poll(() =>
        experimentPage.evaluate(() =>
          window.psynet.trial.eventLog.some(
            (event) => event.eventType === "audioFinished: fadeout_stale_audio"
          )
        )
      )
      .toBe(false);

    // Manual stop intent must win even when it overlaps an already pending
    // automatic stop, otherwise a looping sound can restart during cleanup.
    expect(await nextPageFromBrowser(experimentPage)).toBe(true);
    await waitForMainBodyContains(
      experimentPage,
      "Overlapping audio stop page",
      STEP_TIMEOUT_MS
    );
    await expect
      .poll(
        () =>
          experimentPage.evaluate(
            () => window.__overlappingAudioStopLifecycle?.ready === true
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);
    await expect
      .poll(
        () =>
          experimentPage.evaluate(() =>
            window.__runOverlappingAudioStopRegression()
          ),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toBe(true);

    // Page-scoped event listeners should work while their page is active.
    expect(await nextPageFromBrowser(experimentPage)).toBe(true);
    await waitForMainBodyContains(experimentPage, "Listener page first", STEP_TIMEOUT_MS);

    await dispatchWindowClick(experimentPage);
    await expect
      .poll(
        () => experimentPage.evaluate(() => window.__adversarialLifecycle),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        listenerClicks: 1,
        cleanupCalls: 0,
        activations: ["first"]
      });

    // The listener from the previous page should be removed during cleanup.
    expect(await nextPageFromBrowser(experimentPage)).toBe(true);
    await waitForMainBodyContains(
      experimentPage,
      "Listener cleanup checkpoint",
      STEP_TIMEOUT_MS
    );
    await dispatchWindowClick(experimentPage);
    await expect
      .poll(
        () => experimentPage.evaluate(() => window.__adversarialLifecycle),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        listenerClicks: 1,
        cleanupCalls: 1,
        activations: ["first"]
      });

    // A later page can register its own listener without reviving the old one.
    expect(await nextPageFromBrowser(experimentPage)).toBe(true);
    await waitForMainBodyContains(experimentPage, "Listener page second", STEP_TIMEOUT_MS);
    await dispatchWindowClick(experimentPage);
    await expect
      .poll(
        () => experimentPage.evaluate(() => window.__adversarialLifecycle),
        { timeout: STEP_TIMEOUT_MS }
      )
      .toMatchObject({
        listenerClicks: 2,
        cleanupCalls: 1,
        activations: ["first", "second"]
      });
    await assertNoBackendError(experimentPage);
  });
});

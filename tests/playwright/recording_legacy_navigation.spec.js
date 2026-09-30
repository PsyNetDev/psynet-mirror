const path = require("path");
const { test, expect } = require("./fixtures");
const {
  withExperiment, completeInitialGateway, waitForVideoRecordingReady,
  waitForNextEnabled,
} = require("./psynetHarness");

test("legacy navigation preserves an answer when document-owned video is lost @legacy-only", async ({page, context}) => {
  test.setTimeout(150000);
  let accepted;
  await context.route("**/response", async route => {
    if (route.request().postData()?.includes("recording_recovery_secret")) {
      // Capture durable acceptance before navigation discards Chromium's body cache.
      const response = await route.fetch();
      accepted = await response.json();
      await route.fulfill({response});
    } else await route.continue();
  });
  // Never deliver bytes: full document navigation is allowed to abandon this queue.
  await context.route("**/media-upload/*", () => {});
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
    await completeInitialGateway(p);
    await expect(p.locator("#main-body")).toContainText("Record a short clip.");
    expect(await p.evaluate(() => window.psynetTemplateData.flags.inplaceTimelineTransitions)).toBe(false);
    await waitForVideoRecordingReady(p, {timeoutMs:45000});
    await waitForNextEnabled(p,30000);
    await p.evaluate(() => { window.recordingDocumentMarker = true; });
    await p.locator("#next-button").click();
    await expect(p.locator("#main-body")).toContainText("Independent page reached.", {timeout:10000});
    expect(accepted.submission).toBe("approved");
    const id = accepted.recording_uploads[0].id;
    expect(await p.evaluate(() => window.recordingDocumentMarker)).toBeUndefined();
    await waitForNextEnabled(p,30000);
    await p.locator("#next-button").click();
    await expect(p.locator("#main-body")).toContainText("Recording unavailable. Your answer was saved.", {timeout:90000});
    await expect(p.locator("video#prompt")).toHaveCount(0);
    const state = await (await context.request.get(new URL(`/test-recording-state/${id}`, p.url()).href)).json();
    expect(state.status).toBe("expired");
    expect(state.participant_failed).toBe(false);
    await waitForNextEnabled(p,30000);
    await p.locator("#next-button").click();
    await expect(p.locator("#Finish")).toBeVisible();
  });
});

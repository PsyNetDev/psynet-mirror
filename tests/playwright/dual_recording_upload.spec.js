const path = require("path");
const { test, expect } = require("./fixtures");
const {
  withExperiment, completeInitialGateway, waitForVideoRecordingReady,
  waitForNextEnabled,
} = require("./psynetHarness");

for (const missingScreen of [false, true]) {
  test(`camera and screen uploads resolve independently (missing screen: ${missingScreen}) @inplace-only`, async ({page, context}) => {
    test.setTimeout(150000);
    const held = new Map();
    await context.route("**/media-upload/*", route => {
      held.set(new URL(route.request().url()).pathname, route);
    });
    const previous = process.env.PSYNET_TEST_RECORDING_DUAL;
    process.env.PSYNET_TEST_RECORDING_DUAL = "1";
    try {
      await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
        await completeInitialGateway(p);
        await expect(p.locator("#main-body")).toContainText("Record a short clip.");
        await waitForVideoRecordingReady(p, {timeoutMs:45000, requireScreen:true});
        await waitForNextEnabled(p,30000);
        const response = p.waitForResponse(r => new URL(r.url()).pathname === "/response" && r.request().method() === "POST");
        await p.locator("#next-button").click();
        const accepted = await (await response).json();
        expect(accepted.recording_uploads.map(upload => upload.source).sort()).toEqual(["camera", "screen"]);
        await expect(p.locator("#main-body")).toContainText("Independent page reached.");
        await expect.poll(() => held.size).toBe(2);
        for (const upload of accepted.recording_uploads) {
          const route = held.get(upload.url);
          expect(route.request().postDataBuffer().length).toBeGreaterThan(0);
          if (missingScreen && upload.source === "screen") {
            await route.fulfill({status:403, body:"Upload unavailable"});
          } else {
            await route.continue();
          }
        }
        await waitForNextEnabled(p,30000);
        await p.locator("#next-button").click();
        await expect(p.locator("#main-body")).toContainText("Uploaded camera clip.", {timeout:45000});
        const video = p.locator("video#prompt");
        await expect.poll(() => video.evaluate(el => el.readyState >= 2 && el.duration > 0)).toBe(true);
        await video.evaluate(el => el.play());
        await expect.poll(() => video.evaluate(el => el.currentTime > 0)).toBe(true);
        await waitForNextEnabled(p,30000);
        await p.locator("#next-button").click();
        if (missingScreen) {
          await expect(p.locator("#main-body")).toContainText("Screen recording unavailable. Your answer was saved.", {timeout:90000});
          await expect(video).toHaveCount(0);
        } else {
          await expect(p.locator("#main-body")).toContainText("Uploaded screen clip.", {timeout:45000});
          await expect.poll(() => video.evaluate(el => el.readyState >= 2 && el.duration > 0)).toBe(true);
          await video.evaluate(el => el.play());
          await expect.poll(() => video.evaluate(el => el.currentTime > 0)).toBe(true);
        }
        for (const upload of accepted.recording_uploads) {
          const state = await (await context.request.get(new URL(`/test-recording-state/${upload.id}`, p.url()).href)).json();
          expect(state.status).toBe(missingScreen && upload.source === "screen" ? "expired" : "deposited");
          expect(state.participant_failed).toBe(false);
        }
        await waitForNextEnabled(p,30000);
        await p.locator("#next-button").click();
        await expect(p.locator("#Finish")).toBeVisible();
      });
    } finally {
      if (previous === undefined) delete process.env.PSYNET_TEST_RECORDING_DUAL;
      else process.env.PSYNET_TEST_RECORDING_DUAL = previous;
    }
  });
}

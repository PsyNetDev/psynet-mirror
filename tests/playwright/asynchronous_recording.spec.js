const path = require("path");
const { test, expect } = require("./fixtures");
const {
  withExperiment, completeInitialGateway, waitForVideoRecordingReady,
  waitForNextEnabled,
} = require("./psynetHarness");

for (const lostAcceptance of [false, true]) {
test(`accepted video advances and plays deposited bytes (lost acceptance: ${lostAcceptance}) @inplace-only`, async ({ page, context }) => {
  test.setTimeout(120000);
  let lost = false;
  if (lostAcceptance) {
    await context.route("**/response", async route => {
      if (!lost && route.request().postData()?.includes("recording_recovery_secret")) {
        lost = true;
        const accepted = await route.fetch();
        expect((await accepted.json()).submission).toBe("approved");
        await route.abort("failed");
      } else await route.continue();
    });
  }
  let held;
  await context.route("**/media-upload/*", route => { held = route; });
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async experimentPage => {
    await completeInitialGateway(experimentPage);
    await expect(experimentPage.locator("#main-body")).toContainText("Record a short clip.");
    await waitForVideoRecordingReady(experimentPage, { timeoutMs: 45000 });
    await waitForNextEnabled(experimentPage, 30000);
    const acceptance = experimentPage.waitForResponse(response =>
      new URL(response.url()).pathname === "/response" && response.request().method() === "POST", { timeout: 20000 }
    );
    await experimentPage.locator("#next-button").click();
    const response = await acceptance;
    const accepted = await response.json();
    expect(accepted.submission).toBe("approved");
    expect(accepted.recording_uploads).toHaveLength(1);
    expect(response.request().postData()).not.toContain('name="cameraRecording"');
    await expect(experimentPage.locator("#main-body")).toContainText("Independent page reached.");
    await expect.poll(() => Boolean(held)).toBe(true);
    expect(held.request().postDataBuffer().length).toBeGreaterThan(0);
    const received = experimentPage.waitForResponse(response =>
      new URL(response.url()).pathname === accepted.recording_uploads[0].url, { timeout: 20000 }
    );
    await held.continue();
    expect((await received).status()).toBe(204);
    await waitForNextEnabled(experimentPage, 30000);
    await experimentPage.locator("#next-button").click();
    const video = experimentPage.locator("video#prompt");
    await expect(video).toBeVisible({ timeout: 60000 });
    await expect.poll(() => video.evaluate(element => element.readyState >= 2 && element.duration > 0)).toBe(true);
    await video.evaluate(element => element.play());
    await expect.poll(() => video.evaluate(element => element.currentTime > 0)).toBe(true);
  });
});

}

test("upload module failure preserves submission and independent navigation @inplace-only", async ({ page, context }) => {
  test.setTimeout(120000);
  await context.route("**/static/scripts/media-upload.js", route => route.abort("failed"));
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
    await completeInitialGateway(p);
    await expect(p.locator("#main-body")).toContainText("Record a short clip.");
    await waitForVideoRecordingReady(p, { timeoutMs: 45000 });
    await waitForNextEnabled(p, 30000);
    const acceptance = p.waitForResponse(r => new URL(r.url()).pathname === "/response" && r.request().method() === "POST", { timeout: 20000 });
    await p.locator("#next-button").click();
    const response = await acceptance;
    const accepted = await response.json();
    expect(accepted.submission).toBe("approved");
    expect(accepted.recording_uploads).toEqual([]);
    expect(response.request().postData()).toContain("transport_unavailable");
    expect(response.request().postData()).not.toContain('name="cameraRecording"');
    await expect(p.locator("#main-body")).toContainText("Independent page reached.");
    await waitForNextEnabled(p, 30000);
  });
});

test("stalled upload module permits independent navigation @inplace-only", async ({page,context}) => {
  test.setTimeout(120000);
  let held;
  await context.route("**/static/scripts/media-upload.js", route => {held=route;});
  await withExperiment(page,context,path.resolve("tests/playwright/experiments/asynchronous_recording"),async p=>{
    await completeInitialGateway(p);
    await expect(p.locator("#main-body")).toContainText("Record a short clip.");
    await waitForVideoRecordingReady(p,{timeoutMs:45000});
    await waitForNextEnabled(p,30000);
    await p.clock.install();
    await p.locator("#next-button").click();
    await expect.poll(()=>Boolean(held)).toBe(true);
    await p.clock.fastForward(6000);
    await expect(p.locator("#main-body")).toContainText("Independent page reached.");
  });
});

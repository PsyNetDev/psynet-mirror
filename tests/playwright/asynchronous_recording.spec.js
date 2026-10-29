const path = require("path");
const { test, expect } = require("./fixtures");
const {
  withExperiment, prepareRecordingFixture, submitRecordingFixture,
  waitForNextEnabled, completeInitialGateway,
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
    const {accepted} = await submitRecordingFixture(experimentPage);
    expect(lost).toBe(lostAcceptance);
    expect(accepted.recording_uploads).toHaveLength(1);
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

test("manual resend after lost replies recovers the original upload slot @inplace-only", async ({ page, context }) => {
  // Every automatic attempt loses its reply. The participant is asked to press
  // Next again; that resend reuses the same submission and recovery secret, so
  // the server replays its original acceptance instead of rejecting a new one.
  test.setTimeout(120000);
  const secrets = [];
  let firstUploadId = null;
  await context.route("**/response", async route => {
    const body = route.request().postData() || "";
    const secret = body.match(/"recording_recovery_secret":\s*"([0-9a-f]+)"/)?.[1];
    if (!secret) return route.continue();
    secrets.push(secret);
    const reply = await route.fetch();
    const accepted = await reply.json();
    expect(accepted.submission).toBe("approved");
    firstUploadId ??= accepted.recording_uploads[0].id;
    if (secrets.length <= 3) return route.abort("failed");
    return route.fulfill({response: reply});
  });
  let held;
  await context.route("**/media-upload/*", route => { held = route; });
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async experimentPage => {
    await prepareRecordingFixture(experimentPage);
    await experimentPage.locator("#next-button").click();
    await expect(experimentPage.locator("#alert-modal")).toBeVisible({ timeout: 30000 });
    expect(secrets).toHaveLength(3);
    await experimentPage.locator("#alert-button").click();
    await waitForNextEnabled(experimentPage, 30000);
    await experimentPage.locator("#next-button").click();
    await expect(experimentPage.locator("#main-body")).toContainText("Independent page reached.");
    expect(new Set(secrets).size).toBe(1);
    await expect.poll(() => Boolean(held)).toBe(true);
    expect(new URL(held.request().url()).pathname).toBe(`/media-upload/${firstUploadId}`);
    expect(held.request().postDataBuffer().length).toBeGreaterThan(0);
    await held.continue();
  });
});

test("camera stream is kept on its recording page and released afterwards @inplace-only", async ({ page, context }) => {
  test.setTimeout(120000);
  await context.route("**/media-upload/*", route => route.continue());
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async experimentPage => {
    await prepareRecordingFixture(experimentPage);
    // The recording page declares its camera, so a release pass keeps it.
    expect(await experimentPage.evaluate(async () => {
      const {devices} = await psynet.getRecordingCapture();
      const stream = devices.streams.get("camera");
      window.recordedCameraTrack = stream.getVideoTracks()[0];
      await psynet.releaseUnusedRecordingStreams();
      return devices.streams.get("camera") === stream && window.recordedCameraTrack.readyState === "live";
    })).toBe(true);
    await experimentPage.locator("#next-button").click();
    await expect(experimentPage.locator("#main-body")).toContainText("Independent page reached.");
    // The next page records nothing, so the camera is released.
    await expect.poll(() => experimentPage.evaluate(async () => {
      const {devices} = await psynet.getRecordingCapture();
      return !devices.streams.has("camera") && window.recordedCameraTrack.readyState === "ended";
    })).toBe(true);
  });
});

test("camera is released while waiting for the recording @inplace-only", async ({ page, context }) => {
  test.setTimeout(120000);
  let held;
  await context.route("**/media-upload/*", route => { held = route; });
  const previous = process.env.PSYNET_TEST_RECORDING_DIRECT_WAIT;
  process.env.PSYNET_TEST_RECORDING_DIRECT_WAIT = "1";
  try {
    await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
      await prepareRecordingFixture(p);
      await p.evaluate(async () => {
        const {devices} = await psynet.getRecordingCapture();
        window.recordedCameraTrack = devices.streams.get("camera").getVideoTracks()[0];
      });
      await p.locator("#next-button").click();
      // The upload is held, so the next page waits for it.
      await expect.poll(() => p.evaluate(() => psynet.timelineHold !== null)).toBe(true);
      await expect.poll(() => p.evaluate(async () => {
        const {devices} = await psynet.getRecordingCapture();
        return !devices.streams.has("camera") && window.recordedCameraTrack.readyState === "ended";
      })).toBe(true);
      await expect.poll(() => Boolean(held)).toBe(true);
      await held.continue();
      await expect(p.locator("video#prompt")).toBeVisible({ timeout: 60000 });
    });
  } finally {
    if (previous === undefined) delete process.env.PSYNET_TEST_RECORDING_DIRECT_WAIT;
    else process.env.PSYNET_TEST_RECORDING_DIRECT_WAIT = previous;
  }
});

for (const autoAdvance of [false, true]) {
test(`legacy capture failure blocks submission until the page is reloaded (auto advance: ${autoAdvance}) @legacy-only`, async ({ page, context }) => {
  // The legacy path uploads the recording with the answer. An empty recording
  // must not be submittable: the participant is told to reload, which runs the
  // recording page again. With auto_advance, the automatic submit after the
  // message is dismissed is blocked without a "Please wait" alert.
  test.setTimeout(120000);
  // The recorder fails until the test lets it work, as after fixing access.
  await context.addInitScript(() => {
    try {
      if (sessionStorage.getItem("recorderWorks")) return;
    } catch (_) {
      return;  // Frames without storage, such as sandboxed ones, do not record.
    }
    window.MediaRecorder = class {
      constructor() { throw new Error("Simulated recorder failure"); }
      static isTypeSupported() { return true; }
    };
  });
  let submissions = 0;
  let onRecordingPage = false;
  await context.route("**/response", route => {
    if (onRecordingPage && route.request().method() === "POST") submissions += 1;
    return route.continue();
  });
  const logs = [];
  page.on("console", message => logs.push(message.text()));
  const previous = process.env.PSYNET_TEST_RECORDING_AUTO_ADVANCE;
  process.env.PSYNET_TEST_RECORDING_AUTO_ADVANCE = autoAdvance ? "1" : "0";
  try {
    await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
      await completeInitialGateway(p);
      await expect(p.locator("#main-body")).toContainText("Record a short clip.");
      onRecordingPage = true;
      await expect(p.locator("#alert-message")).toContainText("could not be captured", { timeout: 30000 });
      await p.locator("#alert-button").click();
      if (autoAdvance) {
        // Dismissing the message lets the page try to submit automatically.
        // That is blocked without telling the participant to wait instead.
        await expect.poll(() => logs.some(text => text.includes("Blocked nextPage because pageReady is false"))).toBe(true);
        await expect(p.locator("#alert-modal")).toBeHidden();
      }
      await expect.poll(() => p.evaluate(() => ({
        ready: psynet.pageReady,
        nextDisabled: document.getElementById("next-button")?.disabled,
      }))).toEqual({ ready: false, nextDisabled: true });
      expect(submissions).toBe(0);

      // Reloading runs the recording page again, and this time it records.
      await p.evaluate(() => sessionStorage.setItem("recorderWorks", "1"));
      await p.reload();
      if (autoAdvance) {
        await expect(p.locator("#main-body")).toContainText("Independent page reached.", { timeout: 60000 });
      } else {
        await expect(p.locator("#main-body")).toContainText("Record a short clip.");
        await waitForNextEnabled(p, 30000);
        await expect(p.locator("#alert-message")).not.toBeVisible();
      }
    });
  } finally {
    if (previous === undefined) delete process.env.PSYNET_TEST_RECORDING_AUTO_ADVANCE;
    else process.env.PSYNET_TEST_RECORDING_AUTO_ADVANCE = previous;
  }
});
}

test("upload module failure preserves submission and independent navigation @inplace-only", async ({ page, context }) => {
  test.setTimeout(120000);
  await context.route("**/static/scripts/media-upload.js", route => route.abort("failed"));
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
    const {accepted, response} = await submitRecordingFixture(p);
    expect(accepted.recording_uploads).toEqual([]);
    expect(response.request().postData()).toContain("transport_unavailable");
    await waitForNextEnabled(p, 30000);
  });
});

test("stalled upload module permits independent navigation @inplace-only", async ({page,context}) => {
  test.setTimeout(120000);
  let held;
  await context.route("**/static/scripts/media-upload.js", route => {held=route;});
  await withExperiment(page,context,path.resolve("tests/playwright/experiments/asynchronous_recording"),async p=>{
    await prepareRecordingFixture(p);
    await p.clock.install();
    await p.locator("#next-button").click();
    await expect.poll(()=>Boolean(held)).toBe(true);
    await p.clock.fastForward(6000);
    await expect(p.locator("#main-body")).toContainText("Independent page reached.");
  });
});

test("missing non-trial recording shows fallback without failing participant @inplace-only", async ({page, context}) => {
  test.setTimeout(120000);
  await context.route("**/media-upload/*", route => route.fulfill({status:403, body:"Upload unavailable"}));
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
    const {accepted} = await submitRecordingFixture(p);
    const id = accepted.recording_uploads[0].id;
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

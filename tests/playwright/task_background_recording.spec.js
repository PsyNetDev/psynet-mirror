const path = require("path");
const {test, expect} = require("./fixtures");
const {withExperiment, completeInitialGateway, waitForTimelinePageReady} = require("./psynetHarness");

for (const capture of [true, false]) {
  test(`task startup and persistent-session recording boundaries (capture: ${capture}) @inplace-only`, async ({page, context}) => {
    test.setTimeout(120000);
    await withExperiment(page, context, path.resolve("tests/playwright/experiments/task_background_recording"), async p => {
      await completeInitialGateway(p);
      await expect(p.locator("#background-recording-permission")).toBeVisible();
      await expect(p.locator("#unity-test-action")).toHaveCount(0);
      const decide = async () => {
        await p.getByRole("button", {name: capture ? "Enable camera" : "Continue without recording", exact: true}).click();
        await waitForTimelinePageReady(p);
      };
      const captured = async () => {
        if (capture) await expect.poll(() => p.locator("#background-recording-status").getAttribute("data-bytes").then(Number)).toBeGreaterThan(0);
      };
      // Remember this document's camera track to check that it is released.
      const keepCameraTrack = () => p.evaluate(async () => {
        const {devices} = await psynet.getRecordingCapture();
        window.cameraTrack = devices.streams.get("camera")?.getVideoTracks()[0] || null;
      });
      const cameraReleased = () => p.evaluate(async () => {
        const {devices} = await psynet.getRecordingCapture();
        return !devices.streams.has("camera") && (!window.cameraTrack || window.cameraTrack.readyState === "ended");
      });
      await decide();
      for (const step of [1, 2, 3]) {
        const button = p.getByRole("button", {name: `Complete Unity step ${step}`, exact: true});
        await expect(button).toBeVisible({timeout: 30000});
        await expect(p.locator("#background-recording-permission")).toHaveCount(0);
        await expect.poll(() => p.evaluate(() => psynet.nextPagePending)).toBe(false);
        if (step < 3) {
          await captured();
          await keepCameraTrack();
        } else {
          // A same-session page without recording stops it and turns the camera off.
          await expect.poll(cameraReleased).toBe(true);
          await expect(p.locator("#background-recording-status")).toHaveCount(0);
        }
        await button.click();
        if (step === 1) {
          // Recording stops and the camera turns off while the participant waits.
          await expect.poll(() => p.evaluate(() => psynet.timelineHold !== null)).toBe(true);
          await expect.poll(cameraReleased).toBe(true);
          await expect(p.locator("#background-recording-status")).toHaveCount(0);
        }
      }
      // jsPsych owns a new document and must await a new capture decision.
      await expect(p.locator("#background-recording-permission")).toBeVisible();
      await expect(p.getByText("Keyboard task started. Press space.", {exact:true})).toHaveCount(0);
      await decide();
      await expect(p.getByText("Keyboard task started. Press space.", {exact:true})).toBeVisible();
      await captured();
      await p.keyboard.press("Space");
      await expect(p.locator("#main-body")).toContainText("Tasks complete.");
      const rows = await (await context.request.get(new URL("/test-capture-state", p.url()).href)).json();
      expect(rows).toHaveLength(3);
      expect(new Set(rows.map(row => row.page_uuid)).size).toBe(3);
      expect(rows.every(row => row.recording_role === "background" && row.required_for_trial === false)).toBe(true);
      if (!capture) expect(rows.every(row => row.recording_failure_reason === "skipped")).toBe(true);
    });
  });
}

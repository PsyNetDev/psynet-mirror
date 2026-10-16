const path = require("path");
const { test, expect } = require("./fixtures");
const { expectBlobPlays } = require("./psynetHarness");
const captureLabels = {
  optional:"Optional capture", required:"Required capture", answer:"Record this answer",
  camera:"Enable camera", screen:"Share screen", skip:"Continue without recording",
  recording:"Recording", stopped:"Recording stopped",
};

// Real MediaRecorder capture with fake Chrome devices; no experiment database.
test.describe("Optional background capture lifecycle @both", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("https://capture.test/", route => route.fulfill({contentType:"text/html",body:"<main>Page</main>"}));
    for (const module of ["background-recording", "media-upload", "recording-capture"]) {
      await page.route(`https://capture.test/${module}.js`, route => route.fulfill({contentType:"text/javascript",path:path.resolve(`psynet/resources/scripts/${module}.js`)}));
    }
    await page.goto("https://capture.test/");
    await page.evaluate(async labels => {
      const {BackgroundRecorder} = await import("/background-recording.js");
      const {MediaUploadQueue} = await import("/media-upload.js");
      window.capture = new BackgroundRecorder(new MediaUploadQueue());
      window.config = {sources:["camera"],audio:false,max_duration:1,max_bytes:1024*1024,labels};
    }, captureLabels);
  });

  test("duration limit preserves a clip", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin(config);});
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    await expect.poll(() => page.evaluate(() => capture.outcomes.camera)).toBe("duration_limit");
    const result = await page.evaluate(async () => {
      const first = await capture.finish();
      const second = await capture.finish();
      return {size:first.recordings.camera.size,again:second.recordings.camera.size,unavailable:first.unavailable};
    });
    expect(result.size).toBeGreaterThan(0);
    expect(result.again).toBe(result.size);
    expect(result.unavailable).toEqual({});
    await page.evaluate(() => capture.begin(config));
    await expect(page.locator("#background-recording-permission")).toHaveCount(0);
  });

  test("size limit keeps the part captured so far", async ({page}) => {
    const limit = 160 * 1024;
    await page.evaluate(limit => {window.started = capture.begin({...config,max_duration:30,max_bytes:limit});}, limit);
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    await expect.poll(() => page.evaluate(() => capture.outcomes.camera), {timeout:20000}).toBe("size_limit");
    const result = await page.evaluate(async () => {
      const result = await capture.finish();
      window.limited = result.recordings.camera;
      return {size:result.recordings.camera?.size || 0,unavailable:result.unavailable,outcome:result.outcomes.camera};
    });
    expect(result.outcome).toBe("size_limit");
    expect(result.unavailable).toEqual({});
    expect(result.size).toBeGreaterThan(0);
    expect(result.size).toBeLessThanOrEqual(limit);
    await expectBlobPlays(page, "limited");
  });

  test("submitting does not stop recording, so a later submission includes more", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin({...config,max_duration:30});});
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    await expect.poll(() => page.evaluate(() => capture.clips.camera.size)).toBeGreaterThan(0);
    const first = await page.evaluate(async () => {
      window.snapshot = (await capture.finish()).recordings.camera;
      return snapshot.size;
    });
    expect(first).toBeGreaterThan(0);
    expect(await page.evaluate(() => capture.clips.camera.getState())).toBe("recording");
    // A snapshot of a recording still in progress plays on its own.
    await expectBlobPlays(page, "snapshot");
    await expect.poll(async () => page.evaluate(async () => (await capture.finish()).recordings.camera.size)).toBeGreaterThan(first);
  });

  test("a rejected early submission keeps recording for the next one", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin({...config,max_duration:30});});
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    // Without flushed data, as on an answer within the first second, the
    // snapshot has to stop the clip.
    const early = await page.evaluate(async () => {
      capture.clips.camera.flush = async () => {};
      const result = await capture.finish();
      return {size:result.recordings.camera?.size || 0,state:capture.clips.camera.getState()};
    });
    expect(early.state).not.toBe("recording");
    await page.evaluate(() => capture.resume());
    expect(await page.evaluate(() => capture.clips.camera.getState())).toBe("recording");
    await expect(page.locator("#background-recording-status")).toHaveText("Recording");
    await expect.poll(() => page.evaluate(() => capture.clips.camera.size)).toBeGreaterThan(0);
    const next = await page.evaluate(async () => {
      const result = await capture.finish();
      window.resumed = result.recordings.camera;
      return {size:result.recordings.camera.size,state:capture.clips.camera.getState(),unavailable:result.unavailable};
    });
    expect(next.size).toBeGreaterThan(0);
    expect(next.state).toBe("recording");
    expect(next.unavailable).toEqual({});
    await expectBlobPlays(page, "resumed");
  });

  test("skipping capture avoids another permission prompt", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin(config);});
    await page.getByRole("button",{name:"Continue without recording",exact:true}).click();
    await page.evaluate(() => started);
    // Nothing is recorded, so no status chip is shown.
    await expect(page.locator("#background-recording-status")).toHaveCount(0);
    expect(await page.evaluate(async () => (await capture.finish()).unavailable)).toEqual({camera:"skipped"});
    await page.evaluate(() => capture.begin(config));
    await expect(page.locator("#background-recording-permission")).toHaveCount(0);
    await page.evaluate(() => { window.started = capture.begin({...config,required:true}); });
    await expect(page.locator("#background-recording-permission")).toBeVisible();
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    // A granted camera is reacquired silently once its track ends; the dialog
    // returns only when that fails.
    await page.evaluate(async () => {
      capture.streams.get("camera").getVideoTracks()[0].stop();
      await capture.begin({...config,required:true});
    });
    await expect(page.locator("#background-recording-permission")).toHaveCount(0);
    expect(await page.evaluate(() => capture.clips.camera.getState())).toBe("recording");
    await page.evaluate(() => {
      capture.streams.get("camera").getVideoTracks()[0].stop();
      navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Denied", "NotAllowedError"));
      window.started = capture.begin({...config,required:true});
    });
    await expect(page.locator("#background-recording-permission")).toBeVisible();
    await page.getByRole("button",{name:"Continue without recording",exact:true}).click();
    await page.evaluate(() => started);
  });

  test("skipping a microphone upgrade preserves video without requesting audio again", async ({page}) => {
    await page.evaluate(async () => {
      await capture.devices.acquire("camera");
      window.started = capture.begin({...config,audio:true,required:true});
    });
    await expect(page.locator("#background-recording-permission")).toBeVisible();
    await page.getByRole("button",{name:"Continue without recording",exact:true}).click();
    const result = await page.evaluate(async () => {
      await started;
      const result = await capture.finish();
      return {unavailable:result.unavailable,videoLive:!!capture.devices.reusable("camera",false)};
    });
    expect(result).toEqual({unavailable:{camera:"skipped"},videoLive:true});
  });

  test("camera and screen produce separate clips without audio by default", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin({...config,sources:["camera","screen"]});});
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.getByRole("button",{name:"Share screen",exact:true}).click();
    await page.evaluate(() => started);
    await expect.poll(() => page.evaluate(() => Object.keys(capture.outcomes).length)).toBe(2);
    const result = await page.evaluate(async () => {
      const result = await capture.finish();
      return {sizes:result.sizes,unavailable:result.unavailable,audioTracks:[...capture.streams.values()].flatMap(stream => stream.getAudioTracks()).length};
    });
    expect(result.sizes.camera).toBeGreaterThan(0);
    expect(result.sizes.screen).toBeGreaterThan(0);
    expect(result.unavailable).toEqual({});
    expect(result.audioTracks).toBe(0);
  });
});

// Both facades use the same native recorder and retain compatible source tracks.
test.describe("Shared recording capture @both", () => {
  test.beforeEach(async ({page}) => {
    await page.route("https://capture.test/", route => route.fulfill({contentType:"text/html",body:"<main>Capture</main>"}));
    for (const module of ["background-recording", "media-upload", "recording-capture"]) {
      await page.route(`https://capture.test/${module}.js`, route => route.fulfill({contentType:"text/javascript",path:path.resolve(`psynet/resources/scripts/${module}.js`)}));
    }
    await page.goto("https://capture.test/");
    await page.evaluate(labels => { window.captureLabels = labels; }, captureLabels);
  });

  for (const source of ["camera", "screen"]) {
    test(`background and answer clips share ${source} tracks and play independently`, async ({page}) => {
      await page.evaluate(async source => {
        const {BackgroundRecorder} = await import("/background-recording.js");
        const {MediaUploadQueue} = await import("/media-upload.js");
        window.capture = new BackgroundRecorder(new MediaUploadQueue());
        window.started = capture.begin({sources:[source],audio:false,max_duration:1,max_bytes:1024*1024,labels:captureLabels});
      }, source);
      await page.getByRole("button", {name:source === "camera" ? "Enable camera" : "Share screen",exact:true}).click();
      await page.evaluate(() => started);
      await expect.poll(() => page.evaluate(source => capture.outcomes[source], source)).toBe("duration_limit");
      await page.evaluate(async source => {
        const {RecordingClip} = await import("/recording-capture.js");
        window.backgroundBlob = (await capture.finish()).recordings[source];
        const original = capture.streams.get(source);
        const settings = original.getVideoTracks()[0].getSettings();
        window.captureSettings = settings;
        await capture.discard();
        const stream = await capture.devices.acquireAnswer(source, false);
        window.reusedStream = stream.getVideoTracks()[0] === original.getVideoTracks()[0];
        window.answerClip = new RecordingClip(stream, {maxDuration:1});
        answerClip.startRecording();
      }, source);
      expect(await page.evaluate(() => reusedStream)).toBe(true);
      const settings = await page.evaluate(() => captureSettings);
      expect(settings.width).toBeLessThanOrEqual(640);
      expect(settings.height).toBeLessThanOrEqual(480);
      expect(settings.frameRate).toBeLessThanOrEqual(15);
      await expect(page.locator("#answer-recording-permission")).toHaveCount(0);
      await expect.poll(() => page.evaluate(() => answerClip.outcome)).toBe("duration_limit");
      await page.evaluate(async () => {
        await answerClip.stopRecording();
        for (const [id, blob] of [["background", backgroundBlob], ["answer", answerClip.getBlob()]]) {
          const video = document.createElement("video");
          video.id = id;
          video.muted = true;
          video.src = URL.createObjectURL(blob);
          document.body.append(video);
        }
      });
      for (const id of ["background", "answer"]) {
        const video = page.locator(`video#${id}`);
        await expect.poll(() => video.evaluate(element => element.readyState >= 2 && element.videoWidth > 0)).toBe(true);
        await video.evaluate(element => element.play());
        await expect.poll(() => video.evaluate(element => element.currentTime)).toBeGreaterThan(0);
      }
    });
  }
});

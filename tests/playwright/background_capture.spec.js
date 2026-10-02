const path = require("path");
const { test, expect } = require("./fixtures");
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

  test("duration limit preserves a clip and rejected answers reuse it", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin(config);});
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    await expect.poll(() => page.evaluate(() => capture.outcomes.camera)).toBe("duration_limit");
    const result = await page.evaluate(async () => {
      const first = await capture.finish();
      const second = await capture.finish();
      return {size:first.recordings.camera.size,same:first.recordings.camera === second.recordings.camera,unavailable:first.unavailable};
    });
    expect(result.size).toBeGreaterThan(0);
    expect(result.same).toBe(true);
    expect(result.unavailable).toEqual({});
    await page.evaluate(() => capture.begin(config));
    await expect(page.locator("#background-recording-permission")).toHaveCount(0);
  });

  test("oversized capture is discarded without blocking submission", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin({...config,max_bytes:1});});
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    await expect.poll(() => page.evaluate(() => capture.unavailable.camera)).toBe("size_limit");
    const result = await page.evaluate(async () => {
      const result = await capture.finish();
      return {sources:Object.keys(result.recordings),unavailable:result.unavailable};
    });
    expect(result).toEqual({sources:[],unavailable:{camera:"size_limit"}});
  });

  test("skipping capture avoids another permission prompt", async ({page}) => {
    await page.evaluate(() => {window.started = capture.begin(config);});
    await page.getByRole("button",{name:"Continue without recording",exact:true}).click();
    await page.evaluate(() => started);
    expect(await page.evaluate(async () => (await capture.finish()).unavailable)).toEqual({camera:"skipped"});
    await page.evaluate(() => capture.begin(config));
    await expect(page.locator("#background-recording-permission")).toHaveCount(0);
    await page.evaluate(() => { window.started = capture.begin({...config,required:true}); });
    await expect(page.locator("#background-recording-permission")).toBeVisible();
    await page.getByRole("button",{name:"Enable camera",exact:true}).click();
    await page.evaluate(() => started);
    await page.evaluate(() => {
      capture.streams.get("camera").getVideoTracks()[0].stop();
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

  test("camera video survives changes in microphone requirements", async ({page}) => {
    const result = await page.evaluate(async () => {
      const {RecordingDevices} = await import("/recording-capture.js");
      const devices = new RecordingDevices();
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      const requests = [];
      navigator.mediaDevices.getUserMedia = constraints => {
        requests.push(constraints);
        return original(constraints);
      };
      try {
        const first = await devices.acquire("camera", {audio:true});
        const microphone = first.getAudioTracks()[0];
        const silent = await devices.acquire("camera");
        const microphoneStopped = microphone.readyState === "ended" && devices.streams.get("camera").getAudioTracks().length === 0;
        const changed = await devices.acquire("camera", {audio:{channelCount:1}});
        return {
          sameVideo: [silent, changed].every(stream => stream.getVideoTracks()[0] === first.getVideoTracks()[0]),
          silent: silent.getAudioTracks().length === 0,
          microphoneStopped,
          videoRequests: requests.filter(request => request.video).length,
          microphoneRequests: requests.filter(request => request.video === false).length,
        };
      } finally {
        navigator.mediaDevices.getUserMedia = original;
        devices.release("camera");
      }
    });
    expect(result).toEqual({sameVideo:true,silent:true,microphoneStopped:true,videoRequests:1,microphoneRequests:1});
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

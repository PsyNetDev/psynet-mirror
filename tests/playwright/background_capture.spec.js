const path = require("path");
const { test, expect } = require("./fixtures");

// Real MediaRecorder capture with fake Chrome devices; no experiment database.
test.describe("Optional background capture lifecycle @both", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("https://capture.test/", route => route.fulfill({contentType:"text/html",body:"<main>Page</main>"}));
    for (const module of ["background-recording", "media-upload"]) {
      await page.route(`https://capture.test/${module}.js`, route => route.fulfill({contentType:"text/javascript",path:path.resolve(`psynet/resources/scripts/${module}.js`)}));
    }
    await page.goto("https://capture.test/");
    await page.evaluate(async () => {
      const {BackgroundRecorder} = await import("/background-recording.js");
      const {MediaUploadQueue} = await import("/media-upload.js");
      window.capture = new BackgroundRecorder(new MediaUploadQueue());
      window.config = {sources:["camera"],audio:false,max_duration:1,max_bytes:1024*1024};
    });
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

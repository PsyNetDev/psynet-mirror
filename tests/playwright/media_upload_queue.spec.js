const path = require("path");
const { test, expect } = require("./fixtures");

// Browser fetch/abort, deadline, DOM lifetime and unload checks. Pure transport
// policy lives in tests/javascript/media-upload-queue.test.mjs.
test.describe("Document-owned media upload queue @both", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("http://media.test/", (route) =>
      route.fulfill({ contentType: "text/html", body: "<main>First page</main>" })
    );
    await page.route("http://media.test/media-upload.js", (route) =>
      route.fulfill({
        path: path.resolve("psynet/resources/scripts/media-upload.js"),
        contentType: "text/javascript"
      })
    );
    await page.goto("http://media.test/");
    await page.evaluate(async () => {
      const { MediaUploadQueue } = await import("/media-upload.js");
      window.queue = new MediaUploadQueue({ concurrency: 1, maxBytes: 100 });
      window.enqueue = (id, timeout = 60000, text = "recorded bytes") => {
        const promise = queue.enqueue({
          id,
          url: `/media-upload/${id}`,
          token: "write-capability",
          deadline: performance.now() + timeout,
          blob: new Blob([text], { type: "video/webm" })
        });
        window.results ||= {};
        promise.then((result) => { results[id] = result; });
        return promise;
      };
    });
  });

  test("keeps bytes after page content changes and does not wait for delivery", async ({ page }) => {
    let upload;
    await page.route("**/media-upload/first", (route) => { upload = route; });
    await page.evaluate(() => {
      enqueue("first");
      window.drained = false;
      queue.drain().then(() => { window.drained = true; });
      document.querySelector("main").textContent = "Next page";
    });
    await expect(page.locator("main")).toHaveText("Next page");
    await expect.poll(() => Boolean(upload)).toBe(true);
    expect(upload.request().postData()).toBe("recorded bytes");
    expect(upload.request().headers().authorization).toBe("Bearer write-capability");
    expect(await page.evaluate(() => results.first)).toBeUndefined();
    expect(await page.evaluate(() => drained)).toBe(false);
    expect(await page.evaluate(() => window.dispatchEvent(new Event("beforeunload", {cancelable:true})))).toBe(false);
    await upload.fulfill({ status: 204 });
    await expect.poll(() => page.evaluate(() => results.first)).toEqual({ status: "received" });
    expect(await page.evaluate(() => queue.pendingBytes)).toBe(0);
    expect(await page.evaluate(() => drained)).toBe(true);
    expect(await page.evaluate(() => window.dispatchEvent(new Event("beforeunload", {cancelable:true})))).toBe(true);
  });

  test("allows a slow delivery to finish without restarting at ten seconds", async ({ page }) => {
    await page.clock.install();
    const uploads = [];
    await page.route("**/media-upload/slow", (route) => { uploads.push(route); });
    await page.evaluate(() => { enqueue("slow", 60000); });
    await expect.poll(() => uploads.length).toBe(1);
    await page.clock.runFor(12000);
    expect(uploads).toHaveLength(1);
    expect(await page.evaluate(() => results.slow)).toBeUndefined();
    await uploads[0].fulfill({ status: 204 });
    await expect.poll(() => page.evaluate(() => results.slow)).toEqual({ status: "received" });
  });

  test("does not extend the deadline when scheduling another attempt", async ({ page }) => {
    await page.clock.install();
    let requests = 0;
    await page.route("**/media-upload/short", (route) => {
      requests += 1;
      return route.fulfill({ status: 503 });
    });
    await page.evaluate(() => { enqueue("short", 100); });
    await expect.poll(() => requests).toBe(1);
    await page.clock.runFor(1001);
    expect(await page.evaluate(() => results.short)).toEqual({ status: "failed", reason: "deadline" });
    expect(requests).toBe(1);
  });

  test("expires queued files without resetting their deadline when a slot opens", async ({ page }) => {
    await page.clock.install();
    let held;
    let queuedRequests = 0;
    await page.route("**/media-upload/held", (route) => { held = route; });
    await page.route("**/media-upload/queued", (route) => {
      queuedRequests += 1;
      return route.fulfill({ status: 204 });
    });
    await page.evaluate(() => { enqueue("held"); enqueue("queued", 1000); });
    await expect.poll(() => Boolean(held)).toBe(true);
    await page.clock.runFor(1001);
    expect(await page.evaluate(() => results.queued)).toEqual({ status: "failed", reason: "deadline" });
    await held.fulfill({ status: 204 });
    await expect.poll(() => page.evaluate(() => results.held?.status)).toBe("received");
    expect(queuedRequests).toBe(0);
  });

  test("aborts a stalled upload at its deadline and releases the next slot", async ({ page }) => {
    await page.clock.install();
    let started = false;
    await page.route("**/media-upload/stalled", () => { started = true; });
    await page.route("**/media-upload/next", (route) => route.fulfill({ status: 204 }));
    await page.evaluate(() => {
      enqueue("stalled", 1000); enqueue("next");
      window.drained = false;
      queue.drain().then(() => { window.drained = true; });
    });
    await expect.poll(() => started).toBe(true);
    expect(await page.evaluate(() => {
      queue.allowUnload();
      return window.dispatchEvent(new Event("beforeunload", {cancelable:true}));
    })).toBe(true);
    await page.clock.runFor(1001);
    await expect.poll(() => page.evaluate(() => results.next?.status)).toBe("received");
    expect(await page.evaluate(() => results.stalled)).toEqual({ status: "failed", reason: "deadline" });
    await expect.poll(() => page.evaluate(() => drained)).toBe(true);
    expect(await page.evaluate(() => queue.pendingBytes)).toBe(0);
  });

});

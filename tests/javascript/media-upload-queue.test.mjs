import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeEach, afterEach, test } from "node:test";

// Import the browser ES module without changing the repository's CommonJS mode.
const source = readFileSync(new URL("../../psynet/resources/scripts/media-upload.js", import.meta.url));
const { MediaUploadQueue } = await import(`data:text/javascript;base64,${source.toString("base64")}`);
let queue;
const blob = (size) => new Blob([new Uint8Array(size)]);
const upload = (id, size = 14) => ({id, url:`/media-upload/${id}`, token:"secret", deadline:performance.now() + 10000, blob:blob(size)});
const originalWindow = globalThis.window;
beforeEach(() => {
  globalThis.window = Object.assign(new EventTarget(), {location:new URL("http://media.test/")});
  queue = new MediaUploadQueue({concurrency:1, maxBytes:100, retryDelay:1});
});
afterEach(() => { globalThis.window = originalWindow; });

for (const [name, statuses, expected] of [
  ["temporary failure", [503, 204], {status:"received"}],
  ["permanent rejection", [403], {status:"failed", reason:"http_error", httpStatus:403}],
  ["network failures", [null, null, null], {status:"failed", reason:"attempts_exhausted"}],
]) {
  test(name, async t => {
    const request = upload("retry");
    let attempt = 0;
    const fetch = t.mock.method(globalThis, "fetch", async (url, options) => {
      assert.equal(url, "http://media.test/media-upload/retry");
      assert.equal(options.body, request.blob);
      assert.equal(options.headers.Authorization, "Bearer secret");
      const status = statuses[attempt++];
      if (status === null) throw new TypeError("Network unavailable");
      return new Response(null, {status});
    });
    assert.deepEqual(await queue.enqueue(request), expected);
    assert.equal(fetch.mock.callCount(), statuses.length);
    assert.equal(queue.pendingBytes, 0);
  });
}

test("duplicate IDs preserve the original file", async t => {
  const request = upload("duplicate");
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response(null, {status:204}));
  const pending = queue.enqueue(request);
  assert.throws(() => queue.enqueue(upload("duplicate", 20)), /already queued/);
  assert.deepEqual(await pending, {status:"received"});
  assert.equal(fetch.mock.callCount(), 1);
  assert.equal(fetch.mock.calls[0].arguments[1].body, request.blob);
  assert.equal(queue.pendingBytes, 0);
});

test("capacity is shared during preparation and reclaimed after receipt", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response(null, {status:204}));
  const pending = queue.enqueue(upload("held", 60));
  const prepared = queue.prepare({camera:blob(30), screen:blob(30)}, 50);
  assert.deepEqual(Object.keys(prepared.recordings), ["camera"]);
  assert.deepEqual(prepared.unavailable, {screen:"queue_full"});
  const overflow = queue.enqueue(upload("overflow", 50));
  assert.deepEqual(await overflow, {status:"failed", reason:"queue_full"});
  await pending;
  assert.equal(queue.pendingBytes, 0);
  assert.deepEqual(await queue.enqueue(upload("after", 90)), {status:"received"});
});

test("cross-origin uploads never expose the capability or bytes", t => {
  const fetch = t.mock.method(globalThis, "fetch", () => assert.fail("Unexpected upload"));
  assert.throws(() => queue.enqueue({...upload("bad"), url:"https://elsewhere.test/upload"}), /same origin/);
  assert.equal(fetch.mock.callCount(), 0);
  assert.equal(queue.pendingBytes, 0);
});

test("preparation distinguishes missing and oversized captures", () => {
  assert.deepEqual(queue.prepare({camera:blob(0), screen:blob(60)}, 50).unavailable,
    {camera:"missing_recording", screen:"size_limit"});
});

test("default capacity admits two recordings up to the server source limit", () => {
  const recording = blob(80 * 1024**2);
  assert.deepEqual(Object.keys(new MediaUploadQueue().prepare(
    {camera:recording, screen:recording}, 128 * 1024**2).recordings), ["camera", "screen"]);
});

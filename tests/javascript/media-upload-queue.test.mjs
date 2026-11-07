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

// null: network error; numbers: HTTP status (429 replies carry Retry-After: 0).
for (const [name, statuses, expected] of [
  ["temporary failure", [503, 204], {status:"received"}],
  ["stalled connection (408)", [408, 204], {status:"received"}],
  ["permanent rejection", [403], {status:"failed", reason:"http_error", httpStatus:403}],
  ["expired upload (410)", [410], {status:"failed", reason:"http_error", httpStatus:410}],
  ["persistent server fault", [500, 500, 500, 500, 500], {status:"failed", reason:"http_error", httpStatus:500}],
  ["repeated network failures until delivery", [null, null, null, null, 204], {status:"received"}],
  ["active upload elsewhere (429) until delivery", [429, 429, 429, 429, 204], {status:"received"}],
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
      return new Response(null, {status, headers: status === 429 ? {"Retry-After": "0"} : {}});
    });
    assert.deepEqual(await queue.enqueue(request), expected);
    assert.equal(fetch.mock.callCount(), statuses.length);
    assert.equal(queue.pendingBytes, 0);
  });
}

test("retries stop only at the reservation deadline", async t => {
  t.mock.method(globalThis, "fetch", async () => { throw new TypeError("Network unavailable"); });
  const request = {...upload("offline"), deadline: performance.now() + 50};
  assert.deepEqual(await queue.enqueue(request), {status:"failed", reason:"deadline"});
  assert.equal(queue.pendingBytes, 0);
});

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

// An upload request that stays in flight until the test delivers it or the queue aborts it.
function holdUploads(t, heartbeat = () => ({unavailable: []})) {
  const deliveries = new Map();
  const heartbeats = [];
  t.mock.method(globalThis, "fetch", (url, options) => {
    if (url === "/media-upload/heartbeat") {
      heartbeats.push(JSON.parse(options.body));
      return Promise.resolve(Response.json(heartbeat()));
    }
    return new Promise((resolve, reject) => {
      deliveries.set(url.split("/").pop(), () => resolve(new Response(null, {status:204})));
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    });
  });
  return {deliveries, heartbeats};
}

test("backpressure waits only while two earlier pages are still uploading", async t => {
  const {deliveries} = holdUploads(t);
  const next = {camera: blob(14)};
  const first = queue.enqueue({...upload("first"), group:"page-1"});
  assert.equal(queue.hasRoom(next, 50), true);
  const second = queue.enqueue({...upload("second"), group:"page-2"});
  let released = false;
  const waiting = queue.waitForRoom(next, 50).then(() => { released = true; });
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(released, false);
  deliveries.get("first")();
  await first;
  await waiting;
  await new Promise(resolve => setTimeout(resolve, 5));
  deliveries.get("second")();
  assert.deepEqual(await second, {status:"received"});
});

test("backpressure also waits until the next page's recordings fit", async t => {
  const {deliveries} = holdUploads(t);
  // One dual-source page nearly fills the 100-byte queue.
  const camera = queue.enqueue({...upload("camera", 45), group:"page-1"});
  const screen = queue.enqueue({...upload("screen", 45), group:"page-1"});
  const next = {camera: blob(45), screen: blob(45)};
  assert.equal(queue.hasRoom(next, 50), false);
  let released = false;
  const waiting = queue.waitForRoom(next, 50).then(() => { released = true; });
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(released, false);
  deliveries.get("camera")();
  await camera;
  await new Promise(resolve => setTimeout(resolve, 5));
  deliveries.get("screen")();
  await screen;
  await waiting;
  assert.equal(released, true);
});

test("heartbeats renew outstanding uploads and release expired ones", async t => {
  queue = new MediaUploadQueue({concurrency:1, maxBytes:100, retryDelay:1});
  const {heartbeats} = holdUploads(t, () => ({unavailable: ["gone"]}));
  const outcome = await queue.enqueue({...upload("gone"), renewInterval:5});
  assert.deepEqual(outcome, {status:"failed", reason:"expired"});
  assert.deepEqual(heartbeats[0], {uploads: [{id:"gone", token:"secret"}]});
  assert.equal(queue.pendingBytes, 0);
});

test("default capacity admits two recordings up to the server source limit", () => {
  const recording = blob(80 * 1024**2);
  assert.deepEqual(Object.keys(new MediaUploadQueue().prepare(
    {camera:recording, screen:recording}, 128 * 1024**2).recordings), ["camera", "screen"]);
});

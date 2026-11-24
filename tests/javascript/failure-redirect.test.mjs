import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.js"),
  "utf8"
);
const BODY = SOURCE.match(
  /psynet\.moveOnAfterFailure = function \(pageUuid\) \{([\s\S]*?)\n    \};/
)[1];

function run(pageUuid, state = {}) {
  const calls = [];
  const psynet = {
    timelineHold: null,
    nextPagePending: false,
    log: { info() {}, warn: () => calls.push("warn") },
    waiting: { stop: () => calls.push("stopWaiting") },
    stopArrivalUpdates: () => calls.push("stopArrivalUpdates"),
    loadNextTimelinePageWithReload: () => calls.push("reload"),
    ...state,
  };
  const window = { pageUuid: "page-1" };
  const moved = new Function("psynet", "window", "pageUuid", BODY)(
    psynet,
    window,
    pageUuid
  );
  return { moved, calls, psynet };
}

describe("psynet.handleArrivalUpdateMessage", () => {
  it("passes a failure message to moveOnAfterFailure", () => {
    const body = SOURCE.match(
      /psynet\.handleArrivalUpdateMessage = function \(message\) \{([\s\S]*?)\n    \};/
    )[1];
    const failedOn = [];
    const psynet = { moveOnAfterFailure: (pageUuid) => failedOn.push(pageUuid) };
    new Function("psynet", "message", body)(psynet, {
      type: "timeline_hold_wake",
      targets: [{ reason: "participant_failed", page_uuid: "page-1" }],
    });
    assert.deepEqual(failedOn, ["page-1"]);
  });
});

describe("psynet.moveOnAfterFailure", () => {
  it("blocks submissions, stops updates and reloads on the failed page", () => {
    const { moved, calls, psynet } = run("page-1");
    assert.equal(moved, true);
    assert.equal(psynet.nextPagePending, true);
    assert.deepEqual(calls, ["stopWaiting", "stopArrivalUpdates", "reload"]);
  });

  it("lets the participant submit again if the reload fails", async () => {
    const { calls, psynet } = run("page-1", {
      loadNextTimelinePageWithReload: () => Promise.reject(new Error("upload")),
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(psynet.nextPagePending, false);
    assert.equal(calls.at(-1), "warn");
  });

  it("remembers a failure during a submit, for nextPage if it is rejected", () => {
    const { moved, psynet } = run("page-1", { nextPagePending: true });
    assert.equal(moved, false);
    assert.equal(psynet.failedDuringSubmit, "page-1");
    assert.match(
      SOURCE,
      /nextPagePending = false;[\s\S]{0,300}psynet\.moveOnAfterFailure\(psynet\.failedDuringSubmit\)/
    );
  });

  for (const [label, pageUuid, state] of [
    ["another page", "page-0", {}],
    ["no failure", undefined, {}],
    ["a held page", "page-1", { timelineHold: {} }],
    ["a pending submission", "page-1", { nextPagePending: true }],
  ]) {
    it(`does nothing for ${label}`, () => {
      const { moved, calls } = run(pageUuid, state);
      assert.equal(moved, false);
      assert.deepEqual(calls, []);
    });
  }
});

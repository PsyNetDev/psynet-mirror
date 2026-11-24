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
    log: { info() {} },
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

describe("psynet.moveOnAfterFailure", () => {
  it("blocks submissions, stops updates and reloads on the failed page", () => {
    const { moved, calls, psynet } = run("page-1");
    assert.equal(moved, true);
    assert.equal(psynet.nextPagePending, true);
    assert.deepEqual(calls, ["stopWaiting", "stopArrivalUpdates", "reload"]);
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

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.js"),
  "utf8"
);

function extract(name) {
  const match = SOURCE.match(
    new RegExp(`psynet\\.${name} = function[\\s\\S]*?\\n    \\};`)
  );
  assert.ok(match, `missing psynet.${name}`);
  return match[0];
}

it("drops arrival snapshots that come back after a newer one", () => {
  const psynet = { notices: [] };
  psynet.applyArrivalNotice = (notice) => psynet.notices.push(notice);
  const window = { pageUuid: "page-1", dispatchEvent() {} };
  class CustomEvent {}
  new Function(
    "psynet",
    "window",
    "CustomEvent",
    ["applyArrivalSnapshot", "readySeatsFor"].map(extract).join("\n")
  )(psynet, window, CustomEvent);

  const snapshot = (count) => ({
    notice: `${count}/6 ready`,
    group_ready: [{ group_id: 1, seats: [...Array(count).keys()] }],
  });
  psynet.applyArrivalSnapshot(snapshot(4), 2);
  psynet.applyArrivalSnapshot(snapshot(3), 1);
  assert.deepEqual(psynet.notices, ["4/6 ready"]);
  assert.deepEqual(psynet.readySeatsFor(1), [0, 1, 2, 3]);
  window.pageUuid = "page-2";
  assert.deepEqual(psynet.readySeatsFor(1), []);
});

it("ignores an arrival snapshot that comes back after the page changed", () => {
  const applied = [];
  const psynet = { uniqueId: "p1", arrivalUpdates: {} };
  psynet.applyArrivalSnapshot = (data) => applied.push(data);
  const window = { pageUuid: "page-1" };
  const pending = [];
  const $ = { ajax: () => ({ done: (callback) => pending.push(callback) }) };
  new Function("psynet", "window", "$", extract("fetchArrivalNotice"))(
    psynet,
    window,
    $
  );

  psynet.fetchArrivalNotice();
  window.pageUuid = "page-2";
  psynet.fetchArrivalNotice();
  pending.forEach((callback, i) => callback({ request: i }));
  assert.deepEqual(applied, [{ request: 1 }]);
});

it("fetches once for refresh requests that come close together", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let fetches = 0;
  const psynet = { fetchArrivalNotice: () => (fetches += 1) };
  new Function("psynet", extract("requestArrivalRefresh"))(psynet);

  psynet.requestArrivalRefresh();
  psynet.requestArrivalRefresh();
  t.mock.timers.tick(150);
  assert.equal(fetches, 1);
  psynet.requestArrivalRefresh();
  t.mock.timers.tick(150);
  assert.equal(fetches, 2);
});

function arrivalNotices() {
  let notice = null;
  const header = { appendChild: (el) => (notice = el) };
  const document = {
    body: { classList: { contains: () => false } },
    getElementById: (id) => (id === "timeline-header" ? header : notice),
    createElement: () => ({ dataset: {}, setAttribute() {}, remove: () => (notice = null) }),
  };
  const psynet = { arrivalNoticeSuppressors: 0 };
  new Function(
    "psynet",
    "document",
    ["hideArrivalNotice", "suppressArrivalNotice", "showArrivalNotice", "applyArrivalNotice"]
      .map(extract)
      .join("\n")
  )(psynet, document);
  return { psynet, shown: () => notice?.textContent ?? null };
}

it("hides the arrival notice while a page suppresses it", () => {
  const { psynet, shown } = arrivalNotices();
  psynet.showArrivalNotice("1/3 ready");
  const release = psynet.suppressArrivalNotice();
  assert.equal(shown(), null);
  psynet.showArrivalNotice("2/3 ready");
  assert.equal(shown(), null);
  release();
  release();
  psynet.showArrivalNotice("3/3 ready");
  assert.equal(shown(), "3/3 ready");
});

it("shows a removal notice while a page suppresses arrival notices", () => {
  const { psynet, shown } = arrivalNotices();
  const removed = "Your group went on without you.";
  psynet.applyArrivalNotice(removed, { removed: true });
  psynet.suppressArrivalNotice();
  assert.equal(shown(), removed);
  psynet.applyArrivalNotice(null);
  psynet.applyArrivalNotice(removed, { removed: true });
  assert.equal(shown(), removed);
});

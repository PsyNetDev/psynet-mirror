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

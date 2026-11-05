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

function load() {
  const psynet = { notices: [] };
  psynet.applyArrivalNotice = (notice) => psynet.notices.push(notice);
  const window = { pageUuid: "page-1", dispatchEvent() {} };
  class CustomEvent {}
  new Function(
    "psynet",
    "window",
    "CustomEvent",
    `${extract("applyArrivalTarget")}\n${extract("addReadySeats")}`
  )(psynet, window, CustomEvent);
  return psynet;
}

const notices = (from, to) =>
  Array.from({ length: to - from + 1 }, (_, i) => `${from + i}/6 ready`);
const entry = (seats, members, from, nSeats = 6) => ({
  group_id: 1,
  barrier_id: "chose",
  seats,
  members,
  n_seats: nSeats,
  notices: notices(from, 5),
  notices_from: from,
});

it("counts arrivals reported out of order and by the connect snapshot", () => {
  const psynet = load();
  const members = [0, 1, 2, 3, 4, 5];
  psynet.applyArrivalTarget({ group_ready: [entry([0, 1, 2], members, 3)] });
  psynet.applyArrivalTarget({ group_ready: [entry([3], members, 1)] });
  // A snapshot that saw fewer arrivals can't lower the count.
  psynet.applyArrivalTarget({ notice: "1/6 ready", group_ready: [entry([0], members, 1)] });
  assert.deepEqual(psynet.notices, ["3/6 ready", "4/6 ready", "4/6 ready"]);
});

it("drops members who left, but not later joiners missing from an older list", () => {
  const psynet = load();
  psynet.applyArrivalTarget({ group_ready: [entry([0, 1, 4, 5], [0, 1, 2, 3, 4, 5], 3)] });
  assert.deepEqual(psynet.addReadySeats(entry([], [0, 2, 3, 4], 0)).seats, [0, 4]);
  assert.deepEqual(psynet.addReadySeats(entry([], [0, 2, 3], 0, 4)).seats, [0, 4]);
});

it("leaves the notice alone for an entry without notice texts", () => {
  const psynet = load();
  psynet.applyArrivalTarget({ group_ready: [entry([0, 1, 2], [0, 1, 2, 3, 4, 5], 3)] });
  const waiting = { ...entry([0, 1, 2], [0, 1, 2, 3, 4, 5], 3) };
  delete waiting.notices;
  psynet.applyArrivalTarget({ notice: null, group_ready: [waiting] });
  assert.deepEqual(psynet.notices, ["3/6 ready", null]);
});

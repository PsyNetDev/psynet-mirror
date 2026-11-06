import assert from "node:assert/strict";
import { afterEach, it } from "node:test";

import { activate } from "../../psynet/static/scripts/group-prompt.js";

function member(seat) {
  const classes = new Set(["psynet-group-member"]);
  return {
    dataset: { seat: String(seat) },
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
    getAttribute: () => `Member ${seat}`,
    querySelector: () => null,
  };
}

function groupRoot(seats) {
  const members = seats.map(member);
  return {
    isConnected: true,
    querySelector(selector) {
      const seat = selector.match(/data-seat="(\d+)"/);
      return seat ? members.find((m) => m.dataset.seat === seat[1]) : null;
    },
    querySelectorAll(selector) {
      return selector === ".psynet-group-member--answered"
        ? members.filter((m) => m.classList.contains("psynet-group-member--answered"))
        : members;
    },
    ticked: () =>
      members
        .filter((m) => m.classList.contains("psynet-group-member--answered"))
        .map((m) => Number(m.dataset.seat)),
  };
}

function setUp(readySeats = []) {
  const listeners = [];
  globalThis.psynet = { uniqueId: "p1", readySeatsFor: () => readySeats };
  globalThis.window = {
    psynet: globalThis.psynet,
    addEventListener: (type, listener) => listeners.push(listener),
    removeEventListener() {},
  };
  const send = (detail) => listeners.forEach((listener) => listener({ detail }));
  return { send };
}

afterEach(() => {
  delete globalThis.psynet;
  delete globalThis.window;
  delete globalThis.$;
});

it("ticks the members already waiting, then only those still waiting", async () => {
  const { send } = setUp([0, 2]);
  const root = groupRoot([0, 1, 2]);
  await activate({ root, vars: { group_prompt: { group_id: 7, live_ticks: true } } });
  assert.deepEqual(root.ticked(), [0, 2]);

  send({ groupId: 7, seats: [1] });
  assert.deepEqual(root.ticked(), [1]);
  send({ groupId: 8, seats: [] });
  assert.deepEqual(root.ticked(), [1]);
});

it("retries a failed redraw once when another was asked for meanwhile", async (t) => {
  const timers = t.mock.timers;
  timers.enable({ apis: ["setTimeout"] });
  const { send } = setUp();
  const requests = [];
  globalThis.$ = {
    ajax() {
      const request = { done: () => request, fail: (f) => ((request.onFail = f), request) };
      request.always = (f) => ((request.onAlways = f), request);
      requests.push(request);
      return request;
    },
  };
  const root = groupRoot([0]);
  await activate({
    root,
    vars: { group_prompt: { group_id: 7, live_members: true, redraw_token: "t" } },
  });

  send({ groupId: 7, seats: [], members: [0, 1] });
  send({ groupId: 7, seats: [], members: [0, 1] });
  requests[0].onFail();
  requests[0].onAlways();
  assert.equal(requests.length, 2);
  timers.tick(10000);
  requests[1].onAlways();
  assert.equal(requests.length, 2);
});

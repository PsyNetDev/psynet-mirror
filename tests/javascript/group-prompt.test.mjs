import assert from "node:assert/strict";
import { afterEach, it } from "node:test";

import { activate } from "../../psynet/static/scripts/group-prompt.js";

function member(seat) {
  const classes = new Set(["psynet-group-member"]);
  return {
    dataset: { seat: String(seat) },
    classList: {
      add: (name) => classes.add(name),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
    },
    getAttribute: () => `Member ${seat}`,
    querySelector: () => null,
  };
}

function groupRoot(seats) {
  const members = seats.map(member);
  return {
    querySelector(selector) {
      const seat = selector.match(/data-seat="(\d+)"/);
      return seat ? members.find((m) => m.dataset.seat === seat[1]) : null;
    },
    querySelectorAll(selector) {
      if (selector.startsWith(".psynet-group-member--answered")) {
        return members.filter(
          (m) =>
            m.classList.contains("psynet-group-member--answered") ||
            m.classList.contains("psynet-group-member--ran-out-of-time")
        );
      }
      return members;
    },
    ticked: () =>
      members
        .filter((m) => m.classList.contains("psynet-group-member--answered"))
        .map((m) => Number(m.dataset.seat)),
    dashed: () =>
      members
        .filter((m) => m.classList.contains("psynet-group-member--ran-out-of-time"))
        .map((m) => Number(m.dataset.seat)),
  };
}

function setUp(readySeats = [], ranOutOfTime = []) {
  const listeners = [];
  globalThis.psynet = {
    uniqueId: "p1",
    readySeatsFor: () => ({ seats: readySeats, ranOutOfTime }),
  };
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

it("gives members who ran out of time a dash instead of a tick", async () => {
  const { send } = setUp([0, 2], [2]);
  const root = groupRoot([0, 1, 2]);
  await activate({ root, vars: { group_prompt: { group_id: 7, live_ticks: true } } });
  assert.deepEqual([root.ticked(), root.dashed()], [[0], [2]]);

  send({ groupId: 7, seats: [1, 2], ranOutOfTime: [1] });
  assert.deepEqual([root.ticked(), root.dashed()], [[2], [1]]);
});

function mockAjax() {
  const requests = [];
  globalThis.$ = {
    ajax() {
      const request = { abort() {} };
      for (const name of ["done", "fail", "always"]) {
        request[name] = (f) => ((request[name + "Handler"] = f), request);
      }
      requests.push(request);
      return request;
    },
  };
  return requests;
}

const LIVE_MEMBERS = { group_prompt: { group_id: 7, live_members: true, redraw_token: "t" } };

it("redraws only when the members change", async () => {
  const { send } = setUp();
  const requests = mockAjax();
  await activate({ root: groupRoot([0, 1]), vars: LIVE_MEMBERS });

  send({ groupId: 7, seats: [], members: [0, 1] });
  assert.equal(requests.length, 0);
  send({ groupId: 7, seats: [], members: [0] });
  assert.equal(requests.length, 1);
});

it("runs a redraw asked for meanwhile instead of retrying a failed one", async (t) => {
  const timers = t.mock.timers;
  timers.enable({ apis: ["setTimeout"] });
  const { send } = setUp();
  const requests = mockAjax();
  await activate({ root: groupRoot([0]), vars: LIVE_MEMBERS });

  send({ groupId: 7, seats: [], members: [0, 1] });
  send({ groupId: 7, seats: [], members: [0, 1] });
  requests[0].failHandler();
  requests[0].alwaysHandler();
  assert.equal(requests.length, 2);
  timers.tick(10000);
  requests[1].alwaysHandler();
  assert.equal(requests.length, 2);
});

it("ignores a redraw that ends after the page is cleaned up", async (t) => {
  const timers = t.mock.timers;
  timers.enable({ apis: ["setTimeout"] });
  const { send } = setUp();
  const requests = mockAjax();
  const root = groupRoot([0]);
  const cleanup = await activate({ root, vars: LIVE_MEMBERS });

  send({ groupId: 7, seats: [], members: [0, 1] });
  cleanup();
  root.querySelector = root.querySelectorAll = () => {
    throw new Error("the next page was changed");
  };
  requests[0].doneHandler({ html: "<div class='psynet-group-prompt'><div></div></div>" });
  requests[0].failHandler();
  requests[0].alwaysHandler();
  timers.tick(10000);
  assert.equal(requests.length, 1);
});

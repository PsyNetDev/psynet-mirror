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

function groupRoot(seats, leftSeats = []) {
  const members = seats.map(member);
  members
    .filter((m) => leftSeats.includes(Number(m.dataset.seat)))
    .forEach((m) => m.classList.add("psynet-group-member--left"));
  return {
    querySelector(selector) {
      const seat = selector.match(/data-seat="(\d+)"/);
      return seat ? members.find((m) => m.dataset.seat === seat[1]) : null;
    },
    querySelectorAll(selector) {
      if (selector === ".psynet-group-member--answered") {
        return members.filter((m) => m.classList.contains("psynet-group-member--answered"));
      }
      return selector.endsWith(":not(.psynet-group-member--left)")
        ? members.filter((m) => !m.classList.contains("psynet-group-member--left"))
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

it("doesn't redraw for a member who left and is still drawn", async () => {
  const { send } = setUp();
  const requests = mockAjax();
  await activate({ root: groupRoot([0, 1, 2], [2]), vars: LIVE_MEMBERS });

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

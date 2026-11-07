import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { beforeEach, describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = (name) => fs.readFileSync(path.join(ROOT, "psynet/resources/scripts", name), "utf8");
const PAGE_SOCKET = read("page-socket.js");
const SOURCE = read("live-session.js");
const CALLBACKS = ["onView", "onRejected", "onEnded", "onResultSaved", "onRefused"];
const READY = ["pick_numbers", { type: "psynet_ready", message: {} }];

// Stands in for the dallinger.Socket that openExperimentSocket returns.
class FakeSocket {
  constructor(options) {
    this.options = options;
    this.gameChannel = options.gameChannel;
    this.sent = [];
    this.closed = false;
    this.callbacks = Object.fromEntries(
      [...CALLBACKS, "onClock", "onOpen"].map((name) => [name, []])
    );
    for (const name of [...CALLBACKS, "onClock", "onOpen"]) {
      this[name] = (callback) => {
        this.callbacks[name].push(callback);
        return this;
      };
    }
  }
  send(channel, payload) {
    this.sent.push([channel, payload]);
    return this.sent.length;
  }
  close() {
    this.closed = true;
  }
  fire(name, ...args) {
    this.callbacks[name].slice().forEach((callback) => callback(...args));
  }
}

const view = (startedAt) => ({ live_session: { ready: [], started_at: startedAt } });

// The script builds its objects in another realm, so compare JSON copies.
const plain = (value) => JSON.parse(JSON.stringify(value));

let sockets;
let errors;
let token;
let session;
let liveSession;
let pageReady;
let nextPages;
let events;

beforeEach(() => {
  sockets = [];
  errors = [];
  token = "token-1";
  session = {
    initializerId: "pick_numbers",
    sessionId: 7,
    gameChannel: "pick_numbers",
    autoAdvance: true,
  };
  pageReady = true;
  nextPages = 0;
  events = new EventTarget();
  const context = {
    addEventListener: events.addEventListener.bind(events),
    console: { error: (error) => errors.push(error.message) },
    dallinger: {
      pageScope: "load-1",
      openExperimentSocket(options) {
        const socket = new FakeSocket(options);
        sockets.push(socket);
        return socket;
      },
    },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(PAGE_SOCKET, context);
  vm.runInContext(SOURCE, context);
  liveSession = context.PsyNetLiveSession.create(
    () => session,
    () => token,
    { ready: () => pageReady, nextPage: () => nextPages++ }
  );
});

describe("psynet.liveSession", () => {
  it("joins the page's session once, scoped by the page token and page load", () => {
    assert.equal(sockets.length, 0);
    liveSession.onView(() => {});
    liveSession.send("pick", { number: 7 });
    assert.equal(sockets.length, 1);
    assert.deepEqual(plain(sockets[0].options), {
      session: 7,
      gameChannel: "pick_numbers",
      scope: "token-1.load-1",
    });
    assert.equal(liveSession.socket, sockets[0]);
    assert.ok(!Object.keys(liveSession).includes("socket"));
    assert.ok(!Object.keys(liveSession).includes("resetPageState"));
  });

  it("sends a message's type and fields on the game's channel", () => {
    assert.equal(liveSession.send("pick", { number: 7 }), 1);
    assert.equal(liveSession.send("pass"), 2);
    assert.deepEqual(plain(sockets[0].sent), [
      ["pick_numbers", { type: "pick", message: { number: 7 } }],
      ["pick_numbers", { type: "pass" }],
    ]);
  });

  it("passes callbacks to the socket and returns itself", () => {
    const callback = () => {};
    for (const name of CALLBACKS) {
      assert.equal(liveSession[name](callback), liveSession);
      assert.equal(sockets[0].callbacks[name].at(-1), callback);
    }
  });

  it("says the player is ready after the first clock measurement of each connection", () => {
    liveSession.send("pick", { number: 7 });
    assert.deepEqual(plain(sockets[0].sent), [
      ["pick_numbers", { type: "pick", message: { number: 7 } }],
    ]);
    for (const reconnect of [1, 2]) {
      sockets[0].fire("onOpen", {});
      sockets[0].fire("onClock", {});
      sockets[0].fire("onClock", {});
    }
    assert.deepEqual(plain(sockets[0].sent.slice(1)), [READY, READY]);
  });

  it("calls onStarted once, with the first view after the start", () => {
    const started = [];
    liveSession.onStarted(() => {
      throw new Error("a page's mistake");
    });
    liveSession.onStarted((v) => started.push(["early", v]));
    sockets[0].fire("onView", view(null));
    sockets[0].fire("onView", null);
    assert.deepEqual(started, []);
    sockets[0].fire("onView", view(4));
    sockets[0].fire("onView", view(4));
    liveSession.onStarted((v) => started.push(["late", v]));
    assert.deepEqual(plain(started), [
      ["early", view(4)],
      ["late", view(4)],
    ]);
    assert.deepEqual(errors, ["a page's mistake"]);
  });

  it("disables elements until the start", () => {
    const pick = { disabled: false };
    const pass = { disabled: false };
    assert.equal(liveSession.disableUntilStarted(pick, pass), liveSession);
    assert.deepEqual([pick.disabled, pass.disabled], [true, true]);
    sockets[0].fire("onView", view(null));
    assert.deepEqual([pick.disabled, pass.disabled], [true, true]);
    sockets[0].fire("onView", view(4));
    assert.deepEqual([pick.disabled, pass.disabled], [false, false]);

    const late = { disabled: false };
    liveSession.disableUntilStarted(late);
    assert.equal(late.disabled, false);
  });

  it("says whether the session has started, up to date in onView, without joining", () => {
    assert.equal(liveSession.started, false);
    assert.equal(sockets.length, 0);
    const seen = [];
    liveSession.onView(() => seen.push(liveSession.started));
    sockets[0].fire("onView", view(null));
    sockets[0].fire("onView", view(4));
    assert.deepEqual(seen, [false, true]);
    assert.equal(liveSession.started, true);
    assert.ok(Object.keys(liveSession).includes("started"));
    token = "token-2";
    assert.equal(liveSession.started, false);
  });

  it("moves on once the result is saved, or the connection is refused", () => {
    liveSession.onView(() => {});
    sockets[0].fire("onResultSaved");
    assert.equal(nextPages, 1);
    sockets[0].fire("onRefused", 1008, "Gone");
    assert.equal(nextPages, 2);

    token = "token-2";
    session = { ...session, autoAdvance: false };
    liveSession.onView(() => {});
    sockets[1].fire("onResultSaved");
    sockets[1].fire("onRefused", 1008, "Gone");
    assert.equal(nextPages, 2);
  });

  it("waits for the page to be ready before moving on, on that page only", () => {
    pageReady = false;
    liveSession.onView(() => {});
    sockets[0].fire("onResultSaved");
    assert.equal(nextPages, 0);
    events.dispatchEvent(new Event("timelinePageReady"));
    assert.equal(nextPages, 1);
    events.dispatchEvent(new Event("timelinePageReady"));
    assert.equal(nextPages, 1);

    sockets[0].fire("onRefused", 1008, "Gone");
    token = "token-2";
    events.dispatchEvent(new Event("timelinePageReady"));
    assert.equal(nextPages, 1);
  });

  it("leaves the session when the page changes", () => {
    liveSession.send("pick", { number: 1 });
    token = "token-2";
    liveSession.send("pick", { number: 2 });
    assert.equal(sockets[0].closed, true);
    assert.equal(sockets[1].options.scope, "token-2.load-1");
    assert.deepEqual(plain(sockets[1].sent), [
      ["pick_numbers", { type: "pick", message: { number: 2 } }],
    ]);

    liveSession.resetPageState();
    assert.equal(sockets[1].closed, true);
    assert.equal(sockets.length, 2);
  });

  it("says whether the group has a session, without joining it", () => {
    assert.equal(liveSession.hasSession, true);
    session = { initializerId: "pick_numbers", sessionId: null, gameChannel: null };
    assert.equal(liveSession.hasSession, false);
    session = undefined;
    assert.equal(liveSession.hasSession, false);
    assert.equal(sockets.length, 0);
  });

  it("explains a page with no session or no page token", () => {
    session = undefined;
    assert.throws(() => liveSession.send("pick"), /control isn't a LiveSessionControl/);
    session = { initializerId: "pick_numbers", sessionId: null, gameChannel: null };
    assert.throws(
      () => liveSession.onView(() => {}),
      /hasn't started a live session at the initializer "pick_numbers"/
    );
    session = { initializerId: "pick_numbers", sessionId: 7, gameChannel: "pick_numbers" };
    token = null;
    assert.throws(() => liveSession.send("pick"), /needs a FLASK_SECRET_KEY/);
    assert.equal(sockets.length, 0);
  });
});

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, it, mock } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = (name) => fs.readFileSync(path.join(ROOT, "psynet/resources/scripts", name), "utf8");
const SOURCE = read("live-session.js");
const CALLBACKS = ["onView", "onRejected", "onEnded", "onResultSaved", "onRefused"];
// The callbacks psynet.liveSession hands straight to the socket.
const PASSED_ON = CALLBACKS.filter((name) => name !== "onView");
const AWAY_NOTICE = "psynet-player-away-notice";
const READY = ["pick_numbers", { type: "psynet_ready", message: {} }];

// Stands in for the dallinger.Socket that openExperimentSocket returns.
class FakeSocket {
  constructor(options) {
    this.options = options;
    this.gameChannel = options.gameChannel;
    this.sent = [];
    this.closed = false;
    // Stands in for the ReconnectingWebSocket.
    this.raw = new EventTarget();
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
  sessionTime() {
    return this.time ?? null;
  }
  fire(name, ...args) {
    this.callbacks[name].slice().forEach((callback) => callback(...args));
  }
  // As Dallinger does: the view, then its details, which say whether it's
  // the final view.
  view(view, ended = null) {
    this.fire("onView", view, { ended: ended });
  }
}

const view = (startedAt, away = [], endsAt = null) => ({
  live_session: { ready: [], started_at: startedAt, ends_at: endsAt, away: away },
});

// The script builds its objects in another realm, so compare JSON copies.
const plain = (value) => JSON.parse(JSON.stringify(value));

let sockets;
let errors;
let leavePage;
let context;
let session;
let liveSession;
let pageReady;
let nextPages;
let events;
let notices;
let nextButtonHidden;

beforeEach(() => {
  sockets = [];
  errors = [];
  session = {
    gameId: "pick_numbers",
    sessionId: 7,
    gameChannel: "pick_numbers",
    autoAdvance: true,
    playerLeftMessage: "Another player has left the game.",
  };
  pageReady = true;
  notices = [];
  nextButtonHidden = [];
  nextPages = 0;
  events = new EventTarget();
  context = {
    addEventListener: events.addEventListener.bind(events),
    // Looked up at each call, so a test's mocked timers apply.
    // Unreferenced, so a page's repeating connection check doesn't keep the
    // test process alive.
    setTimeout: (...args) => {
      const timer = setTimeout(...args);
      timer?.unref?.();
      return timer;
    },
    clearTimeout: (...args) => clearTimeout(...args),
    console: { error: (error) => errors.push(error.message) },
    WebSocket: { OPEN: 1 },
    dallinger: {
      pageScope: "load-1",
      openExperimentSocket(options) {
        const socket = new FakeSocket(options);
        sockets.push(socket);
        return socket;
      },
    },
  };
  Object.defineProperty(context, "Date", { get: () => Date });
  context.window = context;
  vm.createContext(context);
  vm.runInContext(SOURCE, context);
  liveSession = context.PsyNetLiveSession.create(
    () => session,
    {
      websocketScope: () => "scope-7",
      ready: () => pageReady,
      nextPage: () => nextPages++,
      setNextButtonHidden: (hidden) => nextButtonHidden.push(hidden),
      showNotice: (id, text) => notices.push([id, text]),
    }
  );
  leavePage = liveSession.activatePage();
});

// Moves the participant on to another page with a LiveSessionControl, as
// PsyNet does: the old page's cleanup, then the new page's code.
function changePage() {
  leavePage();
  leavePage = liveSession.activatePage();
}

afterEach(() => {
  mock.timers.reset();
});

describe("psynet.liveSession", () => {
  it("joins the page's session once, scoped by the participant's scope and page load", () => {
    assert.equal(sockets.length, 0);
    liveSession.onView(() => {});
    liveSession.send("pick", { number: 7 });
    assert.equal(sockets.length, 1);
    assert.deepEqual(plain(sockets[0].options), {
      session: 7,
      gameChannel: "pick_numbers",
      scope: "scope-7.load-1.1",
    });
    assert.equal(liveSession.socket, sockets[0]);
    assert.ok(!Object.keys(liveSession).includes("socket"));
    assert.ok(!Object.keys(liveSession).includes("activatePage"));
  });

  it("is created by the control's page code, once for the pages a document shows", () => {
    const shown = [];
    const psynet = {
      var: { liveSession: { sessionId: null, noSessionMessage: "No game." } },
      showStatusNotice: (id, text) => shown.push([id, text]),
    };
    const leave = context.PsyNetLiveSession.activatePage(psynet);
    const created = psynet.liveSession;
    assert.equal(created.hasSession, false);
    assert.deepEqual(shown, [["psynet-no-session-notice", "No game."]]);
    leave();
    assert.deepEqual(shown.at(-1), ["psynet-no-session-notice", null]);

    psynet.var = { liveSession: session };
    context.PsyNetLiveSession.activatePage(psynet);
    assert.equal(psynet.liveSession, created);
    assert.equal(created.hasSession, true);
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
    for (const name of PASSED_ON) {
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
    sockets[0].view(view(null));
    sockets[0].view(null);
    assert.deepEqual(started, []);
    sockets[0].view(view(4));
    sockets[0].view(view(4));
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
    sockets[0].view(view(null));
    assert.deepEqual([pick.disabled, pass.disabled], [true, true]);
    sockets[0].view(view(4));
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
    sockets[0].view(view(null));
    sockets[0].view(view(4));
    assert.deepEqual(seen, [false, true]);
    assert.equal(liveSession.started, true);
    assert.ok(Object.keys(liveSession).includes("started"));
    changePage();
    assert.equal(liveSession.started, false);
  });

  it("moves on once the result is saved, or the connection is refused", () => {
    liveSession.onView(() => {});
    sockets[0].fire("onResultSaved");
    assert.equal(nextPages, 1);
    sockets[0].fire("onRefused", 1008, "Gone");
    assert.equal(nextPages, 2);

    changePage();
    session = { ...session, autoAdvance: false };
    liveSession.onView(() => {});
    sockets[1].fire("onResultSaved");
    sockets[1].fire("onRefused", 1008, "Gone");
    assert.equal(nextPages, 2);
    // Only the page that moves on by itself hides its Next button.
    assert.deepEqual(nextButtonHidden, [true]);
  });

  it("shows the result for the control's show_result_for seconds before moving on", () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    session = { ...session, showResultFor: 8 };
    assert.equal(liveSession.showResultFor, 8);
    liveSession.onView(() => {});
    sockets[0].fire("onResultSaved");
    mock.timers.tick(7999);
    assert.equal(nextPages, 0);
    mock.timers.tick(1);
    assert.equal(nextPages, 1);

    // A page that has gone doesn't move the next one on.
    changePage();
    liveSession.onView(() => {});
    sockets[1].fire("onResultSaved");
    changePage();
    mock.timers.tick(8000);
    assert.equal(nextPages, 1);
  });

  it("counts down to the end of a game with a duration", () => {
    liveSession.onView(() => {});
    assert.equal(liveSession.secondsLeft(), null);
    sockets[0].view(view(5, [], 45));
    assert.equal(liveSession.duration, 40);
    sockets[0].time = 30;
    assert.equal(liveSession.secondsLeft(), 15);
    sockets[0].time = 50;
    assert.equal(liveSession.secondsLeft(), 0);
  });

  it("shows the Next button again once the connection has been down for ten seconds", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    liveSession.onView(() => {});
    // Hidden from the start, for ten seconds even if it never connects.
    assert.deepEqual(nextButtonHidden, [true]);
    mock.timers.tick(9999);
    sockets[0].raw.dispatchEvent(new Event("open"));
    mock.timers.tick(60000);
    assert.deepEqual(nextButtonHidden, [true, true]);

    sockets[0].raw.dispatchEvent(new Event("close"));
    mock.timers.tick(5000);
    // A failed attempt to reconnect doesn't start the ten seconds again.
    sockets[0].raw.dispatchEvent(new Event("close"));
    mock.timers.tick(4999);
    assert.deepEqual(nextButtonHidden, [true, true]);
    mock.timers.tick(1);
    assert.deepEqual(nextButtonHidden, [true, true, false]);
    sockets[0].raw.dispatchEvent(new Event("open"));
    assert.deepEqual(nextButtonHidden, [true, true, false, true]);

    // A page that has gone leaves the next page's button alone, whether it
    // went while its connection was down
    sockets[0].raw.dispatchEvent(new Event("close"));
    changePage();
    mock.timers.tick(60000);
    assert.deepEqual(nextButtonHidden, [true, true, false, true]);
    // or up.
    liveSession.onView(() => {});
    sockets[1].raw.dispatchEvent(new Event("open"));
    const shown = nextButtonHidden.length;
    changePage();
    sockets[1].raw.dispatchEvent(new Event("close"));
    mock.timers.tick(60000);
    assert.equal(nextButtonHidden.length, shown);
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
    changePage();
    events.dispatchEvent(new Event("timelinePageReady"));
    assert.equal(nextPages, 1);
  });

  it("leaves the session when the page changes", () => {
    liveSession.send("pick", { number: 1 });
    changePage();
    assert.equal(sockets[0].closed, true);
    liveSession.send("pick", { number: 2 });
    // The engine counts each connection as a page of its own.
    assert.equal(sockets[1].options.scope, "scope-7.load-1.2");
    assert.deepEqual(plain(sockets[1].sent), [
      ["pick_numbers", { type: "pick", message: { number: 2 } }],
    ]);

    leavePage();
    assert.equal(sockets[1].closed, true);
    assert.equal(sockets.length, 2);
  });

  it("says whether the group has a session, without joining it", () => {
    assert.equal(liveSession.hasSession, true);
    session = { gameId: "pick_numbers", sessionId: null, gameChannel: null };
    assert.equal(liveSession.hasSession, false);
    session = undefined;
    assert.equal(liveSession.hasSession, false);
    assert.equal(sockets.length, 0);
  });

  it("shows the control's notice on a page with no session, until the page ends", () => {
    assert.deepEqual(notices, []);
    session = {
      gameId: "pick_numbers",
      sessionId: null,
      gameChannel: null,
      noSessionMessage: null,
    };
    changePage();
    assert.deepEqual(
      notices.filter(([, text]) => text !== null),
      []
    );
    session = { ...session, noSessionMessage: "Your group couldn't start the game." };
    changePage();
    assert.deepEqual(notices.at(-1), [
      "psynet-no-session-notice",
      "Your group couldn't start the game.",
    ]);
    leavePage();
    assert.deepEqual(notices.at(-1), ["psynet-no-session-notice", null]);
    assert.equal(sockets.length, 0);
  });

  it("explains a page with no session", () => {
    session = undefined;
    assert.throws(() => liveSession.send("pick"), /control isn't a LiveSessionControl/);
    session = { gameId: "pick_numbers", sessionId: null, gameChannel: null };
    assert.throws(
      () => liveSession.onView(() => {}),
      /hasn't started a live session at the PlayLiveGame "pick_numbers"/
    );
    assert.equal(sockets.length, 0);
  });

  it("passes on the final view, with ended up to date, and no view after it", () => {
    const seen = [];
    liveSession.onView((v, details) => seen.push([v.n, liveSession.ended, details]));
    sockets[0].view({ ...view(4), n: 1 });
    sockets[0].view({ ...view(4), n: 2 }, "finished");
    sockets[0].view({ ...view(4), n: 3 });
    sockets[0].fire("onEnded", "finished", { ...view(4), n: 2 });
    assert.deepEqual(plain(seen), [
      [1, false, { ended: null }],
      [2, true, { ended: "finished" }],
    ]);
    assert.equal(liveSession.ended, true);
    changePage();
    assert.equal(liveSession.ended, false);
  });

  it("passes the final view that comes with the ending to onView, before onEnded", () => {
    const seen = [];
    liveSession.onView((v, details) => seen.push(["view", v === null ? null : v.n, details]));
    liveSession.onEnded((reason, v) => seen.push(["ended", reason, v === null ? null : v.n]));
    sockets[0].fire("onEnded", "finished", { ...view(4), n: 5 });
    sockets[0].view({ ...view(4), n: 5 }, "finished");
    assert.deepEqual(plain(seen), [
      ["view", 5, null],
      ["ended", "finished", 5],
    ]);

    // A failed session's final view can be null.
    changePage();
    seen.length = 0;
    liveSession.onView((v, details) => seen.push(["view", v, details]));
    sockets[1].fire("onEnded", "failed", null);
    assert.deepEqual(plain(seen), [["view", null, null]]);
  });

  it("keeps controls disabled on a page that opens after the session has ended", () => {
    const pick = { disabled: false };
    liveSession.disableUntilStarted(pick);
    sockets[0].fire("onEnded", "finished", view(4));
    const late = { disabled: false };
    liveSession.disableUntilStarted(late);
    assert.deepEqual([pick.disabled, late.disabled], [true, true]);
    assert.equal(liveSession.started, false);

    // Nor on a page that played, then adds the callback after the end.
    changePage();
    liveSession.onView(() => {});
    sockets[1].view(view(4));
    sockets[1].view(view(4), "finished");
    const afterTheEnd = { disabled: false };
    liveSession.disableUntilStarted(afterTheEnd);
    assert.equal(afterTheEnd.disabled, true);
  });

  it("logs the error of a callback added while players are away", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    liveSession.onView(() => {});
    sockets[0].view(view(4, ["2"]));
    mock.timers.tick(5000);
    liveSession.onPlayersAway(() => {
      throw new Error("a page's mistake");
    });
    assert.deepEqual(errors, ["a page's mistake"]);
  });

  it("reports players who have been away for five seconds, and shows the notice", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    const reports = [];
    liveSession.onPlayersAway((players) => reports.push(players));
    sockets[0].view(view(4, ["2"]));
    mock.timers.tick(4999);
    assert.deepEqual(reports, []);
    mock.timers.tick(1);
    sockets[0].view(view(4, ["2", "3"]));
    mock.timers.tick(5000);
    sockets[0].view(view(4, ["3"]));
    sockets[0].view(view(4, []));
    assert.deepEqual(plain(reports), [["2"], ["2", "3"], ["3"], []]);
    assert.deepEqual(plain(notices), [
      [AWAY_NOTICE, "Another player has left the game."],
      [AWAY_NOTICE, "Another player has left the game."],
      [AWAY_NOTICE, "Another player has left the game."],
      [AWAY_NOTICE, null],
    ]);
  });

  it("doesn't report a player who comes back within five seconds", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    const reports = [];
    liveSession.onPlayersAway((players) => reports.push(players));
    sockets[0].view(view(4, ["2"]));
    mock.timers.tick(3000);
    sockets[0].view(view(4, []));
    mock.timers.tick(5000);
    assert.deepEqual(reports, []);
    assert.deepEqual(notices, []);
  });

  it("tells a callback added later who is away at once", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    liveSession.onView(() => {});
    sockets[0].view(view(4, ["2"]));
    mock.timers.tick(5000);
    const reports = [];
    assert.equal(liveSession.onPlayersAway((players) => reports.push(players)), liveSession);
    assert.deepEqual(plain(reports), [["2"]]);
  });

  it("reports no one away once the session ends, and stops when the page changes", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    const reports = [];
    liveSession.onPlayersAway((players) => reports.push(players));
    sockets[0].view(view(4, ["2"]));
    mock.timers.tick(5000);
    sockets[0].view(view(4, ["2"]), "finished");
    assert.deepEqual(plain(reports), [["2"], []]);

    changePage();
    liveSession.onPlayersAway((players) => reports.push(["next page", ...players]));
    sockets[1].view(view(4, ["2"]));
    mock.timers.tick(5000);
    sockets[1].view(view(4, ["2", "3"]));
    assert.deepEqual(plain(notices.at(-1)), [AWAY_NOTICE, "Another player has left the game."]);
    changePage();
    assert.equal(liveSession.started, false);
    mock.timers.tick(5000);
    assert.deepEqual(plain(reports), [["2"], [], ["next page", "2"]]);
    assert.deepEqual(plain(notices.at(-1)), [AWAY_NOTICE, null]);
  });

  it("predicts with the page's predict callback, leaving out PsyNet's own messages", () => {
    const seen = [];
    assert.equal(
      liveSession.predict((v, type, message, sentAt) => {
        seen.push([type, message, sentAt]);
        v.chosen = true;
      }),
      liveSession
    );
    const predict = sockets[0].options.predict;
    const shown = { chosen: false };
    assert.equal(predict(shown, { type: "choose", message: { round: 1 } }, 12.5), undefined);
    assert.equal(shown.chosen, true);
    const before = { chosen: false };
    assert.equal(predict(before, READY[1], 13), before);
    assert.deepEqual(plain(seen), [["choose", { round: 1 }, 12.5]]);

    sockets[0].predictedView = () => ({ chosen: true });
    assert.deepEqual(plain(liveSession.predictedView()), { chosen: true });

    changePage();
    liveSession.onView(() => {});
    const unchanged = { chosen: false };
    assert.equal(sockets[1].options.predict(unchanged, { type: "choose", message: {} }), unchanged);
  });

  it("interpolates with the page's interpolate callback", () => {
    assert.throws(() => liveSession.interpolatedView(), /interpolate's callback/);
    const interpolate = sockets[0].options.interpolate;
    const a = { x: 0 };
    const b = { x: 10 };
    assert.equal(interpolate(a, b, 0.5), b);
    const seen = [];
    assert.equal(
      liveSession.interpolate((from, to, fraction) => {
        seen.push(fraction);
        return { x: from.x + (to.x - from.x) * fraction };
      }),
      liveSession
    );
    assert.deepEqual(plain(interpolate(a, b, 0.25)), { x: 2.5 });
    assert.deepEqual(plain(seen), [0.25]);
    assert.deepEqual(plain(a), { x: 0 });

    sockets[0].interpolatedView = () => ({ x: 4 });
    assert.deepEqual(plain(liveSession.interpolatedView()), { x: 4 });

    changePage();
    liveSession.onView(() => {});
    assert.equal(sockets[1].options.interpolate(a, b, 0.5), b);
    assert.throws(() => liveSession.interpolatedView(), /interpolate's callback/);
  });

  it("shows no notice when the control has no player_left_message", () => {
    mock.timers.enable({ apis: ["setTimeout", "Date"] });
    session = { ...session, playerLeftMessage: null };
    const reports = [];
    liveSession.onPlayersAway((players) => reports.push(players));
    sockets[0].view(view(4, ["2"]));
    mock.timers.tick(5000);
    assert.deepEqual(plain(reports), [["2"]]);
    assert.deepEqual(notices, []);
  });
});

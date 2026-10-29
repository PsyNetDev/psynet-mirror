import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { beforeEach, describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/page-socket.js"),
  "utf8"
);

// Stands in for the dallinger.Socket that openExperimentSocket returns.
class FakeSocket {
  constructor(options) {
    this.options = options;
    this.sent = [];
    this.closed = false;
    this.refused = false;
    this.raw = { readyState: 0 };
    this.callbacks = { direct: [], open: [], refused: [] };
  }
  send(channel, payload) {
    if (!this.refused && !this.closed) this.sent.push([channel, payload]);
  }
  onDirect(callback) {
    this.callbacks.direct.push(callback);
  }
  onOpen(callback) {
    this.callbacks.open.push(callback);
  }
  onRefused(callback) {
    this.callbacks.refused.push(callback);
  }
  close() {
    this.closed = true;
  }
  // Dallinger's Socket drops every send once the server refuses it.
  refuse(code, reason) {
    this.refused = true;
    this.fire("refused", code, reason);
  }
  fire(kind, ...args) {
    this.callbacks[kind].forEach((callback) => callback(...args));
  }
}

let sockets;
let token;
let pageSocket;
let errors;

beforeEach(() => {
  sockets = [];
  errors = [];
  token = "token-1";
  const context = {
    WebSocket: { OPEN: 1 },
    setTimeout,
    console: { error: (error) => errors.push(error) },
    dallinger: {
      openExperimentSocket(options) {
        const socket = new FakeSocket(options);
        sockets.push(socket);
        return socket;
      },
    },
  };
  context.window = context;
  vm.runInNewContext(SOURCE, context);
  pageSocket = context.PsyNetPageSocket.create(() => token);
});

describe("psynet.websocket", () => {
  it("opens one socket, scoped by the page token, when first used", () => {
    assert.equal(sockets.length, 0);
    pageSocket.handle("move", () => {});
    pageSocket.send("ready");
    assert.equal(sockets.length, 1);
    assert.equal(sockets[0].options.scope, "token-1");
  });

  it("refuses to open without a page token", () => {
    token = null;
    const moves = [];
    assert.throws(() => pageSocket.send("ready"), /no page token/);
    assert.throws(() => pageSocket.handle("move", (message) => moves.push(message)), /no page token/);
    assert.equal(sockets.length, 0);

    token = "token-1";
    pageSocket.connect();
    sockets[0].fire("direct", { type: "move", message: { x: 1 } });
    assert.deepEqual(moves, []);
  });

  it("sends typed messages on the psynet channel, with the message context", () => {
    pageSocket.setMessageContext({ round: 2 });
    pageSocket.setMessageContext({ trial: 3 });
    pageSocket.send("move", { x: 1 });
    pageSocket.send("ready");
    assert.deepEqual(JSON.parse(JSON.stringify(sockets[0].sent)), [
      ["psynet", { type: "move", message: { round: 2, trial: 3, x: 1 } }],
      ["psynet", { type: "ready" }],
    ]);
  });

  it("passes each message to the handlers for its type until they unsubscribe", () => {
    const moves = [];
    const unsubscribe = pageSocket.handle("move", (message) => moves.push(message));
    pageSocket.handle("score", () => moves.push("wrong handler"));
    sockets[0].fire("direct", { type: "move", message: { x: 1 } });
    sockets[0].fire("direct", null);
    unsubscribe();
    sockets[0].fire("direct", { type: "move", message: { x: 2 } });
    assert.deepEqual(JSON.parse(JSON.stringify(moves)), [{ x: 1 }]);
  });

  it("calls an onConnect callback at once, with the last open event, if the connection is already open", async () => {
    pageSocket.send("ready");
    sockets[0].raw.readyState = 1;
    const reopen = { isReconnect: true };
    sockets[0].fire("open", reopen);
    const opens = [];
    pageSocket.onConnect((event) => opens.push(event));
    pageSocket.onConnect(() => opens.push("unsubscribed"))();
    assert.deepEqual(opens, []);
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(opens.length, 1);
    assert.equal(opens[0], reopen);
  });

  it("calls onConnect callbacks each time the connection opens", () => {
    const opens = [];
    pageSocket.onConnect((event) => opens.push(event.isReconnect));
    sockets[0].fire("open", { isReconnect: false });
    sockets[0].fire("open", { isReconnect: true });
    assert.deepEqual(opens, [false, true]);
  });

  it("keeps a handler's error from reaching the other handlers", () => {
    const moves = [];
    pageSocket.handle("move", () => {
      throw new Error("broken handler");
    });
    pageSocket.handle("move", (message) => moves.push(message));
    sockets[0].fire("direct", { type: "move", message: 1 });
    assert.deepEqual(moves, [1]);
    assert.equal(errors.length, 1);
    assert.match(errors[0].message, /broken handler/);
  });

  it("passes on types named like an object's own properties only to their handlers", () => {
    const received = [];
    pageSocket.handle("move", () => {});
    sockets[0].fire("direct", { type: "constructor", message: 1 });
    sockets[0].fire("direct", { type: "__proto__", message: 2 });
    pageSocket.handle("toString", (message) => received.push(message));
    sockets[0].fire("direct", { type: "toString", message: 3 });
    assert.deepEqual(received, [3]);
    assert.deepEqual(errors, []);
  });

  it("opens no new socket after the server refuses it", () => {
    pageSocket.send("ready");
    sockets[0].refuse(1008, "not the current page");
    pageSocket.send("ready");
    pageSocket.handle("move", () => {});
    pageSocket.onConnect(() => {});
    assert.equal(sockets.length, 1);
    assert.equal(sockets[0].sent.length, 1);
  });

  it("replaces a socket opened with an earlier page's token", () => {
    pageSocket.send("ready");
    sockets[0].refuse(1008, "not the current page");
    token = "token-2";
    pageSocket.send("ready");
    assert.equal(sockets[0].closed, true);
    assert.equal(sockets.length, 2);
    assert.equal(sockets[1].options.scope, "token-2");
    assert.equal(sockets[1].sent.length, 1);
  });

  it("closes on a new page, and reopens with that page's token", () => {
    const moves = [];
    pageSocket.handle("move", (message) => moves.push(message));
    pageSocket.resetPageState();
    assert.equal(sockets[0].closed, true);

    token = "token-2";
    pageSocket.send("ready");
    assert.equal(sockets.length, 2);
    assert.equal(sockets[1].options.scope, "token-2");
    sockets[1].fire("direct", { type: "move", message: { x: 1 } });
    assert.deepEqual(moves, []);
  });

  it("discards the page's handlers and context on a reset, even if the token stays the same", () => {
    const moves = [];
    pageSocket.setMessageContext({ round: 1 });
    pageSocket.handle("move", (message) => moves.push(message));
    pageSocket.resetPageState();

    pageSocket.send("move", { x: 1 });
    sockets[1].fire("direct", { type: "move", message: { x: 2 } });
    assert.deepEqual(moves, []);
    assert.deepEqual(JSON.parse(JSON.stringify(sockets[1].sent)), [
      ["psynet", { type: "move", message: { x: 1 } }],
    ]);
  });

  it("discards an earlier page's handlers, callbacks and context when the token changes", () => {
    const received = [];
    pageSocket.setMessageContext({ round: 1 });
    pageSocket.handle("move", () => received.push("old handler"));
    pageSocket.onConnect(() => received.push("old onConnect"));

    token = "token-2";
    pageSocket.setMessageContext({ trial: 2 });
    pageSocket.send("move", { x: 1 });
    sockets[1].fire("direct", { type: "move", message: {} });
    sockets[1].fire("open", { isReconnect: false });

    assert.equal(sockets[0].closed, true);
    assert.deepEqual(received, []);
    assert.deepEqual(JSON.parse(JSON.stringify(sockets[1].sent)), [
      ["psynet", { type: "move", message: { trial: 2, x: 1 } }],
    ]);
  });
});

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/websocket-channel.js"),
  "utf8"
);

class FakeSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.sent = [];
    FakeSocket.last = this;
  }
  send(data) {
    this.sent.push(data);
  }
  close() {}
}

function loadChannelModule({ refusals = [], warnings = [] } = {}) {
  const window = {};
  vm.runInNewContext(SOURCE, {
    window,
    location: { protocol: "http:", host: "localhost" },
    dallinger: {
      identity: { participantId: "1" },
      stopReconnectingIfRefused: (socket, callback) =>
        refusals.push({ socket, callback }),
    },
    psynetTemplateData: { websocketScope: "scope" },
    ReconnectingWebSocket: FakeSocket,
    WebSocket: { OPEN: 1 },
    setInterval,
    clearInterval,
    setTimeout,
    console: { ...console, warn: (message) => warnings.push(message) },
  });
  return window.PsyNetWebSocketChannel;
}

it("routes directed, channel and probe frames to the right callbacks", () => {
  const channel = "psynet_timeline_hold_1";
  const calls = [];
  const connection = loadChannelModule().connect({
    channel,
    confirmListening: true,
    onOpen: () => calls.push(["open"]),
    onMessage: (message) => calls.push(["message", message.type]),
    onDirect: (message) => calls.push(["direct", message.type]),
  });
  const socket = FakeSocket.last;
  const deliver = (data) => socket.onmessage({ data });

  socket.onopen({});
  // Directed frames can arrive before the probe echo runs onOpen.
  deliver('dallinger_direct:{"type":"early"}');
  assert.deepEqual(calls, [["direct", "early"]]);
  deliver(socket.sent[0]);
  assert.deepEqual(calls.slice(1), [["open"]]);

  deliver('dallinger_direct:{"type":"timeline_hold_wake"}');
  // A forged wake on the public channel must never reach onDirect.
  deliver(`${channel}:{"type":"timeline_hold_wake","targets":[]}`);
  assert.deepEqual(calls.slice(2), [
    ["direct", "timeline_hold_wake"],
    ["message", "timeline_hold_wake"],
  ]);
  connection.close();
  deliver('dallinger_direct:{"type":"after_close"}');
  assert.equal(calls.length, 4);
});

it("stops reconnecting and warns when the server refuses the channel", () => {
  const refusals = [];
  const warnings = [];
  loadChannelModule({ refusals, warnings }).connect({ channel: "chat" });

  assert.equal(refusals.length, 1);
  assert.equal(refusals[0].socket, FakeSocket.last);
  refusals[0].callback(1008, "refused by the experiment");
  assert.deepEqual(warnings, [
    'The server refused WebSocket channel "chat" (code 1008: refused by the experiment); not reconnecting.',
  ]);
});

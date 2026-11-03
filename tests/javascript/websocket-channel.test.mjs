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

function loadChannelModule() {
  const window = {};
  vm.runInNewContext(SOURCE, {
    window,
    location: { protocol: "http:", host: "localhost" },
    dallinger: { identity: { participantId: "1" } },
    psynetTemplateData: { websocketScope: "scope" },
    ReconnectingWebSocket: FakeSocket,
    WebSocket: { OPEN: 1 },
    setInterval,
    clearInterval,
    setTimeout,
    console,
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
  assert.deepEqual(calls, []);
  deliver(socket.sent[0]);
  assert.deepEqual(calls, [["open"]]);

  deliver('dallinger_direct:{"type":"timeline_hold_wake"}');
  deliver(`${channel}:{"type":"chat"}`);
  assert.deepEqual(calls.slice(1), [
    ["direct", "timeline_hold_wake"],
    ["message", "chat"],
  ]);
  connection.close();
});

import assert from "node:assert/strict";
import { it } from "node:test";

import { activate } from "../../psynet/static/scripts/time-limit.js";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

it("counts down from when the page arrived, not from when the script ran", async () => {
  globalThis.window = { setTimeout, clearTimeout };
  const label = { textContent: "" };
  const root = { querySelectorAll: () => [label], isConnected: true };
  const submissions = [];
  const psynet = {
    pageReady: true,
    pageReceivedAt: Date.now() - 3000,
    nextPage: (rawAnswer, metadata) => submissions.push(metadata),
  };

  const deactivate = activate({ root, vars: { timeLimit: { secondsLeft: 10 } }, psynet });
  assert.equal(label.textContent, 7);
  deactivate();

  psynet.pageReceivedAt = Date.now() - 10000;
  activate({ root, vars: { timeLimit: { secondsLeft: 10 } }, psynet });
  assert.equal(label.textContent, 1);
  await flush();
  assert.deepEqual(submissions, [{ time_limit_reached: true }]);
});

it("resumes the countdown when the server's deadline is still to come", async () => {
  globalThis.window = { setTimeout, clearTimeout };
  const label = { textContent: "" };
  const root = { querySelectorAll: () => [label], isConnected: true };
  let calls = 0;
  const psynet = {
    pageReady: true,
    pageReceivedAt: Date.now() - 10000,
    nextPage: (rawAnswer, metadata, blobs, onRejection) => {
      calls += 1;
      onRejection({ submission: "rejected", message: "", time_limit_seconds_left: 3.2 });
      return false;
    },
  };

  const deactivate = activate({ root, vars: { timeLimit: { secondsLeft: 10 } }, psynet });
  await flush();
  assert.equal(calls, 1);
  assert.equal(label.textContent, 4);
  deactivate();
});

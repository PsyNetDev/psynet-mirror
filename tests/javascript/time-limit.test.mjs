import assert from "node:assert/strict";
import { it } from "node:test";

import { activate } from "../../psynet/static/scripts/time-limit.js";

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
  assert.equal(label.textContent, 0);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(submissions, [{ time_limit_reached: true }]);
});

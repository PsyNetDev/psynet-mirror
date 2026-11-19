import assert from "node:assert/strict";
import { beforeEach, it } from "node:test";

import { activate } from "../../psynet/static/scripts/time-limit.js";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  globalThis.document = { dispatchEvent: () => true };
});

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

it("announces the time-out and can submit the current answer", async () => {
  globalThis.window = { setTimeout, clearTimeout };
  const root = { querySelectorAll: () => [{ textContent: "" }], isConnected: true };
  const submissions = [];
  const psynet = {
    pageReady: true,
    pageReceivedAt: Date.now() - 10000,
    response: { staged: { rawAnswer: null, metadata: {}, blobs: {} } },
    SUBMISSION_HANDLED: Symbol("handled"),
    getRetrieveResponseHandler: () => undefined,
    nextPage: (rawAnswer, metadata) => submissions.push([rawAnswer, metadata]),
  };
  globalThis.document = {
    dispatchEvent: (event) => {
      assert.equal(event.type, "psynet:timeLimitReached");
      psynet.response.staged.rawAnswer = "partial";
    },
  };
  const vars = { timeLimit: { secondsLeft: 10, currentAnswer: true } };

  activate({ root, vars, psynet });
  await flush();
  assert.deepEqual(submissions, [["partial", { time_limit_reached: true }]]);

  psynet.getRetrieveResponseHandler = () => () => ({ rawAnswer: "typed" });
  activate({ root, vars, psynet });
  await flush();
  assert.equal(submissions[1][0], "typed");

  // As on Next, an asynchronous stage handler (e.g. MonitorControl's) runs first.
  psynet.getRetrieveResponseHandler = () => undefined;
  // SurveyJS stages its data only while this flag is set.
  let flagInHandler;
  psynet.getStageResponseHandler = () => async () => {
    flagInHandler = psynet.timeLimitSubmitting;
    psynet.response.staged.rawAnswer = "staged";
  };
  activate({ root, vars, psynet });
  await flush();
  assert.equal(submissions[2][0], "staged");
  assert.equal(flagInHandler, true);
  assert.equal(psynet.timeLimitSubmitting, false);
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

it("does not retry a submission the server refused with a message", async () => {
  globalThis.window = { setTimeout, clearTimeout };
  const root = { querySelectorAll: () => [{ textContent: "" }], isConnected: true };
  let calls = 0;
  const psynet = {
    pageReady: true,
    pageReceivedAt: Date.now() - 10000,
    nextPage: (rawAnswer, metadata, blobs, onRejection) => {
      calls += 1;
      onRejection({ submission: "rejected", message: "This page is out of date." });
      return false;
    },
  };

  const deactivate = activate({ root, vars: { timeLimit: { secondsLeft: 10 } }, psynet });
  await new Promise((resolve) => setTimeout(resolve, 1200));
  assert.equal(calls, 1);
  deactivate();
});

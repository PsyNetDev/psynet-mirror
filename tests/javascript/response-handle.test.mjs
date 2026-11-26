import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.js"),
  "utf8"
);

function extract(name) {
  const match = SOURCE.match(
    new RegExp(`psynet\\.${name} = function[\\s\\S]*?\\n    \\};`)
  );
  assert.ok(match, `missing psynet.${name}`);
  return match[0];
}

function pageWith(upcomingPages) {
  const psynet = {
    upcomingPages,
    answers: { queue: [], handle: null },
    pageState: {},
    comments: [],
    trial: { eventLog: [] },
    swappedIn: [],
    sendAnswers() {},
    showNextPredictedTrial() {},
    answerWithRenderedPage(value) {
      psynet.swappedIn.push(value);
    },
  };
  new Function(
    "psynet",
    ["nextRenderedPage", "createResponseHandle"].map(extract).join("\n")
  )(psynet);
  const handle = psynet.createResponseHandle();
  psynet.answers.handle = handle;
  return { psynet, handle };
}

it("swaps in the next page if the server sent it rendered", () => {
  const { psynet, handle } = pageWith([{ page_uuid: "p2", html: "<div></div>" }]);
  assert.equal(handle.answer("left"), true);
  assert.deepEqual(psynet.swappedIn, ["left"]);
  assert.deepEqual(psynet.answers.queue, []);
});

it("queues the answer if the module shows the next trial", () => {
  const { psynet, handle } = pageWith([{ page_uuid: "p2", contents: {} }]);
  assert.equal(handle.answer("left"), true);
  assert.deepEqual(psynet.swappedIn, []);
  assert.equal(psynet.answers.queue[0].value, "left");
});

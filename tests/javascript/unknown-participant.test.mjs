import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE = fs.readFileSync(
  path.join(ROOT, "psynet/resources/scripts/psynet.js"),
  "utf8"
);
const match = SOURCE.match(
  /psynet\.isUnknownParticipantResponse = (function[\s\S]*?\n    \});/
);
assert.ok(match, "could not extract psynet.isUnknownParticipantResponse");
const isUnknownParticipantResponse = new Function(`return ${match[1]}`)();

const BODY = '{"status": "unknown_participant", "submission": "rejected"}';

describe("isUnknownParticipantResponse", () => {
  it("recognises the 404 from an XMLHttpRequest and from jQuery", () => {
    assert.equal(isUnknownParticipantResponse({ status: 404, response: BODY }), true);
    assert.equal(
      isUnknownParticipantResponse({ status: 404, responseText: BODY }),
      true
    );
  });

  it("ignores other failures", () => {
    assert.equal(isUnknownParticipantResponse({ status: 404, response: "<html>" }), false);
    assert.equal(isUnknownParticipantResponse({ status: 500, response: BODY }), false);
    assert.equal(isUnknownParticipantResponse({ status: 0 }), false);
  });
});

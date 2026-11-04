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
  /psynet\.initLucidTermination = (function[\s\S]*?\n  \});/
);
assert.ok(match, "could not extract psynet.initLucidTermination");

function initLucidTermination(lucidRecruitment) {
  const calls = { redirectedTo: null, errors: [], uploadsAllowedToUnload: false };
  const psynet = {
    allowRecordingUnload() {
      calls.uploadsAllowedToUnload = true;
    },
    clearLucidTermination() {},
    addBeforeUnloadEventListener() {},
    removeBeforeUnloadEventListener() {},
    log: { error: (message) => calls.errors.push(message) },
  };
  const psynetTemplateData = {
    flags: { lucidRecruitment },
    uniqueId: "rid:rid",
    lucid: { secondsLeft: 600 },
  };
  const window = {
    addEventListener() {},
    location: {
      replace(url) {
        calls.redirectedTo = url;
      },
    },
  };
  new Function(
    "psynet",
    "psynetTemplateData",
    "window",
    "setInterval",
    "clearInterval",
    "$",
    "document",
    `let beforeunloadFunction; return ${match[1]};`
  )(
    psynet,
    psynetTemplateData,
    window,
    () => 1,
    () => {},
    () => ({ on() {} }),
    {}
  )();
  return { psynet, calls };
}

describe("initLucidTermination", () => {
  it("exposes psynet.terminateParticipant for Lucid screening controls", () => {
    const { psynet, calls } = initLucidTermination(true);
    psynet.terminateParticipant("screening_no");

    assert.equal(
      calls.redirectedTo,
      "/terminate_participant?unique_id=rid%3Arid&reason=screening_no"
    );
    assert.ok(calls.uploadsAllowedToUnload);
  });

  it("logs instead of terminating without Lucid recruitment", () => {
    const { psynet, calls } = initLucidTermination(false);
    psynet.terminateParticipant("screening_no");

    assert.equal(calls.redirectedTo, null);
    assert.match(calls.errors[0], /does not recruit through Lucid/);
  });
});

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

describe("initLucidTermination", () => {
  it("exposes psynet.terminateParticipant for Lucid screening controls", () => {
    let redirectedTo = null;
    const psynet = {
      clearLucidTermination() {},
      addBeforeUnloadEventListener() {},
      removeBeforeUnloadEventListener() {},
    };
    const psynetTemplateData = {
      flags: { lucidRecruitment: true },
      uniqueId: "rid:rid",
      lucid: { secondsLeft: 600 },
    };
    const window = {
      addEventListener() {},
      location: {
        replace(url) {
          redirectedTo = url;
        },
      },
    };
    const init = new Function(
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
    );

    init();
    psynet.terminateParticipant("screening_no");

    assert.equal(
      redirectedTo,
      "/terminate_participant?unique_id=rid%3Arid&reason=screening_no"
    );
  });
});

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
  /psynet\.isPredictedReply = function[\s\S]*?\n    \};/
);
assert.ok(match, "could not extract psynet.isPredictedReply");

function isPredictedReply(entry, page) {
  const psynet = { answers: { queue: [entry] } };
  const fn = new Function(
    "psynet",
    `return ${match[0].replace("psynet.isPredictedReply = ", "")}`
  )(psynet);
  return fn({ page });
}

const entry = {
  nextPageUuid: "1-5-p-abc",
  nextContents: JSON.stringify({ name: "yellow star" }),
};
const page = (contents, attributes = {}) => ({
  attributes: { page_uuid: "1-5-p-abc", ...attributes },
  contents,
});

describe("isPredictedReply", () => {
  it("adopts the page shown in advance", () => {
    assert.equal(isPredictedReply(entry, page({ name: "yellow star" })), true);
  });

  it("rejects a reply whose contents differ from those shown", () => {
    assert.equal(isPredictedReply(entry, page({ name: "green square" })), false);
  });

  it("rejects another page or a timeline hold", () => {
    assert.equal(
      isPredictedReply(entry, {
        ...page({ name: "yellow star" }),
        attributes: { page_uuid: "1-6-p-def" },
      }),
      false
    );
    assert.equal(
      isPredictedReply(entry, page({ name: "yellow star" }, { timeline_hold: true })),
      false
    );
  });
});

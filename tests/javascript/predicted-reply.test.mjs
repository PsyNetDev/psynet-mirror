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

const sendingCode = ["psynet\\.sendAnswers", "let sendQueuedAnswers"].map((name) => {
  const found = SOURCE.match(new RegExp(`${name} = async function[\\s\\S]*?\\n    \\};`));
  assert.ok(found, `could not extract ${name}`);
  return found[0];
});

describe("sendAnswers", () => {
  it("stops when an answer couldn't be sent and isn't shown again", async () => {
    const psynet = {
      answers: { queue: [{ value: 1, metadata: {} }], sending: null },
      calls: 0,
      async nextPage() {
        this.calls += 1;
        return false;
      },
    };
    new Function("psynet", sendingCode.join("\n"))(psynet);
    await psynet.sendAnswers();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(psynet.calls, 1);
  });
});

const adoptionCode = ["psynet\\.isPredictedReply", "psynet\\.adoptRenderedReply"].map(
  (name) => {
    const found = SOURCE.match(new RegExp(`${name} = function[\\s\\S]*?\\n    \\};`));
    assert.ok(found, `could not extract ${name}`);
    return found[0];
  }
);

describe("adoptRenderedReply", () => {
  const adopt = (layoutKey) => {
    const psynet = {
      answers: {
        queue: [{ ...entry, pageUuid: "1-4-p-xyz", nextLayoutKey: "k1" }],
      },
      log: { warn() {} },
      media: { prefetch() {} },
    };
    new Function("psynet", "psynetTemplateData", adoptionCode.join("\n"))(psynet, {
      flags: {},
    });
    const adopted = psynet.adoptRenderedReply({
      page: page({ name: "yellow star" }),
      timeline_fragment: { layout_key: layoutKey },
    });
    return [adopted, psynet.answers.queue.length];
  };

  it("adopts a reply that shows the page as it was swapped in", () => {
    assert.deepEqual(adopt("k1"), [true, 0]);
  });

  it("rejects a reply whose page has changed since it was swapped in", () => {
    assert.deepEqual(adopt("k2"), [false, 1]);
  });
});

const prefetchCode = SOURCE.match(
  /psynet\.media\.prefetchToken = 0;[\s\S]*?psynet\.media\.prefetch = function[\s\S]*?\n    \};/
)[0];

describe("prefetch after adopting a reply mid-swap", () => {
  it("still fetches the next pages' media once the swap ends", async () => {
    let endSwap;
    const psynet = {
      answers: { queue: [{ ...entry, pageUuid: "1-4-p-xyz", nextLayoutKey: "k1" }] },
      log: { warn() {} },
      media: { prefetched: new Map([["/a.wav", null]]), prefetchedImages: new Map() },
      pageSwap: new Promise((resolve) => (endSwap = resolve)),
    };
    const fetch = async () => ({ ok: true, blob: async () => null });
    new Function("psynet", "psynetTemplateData", "fetch", prefetchCode + adoptionCode.join("\n"))(
      psynet,
      { flags: {} },
      fetch
    );
    psynet.adoptRenderedReply({
      page: page({ name: "yellow star" }, { upcoming_media: { audio: ["/b.wav"] } }),
      timeline_fragment: { layout_key: "k1" },
    });
    // The swapped-in page has no upcoming media of its own.
    psynet.media.prefetch(undefined);
    assert.ok(psynet.media.prefetched.has("/a.wav"));
    endSwap();
    await psynet.pageSwap;
    assert.deepEqual([...psynet.media.prefetched.keys()], ["/b.wav"]);
  });
});

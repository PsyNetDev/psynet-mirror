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
  /psynet\.isExpectedReply = function[\s\S]*?\n    \};/
);
assert.ok(match, "could not extract psynet.isExpectedReply");

function isExpectedReply(entry, page) {
  const psynet = { answers: { queue: [entry] } };
  const fn = new Function(
    "psynet",
    `return ${match[0].replace("psynet.isExpectedReply = ", "")}`
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

describe("isExpectedReply", () => {
  it("adopts the page shown in advance", () => {
    assert.equal(isExpectedReply(entry, page({ name: "yellow star" })), true);
  });

  it("rejects a reply whose contents differ from those shown", () => {
    assert.equal(isExpectedReply(entry, page({ name: "green square" })), false);
  });

  it("with nothing shown after the answer, accepts any page but a hold", () => {
    assert.equal(isExpectedReply({}, page({ name: "green square" })), true);
    assert.equal(isExpectedReply({}, page({}, { timeline_hold: true })), false);
  });

  it("rejects another page or a timeline hold", () => {
    assert.equal(
      isExpectedReply(entry, {
        ...page({ name: "yellow star" }),
        attributes: { page_uuid: "1-6-p-def" },
      }),
      false
    );
    assert.equal(
      isExpectedReply(entry, page({ name: "yellow star" }, { timeline_hold: true })),
      false
    );
  });
});

const extract = (pattern) => {
  const found = SOURCE.match(pattern);
  assert.ok(found, `could not extract ${pattern}`);
  return found[0];
};
const serialQueueCode = extract(/let serialQueue = function[\s\S]*?\n    \};/);
const queueCode = serialQueueCode + "let queueSubmission = serialQueue();";
const sendingCode = ["psynet\\.sendAnswers", "let sendQueuedAnswers"].map((name) =>
  extract(new RegExp(`${name} = async function[\\s\\S]*?\\n    \\};`))
);

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
    new Function("psynet", queueCode + sendingCode.join("\n"))(psynet);
    await psynet.sendAnswers();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(psynet.calls, 1);
  });
});

const adoptionCode = ["psynet\\.isExpectedReply", "psynet\\.adoptRenderedReply"].map(
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
      changePage: (change) => change(),
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

const prefetchCode = extract(/psynet\.media\.prefetch = function[\s\S]*?\n    \};/);
const changePageCode = serialQueueCode + "psynet.changePage = serialQueue();";

describe("prefetch after adopting a reply mid-swap", () => {
  it("still fetches the next pages' media once the swap ends", async () => {
    let endSwap;
    const psynet = {
      answers: { queue: [{ ...entry, pageUuid: "1-4-p-xyz", nextLayoutKey: "k1" }] },
      log: { warn() {} },
      media: { prefetched: new Map([["/a.wav", null]]), prefetchedImages: new Map() },
    };
    const fetch = async () => ({ ok: true, blob: async () => null });
    new Function(
      "psynet",
      "psynetTemplateData",
      "fetch",
      changePageCode + prefetchCode + adoptionCode.join("\n")
    )(psynet, { flags: {} }, fetch);
    const swap = new Promise((resolve) => (endSwap = resolve));
    psynet.changePage(() => swap);
    psynet.adoptRenderedReply({
      page: page({ name: "yellow star" }, { upcoming_media: { audio: ["/b.wav"] } }),
      timeline_fragment: { layout_key: "k1" },
    });
    // The swapped-in page has no upcoming media of its own.
    psynet.media.prefetch(undefined);
    assert.ok(psynet.media.prefetched.has("/a.wav"));
    endSwap();
    await psynet.changePage(() => {});
    assert.deepEqual([...psynet.media.prefetched.keys()], ["/b.wav"]);
  });
});

const submissionCode =
  serialQueueCode +
  extract(/let queueSubmission = serialQueue\(\);[\s\S]*?(?=\n    \/\/ Show the page before this one again)/);

describe("nextPage while answers given in advance are sent", () => {
  it("times the answer from the click and ignores a second click", async () => {
    let finishSending;
    const posted = [];
    const psynet = {
      pageReady: true,
      pageState: {},
      pageModuleGeneration: 0,
      pageLoadTime: new Date(Date.now() - 500),
      trial: { eventLog: ["promptStart"] },
      response: { staged: { blobs: {} } },
      comments: [],
      log: { info() {} },
      answers: { queue: [{ value: "earlier", metadata: {} }], sending: null },
      nextRenderedPage: () => null,
      setTimelineTransitionBusy() {},
    };
    const submitGenericResponse = async (rawAnswer, metadata) => {
      posted.push([rawAnswer, metadata]);
      if (rawAnswer === "earlier") {
        await new Promise((resolve) => (finishSending = resolve));
        psynet.answers.queue.shift();
      }
      return true;
    };
    new Function(
      "psynet",
      "psynetTemplateData",
      "submitGenericResponse",
      "onSuccessResponse",
      "onErrorResponse",
      submissionCode + sendingCode.join("\n")
    )(psynet, { flags: {} }, submitGenericResponse);
    psynet.sendAnswers();
    const first = psynet.nextPage("A");
    assert.equal(await psynet.nextPage("B"), false);
    await new Promise((resolve) => setTimeout(resolve, 300));
    finishSending();
    assert.equal(await first, true);
    assert.deepEqual(
      posted.map(([answer]) => answer),
      ["earlier", "A"]
    );
    const metadata = posted[1][1];
    assert.ok(metadata.time_taken < 0.7, `time_taken was ${metadata.time_taken}`);
    assert.deepEqual(metadata.event_log, ["promptStart"]);
  });
});

describe("finalizePageReady", () => {
  it("doesn't wait for a page module's update() to finish", async () => {
    const code = ["psynet\\.showPageModuleTrial = function", "psynet\\.finalizePageReady = async function"]
      .map((start) => extract(new RegExp(`${start}[\\s\\S]*?\\n    \\};`)))
      .join("\n");
    let updated = false;
    const psynet = {
      pageModuleGeneration: 1,
      page: { attributes: {} },
      pageModuleUpdates: [() => {}],
      setPageReady() {},
      trial: { async registerEvent() {} },
      ensureArrivalUpdates() {},
      waiting: { start() {} },
      setTimelineTransitionBusy() {},
      log: { error() {} },
      // Like an update() that waits for its signal, aborted only on leaving.
      updatePageModules() {
        updated = true;
        return new Promise(() => {});
      },
    };
    new Function("psynet", code)(psynet);
    await psynet.finalizePageReady();
    assert.equal(updated, true);
  });
});

describe("showPageModuleTrial", () => {
  const run = async (abort) => {
    const failures = [];
    const psynet = {
      pageModuleGeneration: 1,
      updateController: null,
      handleTimelineTransitionFailure: (error) => failures.push(error.message),
      async updatePageModules() {
        const controller = new AbortController();
        psynet.updateController = controller;
        await null;
        if (abort) controller.abort();
        throw new Error("The sound couldn't load.");
      },
    };
    new Function("psynet", extract(/psynet\.showPageModuleTrial = function[\s\S]*?\n    \};/))(psynet);
    psynet.showPageModuleTrial(0);
    await new Promise((resolve) => setTimeout(resolve, 0));
    return failures;
  };

  it("asks the participant to reload when update() fails", async () => {
    assert.deepEqual(await run(false), ["The sound couldn't load."]);
  });

  it("ignores an update() that a newer one replaced", async () => {
    assert.deepEqual(await run(true), []);
  });
});

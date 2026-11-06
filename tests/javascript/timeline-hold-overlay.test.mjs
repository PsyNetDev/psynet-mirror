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

function extractFunction(name) {
  const match = SOURCE.match(
    new RegExp(`psynet\\.${name} = (async )?function[\\s\\S]*?\\n    \\};`)
  );
  assert.ok(match, `could not extract psynet.${name}`);
  return match[0].replace(`psynet.${name} = `, "").replace("function", `function ${name}`);
}

function createDom({ commentDisabled = false } = {}) {
  const nodes = new Map();

  function makeNode(id) {
    const node = {
      id,
      dataset: {},
      className: "",
      innerHTML: "",
      inert: false,
      disabled: false,
      children: [],
      classList: {
        add() {},
        remove() {},
      },
      setAttribute() {},
      querySelector(selector) {
        if (selector === ".psynet-timeline-hold-message") {
          return this.children.find((child) =>
            String(child.className).includes("psynet-timeline-hold-message")
          );
        }
        return null;
      },
      appendChild(child) {
        this.children.push(child);
        if (child.id) {
          nodes.set(child.id, child);
        }
        return child;
      },
      remove() {
        if (this.id) {
          nodes.delete(this.id);
        }
      },
    };
    if (id) {
      nodes.set(id, node);
    }
    return node;
  }

  const document = {
    body: makeNode("body"),
    getElementById(id) {
      return nodes.get(id) ?? null;
    },
    createElement() {
      return makeNode(null);
    },
  };
  makeNode("timeline-hold-region");
  const mainBody = makeNode("main-body");
  const commentButton = makeNode("comment-button");
  commentButton.disabled = commentDisabled;
  return { document, mainBody, commentButton };
}

function FakeCustomEvent(type, init = {}) {
  this.type = type;
  this.detail = init.detail;
}

function loadHoldFns(document) {
  const psynet = {
    hideArrivalNotice() {},
    timelineHold: {
      stopped: false,
      safetyTimer: null,
      timeoutTimer: null,
      busyRetryTimer: null,
      connection: null,
      hold: { hold_id: "hold-1" },
    },
  };
  const dispatched = [];
  const window = {
    dispatchEvent(event) {
      dispatched.push(event);
      return true;
    },
  };
  const showSrc = extractFunction("showTimelineHoldIndicator");
  const hideSrc = extractFunction("hideTimelineHoldIndicator");
  const stopSrc = extractFunction("stopTimelineHold");
  const show = new Function(
    "psynet",
    "document",
    `${showSrc}; return showTimelineHoldIndicator;`
  )(psynet, document);
  psynet.hideTimelineHoldIndicator = new Function(
    "document",
    `${hideSrc}; return hideTimelineHoldIndicator;`
  )(document);
  // CI Node has no browser CustomEvent global. Bind a constructor into the
  // eval and assert the dispatched event so a dummy CustomEvent cannot
  // make stop() look successful without actually firing timelineHoldEnded.
  const stop = new Function(
    "psynet",
    "document",
    "window",
    "CustomEvent",
    `${stopSrc}; return stopTimelineHold;`
  )(psynet, document, window, FakeCustomEvent);
  return { psynet, show, stop, dispatched, window };
}

describe("timeline hold overlay reuse", () => {
  it("keeps the held page inert when the dynamic chip is reused", () => {
    const { document, mainBody, commentButton } = createDom();
    const { show, stop, dispatched } = loadHoldFns(document);

    show("Waiting");
    assert.equal(mainBody.inert, true);
    assert.equal(commentButton.disabled, true);
    const chip = document.getElementById("psynet-timeline-hold-indicator");
    assert.equal(chip.dataset.timelineHoldDynamic, "true");
    assert.equal(chip.dataset.commentButtonWasDisabled, "false");

    show("Still waiting");
    assert.equal(mainBody.inert, true);
    assert.equal(chip.dataset.commentButtonWasDisabled, "false");

    stop();
    assert.equal(mainBody.inert, false);
    assert.equal(commentButton.disabled, false);
    assert.equal(document.getElementById("psynet-timeline-hold-indicator"), null);
    assert.equal(dispatched.length, 1);
    assert.equal(dispatched[0].type, "timelineHoldEnded");
    assert.equal(dispatched[0].detail.holdId, "hold-1");
  });

  it("does not inert a server-rendered fallback chip", () => {
    const { document, mainBody } = createDom();
    const chip = document.createElement("div");
    chip.id = "psynet-timeline-hold-indicator";
    const message = document.createElement("span");
    message.className = "psynet-timeline-hold-message";
    chip.appendChild(message);
    document.getElementById("timeline-hold-region").appendChild(chip);
    const { show } = loadHoldFns(document);

    show("Waiting");
    assert.equal(mainBody.inert, false);
    assert.equal(chip.dataset.timelineHoldDynamic, undefined);
  });

  it("restores the page when hold-ended dispatch throws", () => {
    const { document, mainBody, commentButton } = createDom();
    const { show, stop, window } = loadHoldFns(document);
    show("Waiting");
    window.dispatchEvent = () => {
      throw new Error("dispatch failed");
    };
    assert.throws(() => stop(), /dispatch failed/);
    assert.equal(mainBody.inert, false);
    assert.equal(commentButton.disabled, false);
    assert.equal(document.getElementById("psynet-timeline-hold-indicator"), null);
  });
});

describe("approved response into a waiting screen", () => {
  function loadHandler(shownHoldUuid, shownReplacesPage = true) {
    const calls = [];
    const record = (name) => async () => calls.push(name);
    const psynet = {
      log: { debug() {} },
      page: {
        attributes: {
          timeline_hold: { page_uuid: shownHoldUuid, replaces_page: shownReplacesPage },
        },
      },
      isSameSessionPageUpdate: () => false,
      requiresFullPageReloadTransition: () => false,
      endPageRecording: record("endPageRecording"),
      updatePageForTimelineHold: record("updatePageForTimelineHold"),
      beginTimelineHold: record("beginTimelineHold"),
      stopTimelineHold: record("stopTimelineHold"),
      clearSubmissionControlState: record("clearSubmissionControlState"),
      requireTimelineFragmentPayload: (response) => response.timeline_fragment,
      loadNextTimelinePageFromResponse: record("loadNextTimelinePageFromResponse"),
      loadNextTimelinePageWithReload: record("loadNextTimelinePageWithReload"),
      timelineHold: {},
    };
    const templateData = { flags: { inplaceTimelineTransitions: true } };
    const handle = new Function(
      "psynet",
      "psynetTemplateData",
      `${extractFunction("handleApprovedResponse")}; return handleApprovedResponse;`
    )(psynet, templateData);
    return { handle, calls };
  }

  function holdResponse(pageUuid, replacesPage = true) {
    const hold = { page_uuid: pageUuid, replaces_page: replacesPage };
    return {
      page: { attributes: { timeline_hold: hold } },
      timeline_fragment: { page_uuid: pageUuid, html: "<div></div>" },
    };
  }

  it("keeps waiting on the waiting screen it already shows", async () => {
    const { handle, calls } = loadHandler("hold-1");
    await handle(holdResponse("hold-1"));
    assert.ok(calls.includes("beginTimelineHold"));
    assert.ok(!calls.includes("loadNextTimelinePageFromResponse"));
    assert.ok(!calls.includes("loadNextTimelinePageWithReload"));
  });

  it("renders the waiting screen of a different hold", async () => {
    const { handle, calls } = loadHandler("hold-1");
    await handle(holdResponse("hold-2"));
    assert.ok(!calls.includes("beginTimelineHold"));
    assert.ok(calls.includes("loadNextTimelinePageFromResponse"));
  });

  it("reloads into a hold without a waiting screen from a waiting screen", async () => {
    const { handle, calls } = loadHandler("hold-1");
    await handle(holdResponse("hold-2", false));
    assert.ok(!calls.includes("beginTimelineHold"));
    assert.ok(calls.includes("loadNextTimelinePageWithReload"));
  });

  it("keeps the participant's page under a hold without a waiting screen", async () => {
    const { handle, calls } = loadHandler(undefined, false);
    await handle(holdResponse("hold-2", false));
    assert.ok(calls.includes("beginTimelineHold"));
    assert.ok(!calls.includes("loadNextTimelinePageWithReload"));
  });
});

it("ignores directed messages that are not hold wakes", () => {
  let options;
  const calls = [];
  const psynet = {
    handleArrivalUpdateMessage: () => calls.push("update"),
    resumeTimelineHold: () => calls.push("resume"),
  };
  const channel = { connect: (opts) => (options = opts) };
  const connect = new Function(
    "psynet",
    "PsyNetWebSocketChannel",
    `${extractFunction("_connectTimelineHoldSocket")}; return _connectTimelineHoldSocket;`
  )(psynet, channel);
  connect({ stopped: false, hold: { channel: "c", wake_token: "w" } });

  options.onDirect({ type: "message", targets: [{ wake_token: "w", hold_message: "<b>" }] });
  assert.deepEqual(calls, []);
});

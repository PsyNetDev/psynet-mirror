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
  const start = SOURCE.indexOf(`psynet.${name} = function`);
  assert.notEqual(start, -1, `missing psynet.${name}`);
  const match = SOURCE.slice(start).match(
    new RegExp(`psynet\\.${name} = function[\\s\\S]*?\\n    \\};`)
  );
  assert.ok(match, `could not extract psynet.${name}`);
  return match[0].replace(`psynet.${name} = function`, `function ${name}`);
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
  const window = { dispatchEvent() {} };
  const showSrc = extractFunction("showTimelineHoldIndicator");
  const stopSrc = extractFunction("stopTimelineHold");
  const show = new Function(
    "psynet",
    "document",
    `${showSrc}; return showTimelineHoldIndicator;`
  )(psynet, document);
  const stop = new Function(
    "psynet",
    "document",
    "window",
    `${stopSrc}; return stopTimelineHold;`
  )(psynet, document, window);
  return { psynet, show, stop };
}

describe("timeline hold overlay reuse", () => {
  it("keeps the held page inert when the dynamic chip is reused", () => {
    const { document, mainBody, commentButton } = createDom();
    const { show, stop } = loadHoldFns(document);

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
});

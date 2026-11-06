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

describe("timeline hold countdown", () => {
  function load() {
    const element = { dataset: {}, textContent: "" };
    const document = { querySelectorAll: () => [element] };
    const resumes = [];
    const psynet = { resumeTimelineHold: (reason) => resumes.push(reason) };
    const now = { value: 0 };
    const DateStub = { now: () => now.value };
    for (const name of ["tickTimelineHoldCountdowns", "setTimelineHoldCountdowns"]) {
      psynet[name] = new Function(
        "psynet",
        "document",
        "Date",
        `${extractFunction(name)}; return ${name};`
      )(psynet, document, DateStub);
    }
    return { psynet, element, resumes, now };
  }

  it("counts down to the release and then checks for it once", () => {
    const { psynet, element, resumes, now } = load();
    psynet.setTimelineHoldCountdowns(2500);
    assert.equal(element.textContent, "3");

    now.value = 1600;
    psynet.tickTimelineHoldCountdowns();
    assert.equal(element.textContent, "1");
    assert.deepEqual(resumes, []);

    now.value = 2900;
    psynet.tickTimelineHoldCountdowns();
    psynet.tickTimelineHoldCountdowns();
    assert.equal(element.textContent, "0");
    assert.deepEqual(resumes, ["countdown"]);
  });

  it("shows an ellipsis while the release time is unknown", () => {
    const { psynet, element, resumes } = load();
    psynet.setTimelineHoldCountdowns(null);
    assert.equal(element.textContent, "…");
    psynet.setTimelineHoldCountdowns(0);
    assert.equal(element.textContent, "0");
    assert.deepEqual(resumes, []);
  });
});

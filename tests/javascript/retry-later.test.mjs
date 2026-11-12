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

function extract(name) {
  const match = SOURCE.match(
    new RegExp(`psynet\\.${name} = (async )?function[\\s\\S]*?\\n    \\};`)
  );
  assert.ok(match, `could not extract psynet.${name}`);
  return match[0].replace(`psynet.${name} = `, "");
}

const retryLaterRejection = new Function(`return ${extract("retryLaterRejection")}`)();

function response(status, body) {
  return { status, response: JSON.stringify(body) };
}

const WAIT = response(200, {
  submission: "rejected",
  message: "Please wait.",
  retry_after: 1.5,
});

// Runs psynet.waitIfRetryLater with a fake psynet and timer.
function retryHarness() {
  const notices = [];
  const waits = [];
  const psynet = {
    retryLaterRejection,
    log: { info() {} },
    showStatusNotice: (id, text) => notices.push([id, text]),
  };
  const fakeSetTimeout = (callback, ms) => {
    waits.push(ms);
    callback();
  };
  const waitIfRetryLater = new Function(
    "psynet",
    "setTimeout",
    `return ${extract("waitIfRetryLater")}`
  )(psynet, fakeSetTimeout);
  return { notices, waits, wait: waitIfRetryLater };
}

describe("retryLaterRejection", () => {
  it("reads the delay and message of a rejection to send again later", () => {
    assert.deepEqual(retryLaterRejection(WAIT), {
      delayMs: 1500,
      message: "Please wait.",
    });
  });

  it("leaves other responses to the normal handling", () => {
    for (const other of [
      response(200, { submission: "rejected", message: "No." }),
      response(200, { submission: "approved", retry_after: 1 }),
      response(200, { submission: "rejected", retry_after: 0 }),
      response(200, { submission: "rejected", retry_after: "1" }),
      response(503, { submission: "rejected", retry_after: 1 }),
      { status: 200, response: "<html>" },
    ]) {
      assert.equal(retryLaterRejection(other), null);
    }
  });
});

describe("waitIfRetryLater", () => {
  it("shows the message while it waits, then removes it once the response is accepted", async () => {
    const harness = retryHarness();
    assert.equal(await harness.wait(WAIT), true);
    assert.equal(await harness.wait(response(200, { submission: "approved" })), false);
    assert.deepEqual(harness.waits, [1500]);
    assert.deepEqual(harness.notices, [
      ["psynet-retry-notice", "Please wait."],
      ["psynet-retry-notice", null],
    ]);
  });
});

describe("showStatusNotice", () => {
  // A document whose elements, once added anywhere, can be found by id.
  function fakeDocument() {
    const elements = {};
    const element = () => ({
      children: [],
      setAttribute() {},
      style: {},
      appendChild(child) {
        this.children.push(child);
        child.parent = this;
        elements[child.id] = child;
      },
      remove() {
        delete elements[this.id];
        this.parent.children.splice(this.parent.children.indexOf(this), 1);
      },
    });
    const body = element();
    return {
      elements,
      document: {
        getElementById: (id) => elements[id] || null,
        createElement: element,
        body: body,
      },
    };
  }

  function loadShowStatusNotice(document) {
    return new Function("document", "setTimeout", `return ${extract("showStatusNotice")}`)(
      document,
      (callback) => callback()
    );
  }

  it("stacks notices with different ids, in the order they were first shown", () => {
    const { elements, document } = fakeDocument();
    const showStatusNotice = loadShowStatusNotice(document);

    showStatusNotice("waiting", "The game isn't over yet. The page will move on once it is.");
    showStatusNotice("away", "Another player has left the game.");
    showStatusNotice("waiting", "The game isn't over yet. The page will move on once it is.");
    const stack = elements["psynet-status-notices"];
    assert.deepEqual(
      stack.children.map((notice) => notice.id),
      ["waiting", "away"]
    );
    assert.deepEqual(document.body.children, [stack]);
    showStatusNotice("waiting", null);
    assert.deepEqual(
      stack.children.map((notice) => notice.textContent),
      ["Another player has left the game."]
    );
  });

  it("shows each new message in the same notice, and removes it", () => {
    const { elements, document } = fakeDocument();
    const showStatusNotice = loadShowStatusNotice(document);

    showStatusNotice("notice", "Waiting for 2 players.");
    showStatusNotice("notice", "Waiting for 1 player.");
    assert.equal(elements.notice.textContent, "Waiting for 1 player.");
    showStatusNotice("notice", null);
    assert.equal(elements.notice, undefined);
  });
});

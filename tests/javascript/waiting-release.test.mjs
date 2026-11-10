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
const WAITING_SOURCE = SOURCE.match(/psynet\.waiting = (\{[\s\S]*?\n    \});/)[1];

function FakeCustomEvent(type, init = {}) {
  this.type = type;
  this.detail = init.detail;
}

// Runs psynet.waiting against a fake clock, fetch and psynet.
function waitingHarness({ statuses, cancelRelease = false }) {
  let now = 0;
  let timers = [];
  const calls = [];
  const psynet = {
    uniqueId: "participant-1",
    nextPagePending: false,
    log: { warn() {} },
    showArrivalNotice: (message) => calls.push(`notice: ${message}`),
    hideArrivalNotice: () => calls.push("hide notice"),
    nextPage: (answer, metadata) =>
      calls.push(`submit interrupted=${metadata.interrupted}`),
    loadNextTimelinePageWithReload: async () => calls.push("reload"),
  };
  const window = {
    dispatchEvent: (event) =>
      !(cancelRelease && event.type === "psynetWaitingRelease"),
  };
  const fetch = async () => ({ ok: true, json: async () => statuses.shift() });
  const schedule = (fn, ms, every = null) => {
    const timer = { at: now + ms, fn, every };
    timers.push(timer);
    return timer;
  };
  const clear = (timer) => {
    timers = timers.filter((t) => t !== timer);
  };
  psynet.waiting = new Function(
    "psynet",
    "window",
    "fetch",
    "setTimeout",
    "clearTimeout",
    "setInterval",
    "clearInterval",
    "Date",
    "CustomEvent",
    `return ${WAITING_SOURCE};`
  )(
    psynet,
    window,
    fetch,
    schedule,
    clear,
    (fn, ms) => schedule(fn, ms, ms),
    clear,
    { now: () => now },
    FakeCustomEvent
  );
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  return {
    psynet,
    calls,
    async start(config) {
      psynet.waiting.start(config);
      await settle();
    },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = timers
          .filter((t) => t.at <= end)
          .sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        now = due.at;
        if (due.every) due.at += due.every;
        else clear(due);
        due.fn();
        await settle();
      }
      now = end;
    },
  };
}

const INTERRUPTIBLE = {
  barrier_id: "pair",
  release_grace_ms: 3000,
  release_notice: "Moving on in {SECONDS} s.",
};
const RELEASED = { released: true, ends_page: true, release_in_ms: null };
const MOVED_ON = { released: true, ends_page: false, release_in_ms: null };

describe("psynet.waiting", () => {
  it("counts down once per second, then submits the page as interrupted", async () => {
    const harness = waitingHarness({ statuses: [RELEASED] });
    await harness.start(INTERRUPTIBLE);
    await harness.advance(3000);
    assert.deepEqual(harness.calls, [
      "notice: Moving on in 3 s.",
      "notice: Moving on in 2 s.",
      "notice: Moving on in 1 s.",
      "submit interrupted=true",
    ]);
  });

  it("lets a page cancel the built-in notice but still ends the page", async () => {
    const harness = waitingHarness({ statuses: [RELEASED], cancelRelease: true });
    await harness.start(INTERRUPTIBLE);
    await harness.advance(3000);
    assert.deepEqual(harness.calls, ["hide notice", "submit interrupted=true"]);
  });

  it("reloads an interruptible page that the server has moved past", async () => {
    const harness = waitingHarness({ statuses: [MOVED_ON] });
    await harness.start(INTERRUPTIBLE);
    assert.deepEqual(harness.calls, ["reload"]);
  });

  it("stops polling on a page the release may not end", async () => {
    const harness = waitingHarness({ statuses: [MOVED_ON] });
    await harness.start({ barrier_id: "pair", release_grace_ms: null });
    await harness.advance(10000);
    assert.deepEqual(harness.calls, []);
    assert.equal(harness.psynet.waiting.config, null);
  });
});

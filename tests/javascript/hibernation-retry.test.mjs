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

const hibernationRetryDelayMs = new Function(
  `return ${extract("hibernationRetryDelayMs")}`
)();

function response(status, body, retryAfter = null) {
  return {
    status,
    response: body,
    getResponseHeader: (name) => (name === "Retry-After" ? retryAfter : null),
  };
}

// Runs psynet.waitIfAppIsWaking against a fake clock and a fake psynet.
function retryHarness() {
  let clock = 0;
  const notices = [];
  const psynet = {
    hibernationRetryDelayMs,
    hibernationRetryLimitMs: 5 * 60 * 1000,
    log: { warn() {} },
    showWakingNotice: (visible) => notices.push(visible),
  };
  const fakeSetTimeout = (callback, ms) => {
    clock += ms;
    callback();
  };
  const FakeDate = { now: () => clock };
  const waitIfAppIsWaking = new Function(
    "psynet",
    "setTimeout",
    "Date",
    `return ${extract("waitIfAppIsWaking")}`
  )(psynet, fakeSetTimeout, FakeDate);
  return {
    notices,
    wait: (request, retry, options) => waitIfAppIsWaking(request, retry, options),
    advance: (ms) => {
      clock += ms;
    },
  };
}

const WAKING = response(503, '{"status": "waking"}', "5");

describe("hibernationRetryDelayMs", () => {
  it("waits for Retry-After while the app sleeps or wakes", () => {
    assert.equal(
      hibernationRetryDelayMs(response(503, '{"status": "hibernating"}', "5")),
      5000
    );
    assert.equal(
      hibernationRetryDelayMs(response(503, '{"status": "waking"}', null)),
      5000
    );
    assert.equal(
      hibernationRetryDelayMs(response(503, '{"status": "waking"}', "60")),
      10000
    );
  });

  it("leaves other responses to the normal handling", () => {
    assert.equal(hibernationRetryDelayMs(response(200, "{}")), null);
    assert.equal(
      hibernationRetryDelayMs(response(503, '{"status": "busy"}')),
      null
    );
    assert.equal(
      hibernationRetryDelayMs(response(503, '{"status": "unavailable"}')),
      null
    );
    assert.equal(hibernationRetryDelayMs(response(503, "<html>")), null);
  });
});

describe("waitIfAppIsWaking", () => {
  it("retries while waking, then hides the notice once the app answers", async () => {
    const harness = retryHarness();
    const retry = {};
    assert.equal(await harness.wait(WAKING, retry), true);
    assert.equal(await harness.wait(WAKING, retry), true);
    assert.equal(await harness.wait(response(200, "{}"), retry), false);
    assert.deepEqual(harness.notices, [true, true, false]);
  });

  it("gives up after the limit, so the normal error handling runs", async () => {
    const harness = retryHarness();
    const retry = {};
    assert.equal(await harness.wait(WAKING, retry), true);
    harness.advance(5 * 60 * 1000);
    assert.equal(await harness.wait(WAKING, retry), false);
    assert.deepEqual(harness.notices, [true, false]);
  });

  it("does not retry other failures", async () => {
    const harness = retryHarness();
    const unavailable = response(503, '{"status": "unavailable"}');
    assert.equal(await harness.wait(unavailable, {}), false);
  });

  it("retries hold re-checks without covering the hold message", async () => {
    const harness = retryHarness();
    assert.equal(
      await harness.wait(WAKING, {}, { timelineHoldResume: true }),
      true
    );
    assert.deepEqual(harness.notices, []);
  });
});

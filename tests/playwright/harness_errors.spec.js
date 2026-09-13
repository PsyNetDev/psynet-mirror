const { test, expect } = require("./fixtures");
const { isDestroyedExecutionContext } = require("./psynetHarness");
const { overlayLingerForBudgetMs } = require("./stackedHoldHarness");

test("destroyed execution context matches Playwright navigation errors", { tag: "@both" }, () => {
  // Legacy hold resume reloads mid-wait. Playwright may say the context was
  // destroyed, or it may fail toHaveCount with Received: undefined.
  expect(
    isDestroyedExecutionContext(
      new Error("Execution context was destroyed, most likely because of a navigation")
    )
  ).toBe(true);
  expect(
    isDestroyedExecutionContext(
      new Error(
        "expect(locator('#psynet-timeline-hold-indicator')).toHaveCount(0) failed\nReceived: undefined"
      )
    )
  ).toBe(true);
  expect(
    isDestroyedExecutionContext(new Error("page.evaluate: Target closed"))
  ).toBe(true);
  expect(
    isDestroyedExecutionContext(
      new Error("expect(locator('#psynet-timeline-hold-indicator')).toHaveCount(0)\nReceived: 1")
    )
  ).toBe(false);
});

test("overlay linger budget excludes hold-resume gunicorn queue", { tag: "@both" }, () => {
  // CI last-of-four: wake→end 1876ms, POST wall 1873ms, app 773ms, queue~1100.
  expect(
    overlayLingerForBudgetMs(1876, { durationMs: 1873, serverTimingMs: 773 })
  ).toBe(776);
  expect(overlayLingerForBudgetMs(400, { durationMs: 200, serverTimingMs: 180 })).toBe(
    380
  );
  expect(overlayLingerForBudgetMs(null, { durationMs: 200, serverTimingMs: 180 })).toBe(
    null
  );
});

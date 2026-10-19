const { test, expect } = require("./fixtures");
const { isDestroyedExecutionContext } = require("./psynetHarness");

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

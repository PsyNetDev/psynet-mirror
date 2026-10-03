/**
 * Playwright helper that asserts the current participant page via the
 * in-page layout API (`psynetLayout.check()`).
 *
 * The collectors live in `psynet/resources/scripts/psynet.layout.js` so
 * experiment Playwright walks can call them without copying this file.
 * This helper fails if the page did not load that script.
 *
 * Usage:
 *
 *   const { assertPageInvariants } = require("./participantPageInvariants");
 *   await assertPageInvariants(page, "radio page");
 */
const { expect } = require("./fixtures");

function formatViolations(label, violations) {
  const lines = violations.map((v) => `  - [${v.check}] ${v.detail}`);
  return `Participant page invariants failed on ${label}:\n${lines.join("\n")}`;
}

/**
 * Assert that the current page satisfies every layout invariant.
 *
 * `label` identifies the page in the failure message; Playwright attaches its
 * own screenshot and trace on failure, so the report shows what the page looked
 * like when the assertion fired.
 */
async function assertPageInvariants(page, label) {
  // Park the pointer so hover styling cannot influence geometry.
  await page.mouse.move(0, 0).catch(() => {});
  const violations = await page.evaluate(async () => {
    const layout = window.psynetLayout;
    if (!layout || typeof layout.check !== "function") {
      throw new Error(
        "psynetLayout.check is not available on this page. " +
          "Participant pages should load /static/scripts/psynet.layout.js."
      );
    }
    return await layout.check();
  });
  expect(violations, formatViolations(label, violations)).toEqual([]);
}

module.exports = {
  assertPageInvariants,
};

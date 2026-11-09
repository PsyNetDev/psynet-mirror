const path = require("path");
const { test, expect } = require("./fixtures");
const {
  ACTION_PROMPT,
  GROUP_HOLD_TEXT,
  RESULTS_PROMPT,
  SETTLE_HOLD_MS,
  assertNoSessionErrors,
  assertStillHeld,
  closeHoldSessions,
  enterSkippingHold,
  enterWaitingHold,
  startHoldExperiment,
  stopExperiment,
  armChoiceHold,
  assertWaiterReleasedWithLastArriver,
  submitLastChoice
} = require("./stackedHoldHarness");

// The pair variant of stacked_group_holds.spec.js: a grouper followed by two
// group barriers, then a choice page and a post-choice barrier.
const STACKED_DIR = path.resolve("tests/playwright/experiments/stacked_group_holds");
const PAIR = { env: { PSYNET_STACKED_GROUP_SIZE: "2" } };

test("last arriver skips stacked entry holds", { tag: "@both" }, async ({
  browser
}) => {
  // Enter one participant at a time. The last arriver self-skips released
  // stacked waits and may first-paint a silent catch-up hold. The waiting
  // partner stays on the authored overlay until the server wake, without a
  // safety poll as the success path.
  const { experiment, sessions } = await startHoldExperiment(
    browser,
    STACKED_DIR,
    ["stacked_hold_first", "stacked_hold_second"],
    PAIR
  );
  const [first, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    // Stay past the default 2s safety-poll window so a missed wake cannot
    // hide behind the next scheduled check.
    await first.page.waitForTimeout(SETTLE_HOLD_MS);
    await assertStillHeld(first, GROUP_HOLD_TEXT);
    const lastEntry = await enterSkippingHold(last);
    await expect(last.page.getByRole("button", { name: "go" })).toBeVisible();
    await assertWaiterReleasedWithLastArriver(first, lastEntry);
    await expect(first.page.getByRole("button", { name: "go" })).toBeVisible();
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

test("last choice releases the waiting partner without a safety poll", { tag: "@both" }, async ({
  browser
}) => {
  // After both players reach the choice page, the first submit waits in place.
  // The second submit is a POST /response last arrival, which is a different
  // finalize path from the first GET /timeline skip. A last-arrival GET can
  // 302 after page_uuid advances; first-paint waits for the 200 HTML body.
  // Stay past the default 2s safety-poll window so a missed wake cannot
  // hide behind the next scheduled check.
  const { experiment, sessions } = await startHoldExperiment(
    browser,
    STACKED_DIR,
    ["choice_hold_first", "choice_hold_second"],
    PAIR
  );
  const [first, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await first.page.waitForTimeout(SETTLE_HOLD_MS);
    await assertStillHeld(first, GROUP_HOLD_TEXT);
    const lastEntry = await enterSkippingHold(last);
    await assertWaiterReleasedWithLastArriver(first, lastEntry);

    await armChoiceHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: RESULTS_PROMPT
    });
    const lastChoice = await submitLastChoice(last, { prompt: RESULTS_PROMPT });
    await assertWaiterReleasedWithLastArriver(first, lastChoice, {
      prompt: RESULTS_PROMPT
    });
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

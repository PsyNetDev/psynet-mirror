const path = require("path");
const { test, expect } = require("./fixtures");
const {
  ACTION_PROMPT,
  PAIR_HOLD_TEXT,
  SETTLE_HOLD_MS,
  assertNoSessionErrors,
  assertStillHeld,
  closeHoldSessions,
  enterSkippingHold,
  enterWaitingHold,
  ENTRY_REQUEST_MAX_MS,
  lastArriverWorkRecord,
  startHoldExperiment,
  stopExperiment,
  armChoiceHold,
  assertWaiterReleasedWithLastArriver,
  submitLastChoice
} = require("./stackedHoldHarness");
const { requestHandlerMs } = require("./psynetHarness");

const RPS_DIR = path.resolve("demos/experiments/rock_paper_scissors");

test("last arriver skips stacked entry holds", { tag: "@both" }, async ({
  browser
}) => {
  // Enter one participant at a time. The last arriver skips the released
  // stacked waits, including waiting partners, so first-paint is the action
  // page. The waiting partner must leave their hold from the server wake,
  // without a safety poll as the success path.
  const { experiment, sessions } = await startHoldExperiment(browser, RPS_DIR, [
    "stacked_hold_first",
    "stacked_hold_second"
  ]);
  const [first, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: PAIR_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    // Stay past the default 2s safety-poll window so a missed wake cannot
    // hide behind the next scheduled check.
    await first.page.waitForTimeout(SETTLE_HOLD_MS);
    await assertStillHeld(first, PAIR_HOLD_TEXT);
    const lastEntry = await enterSkippingHold(last);
    const lastWork = lastArriverWorkRecord(lastEntry);
    const firstWork = lastArriverWorkRecord(first.entry);
    expect(
      requestHandlerMs(lastWork),
      `last arriver grouping ${Math.round(requestHandlerMs(lastWork))}ms vs first ${Math.round(requestHandlerMs(firstWork))}ms`
    ).toBeLessThan(requestHandlerMs(firstWork) + ENTRY_REQUEST_MAX_MS);
    await expect(last.page.getByRole("button", { name: "rock" })).toBeVisible();
    await assertWaiterReleasedWithLastArriver(first, lastEntry);
    await expect(first.page.getByRole("button", { name: "rock" })).toBeVisible();
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

test("last choice releases the waiting partner without a safety poll", { tag: "@both" }, async ({
  browser
}) => {
    // After both players reach the action page, the first submit waits in place.
    // The second submit is a POST /response last arrival, which is a different
    // finalize path from the first GET /timeline skip. A last-arrival GET can
    // 302 after page_uuid advances; first-paint waits for the 200 HTML body.
    // Settle the first hold (and its websocket hold-resume) before the last
    // arriver enters, so that overlay POST cannot NOWAIT-lock the waiter row.
  const { experiment, sessions } = await startHoldExperiment(browser, RPS_DIR, [
    "choice_hold_first",
    "choice_hold_second"
  ]);
  const [first, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: PAIR_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await first.page.waitForTimeout(SETTLE_HOLD_MS);
    await assertStillHeld(first, PAIR_HOLD_TEXT);
    const lastEntry = await enterSkippingHold(last);
    await assertWaiterReleasedWithLastArriver(first, lastEntry);

    await armChoiceHold(first, {
      holdText: PAIR_HOLD_TEXT,
      prompt: "Round results",
      buttonName: "rock"
    });
    const lastChoice = await submitLastChoice(last, {
      buttonName: "paper",
      prompt: "Round results"
    });
    await assertWaiterReleasedWithLastArriver(first, lastChoice, {
      prompt: "Round results"
    });
    await expect(first.page.locator("#main-body")).toContainText("You lost.");
    await expect(last.page.locator("#main-body")).toContainText("You won!");
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

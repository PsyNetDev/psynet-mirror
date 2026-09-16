const path = require("path");
const { test, expect } = require("./fixtures");
const {
  ACTION_PROMPT,
  GROUP_HOLD_TEXT,
  RESULTS_PROMPT,
  armChoiceHold,
  assertAllWaitersReleasedTogether,
  assertNoSessionErrors,
  assertStillHeld,
  assertWaiterReleasedWithLastArriver,
  closeHoldSessions,
  enterPossiblyHeldArrival,
  enterSkippingHold,
  enterWaitingHold,
  pickConcurrentLastArriver,
  isAuthoredWaiterArrival,
  startHoldExperiment,
  stopExperiment,
  submitChoiceMaybeHeld,
  submitLastChoice
} = require("./stackedHoldHarness");

const TRIO_DIR = path.resolve("tests/playwright/experiments/stacked_group_holds");

test("last of three skips stacked group holds", { tag: "@both" }, async ({
  browser
}) => {
  // The second member must still first-paint a hold. The third member
  // self-skips released stacked waits and may first-paint a silent catch-up
  // hold. Waiting partners leave on overlay wake.
  const { experiment, sessions } = await startHoldExperiment(browser, TRIO_DIR, [
    "trio_first",
    "trio_second",
    "trio_third"
  ]);
  const [first, second, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await enterWaitingHold(second, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await assertStillHeld(first, GROUP_HOLD_TEXT);
    const lastEntry = await enterSkippingHold(last);
    await expect(last.page.getByRole("button", { name: "go" })).toBeVisible();
    await assertAllWaitersReleasedTogether([first, second], lastEntry);
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

test("two late trio members arriving together release every waiter", { tag: "@both" }, async ({
  browser
}) => {
  // Concurrent last arrivals share one group fill. Arm both late members at
  // first paint so a hold that clears before Playwright looks at the chip still
  // has to prove a wake token, hold-resume POST, and server-driven resume.
  // In legacy mode that clear can reload the document while the probe is
  // attaching or while waitForHeldParticipantToResume is waiting for the hold
  // chip to leave; treat a destroyed execution context (including Playwright
  // toHaveCount Received: undefined) as a cleared hold. Concurrent POST
  // /participant calls serialize in Dallinger and retry with expovariate
  // sleep, so overlapping signup wall time uses SERIALIZED_SIGNUP_MAX_MS, not
  // the GET /timeline handler budget. A skipper filled the barrier; a slower
  // first-paint hold is a waiter. A late member who only resumes via websocket
  // reconnect is still a last arriver, not a waiter that must show a partner
  // wake→end clock. Poller and last-arriver GET /timeline can both publish the
  // same waiting token, then a stacked-hold reload posts once more on websocket
  // onOpen; allow three hold-resume POSTs. Overlay linger uses one 2500ms
  // floor plus 1500ms per extra hop; waiter-release spread and GET
  // /timeline stay 2200/3000.
  const { experiment, sessions } = await startHoldExperiment(browser, TRIO_DIR, [
    "trio_wait",
    "trio_late_a",
    "trio_late_b"
  ]);
  const [first, lateA, lateB] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    const [arrivalA, arrivalB] = await Promise.all([
      enterPossiblyHeldArrival(lateA, {
        holdText: GROUP_HOLD_TEXT,
        prompt: ACTION_PROMPT
      }),
      enterPossiblyHeldArrival(lateB, {
        holdText: GROUP_HOLD_TEXT,
        prompt: ACTION_PROMPT
      })
    ]);
    const laterArrival = pickConcurrentLastArriver([arrivalA, arrivalB]);
    const laterEntry = laterArrival.entry;
    await assertWaiterReleasedWithLastArriver(first, laterEntry, {
      allowWebsocketResume: true,
      maxHoldResumePosts: 3
    });
    const heldLate = [];
    if (isAuthoredWaiterArrival(arrivalA)) {
      heldLate.push(lateA);
    }
    if (isAuthoredWaiterArrival(arrivalB)) {
      heldLate.push(lateB);
    }
    if (heldLate.length) {
      await assertAllWaitersReleasedTogether(heldLate, laterEntry, {
        allowWebsocketResume: true,
        maxHoldResumePosts: 3
      });
    }
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

test("last of three choices releases both waiting members", { tag: "@both" }, async ({
  browser
}) => {
  // The post-choice barrier is a POST /response last arrival with two people
  // already held. Both have to leave without a safety poll. Entry first-paint
  // must follow a last-arrival GET /timeline 302 to the 200 HTML document.
  const { experiment, sessions } = await startHoldExperiment(browser, TRIO_DIR, [
    "trio_choice_a",
    "trio_choice_b",
    "trio_choice_c"
  ]);
  const [first, second, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await enterWaitingHold(second, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    const lastEntry = await enterSkippingHold(last);
    await assertAllWaitersReleasedTogether([first, second], lastEntry);

    await armChoiceHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: RESULTS_PROMPT
    });
    await armChoiceHold(second, {
      holdText: GROUP_HOLD_TEXT,
      prompt: RESULTS_PROMPT
    });
    const lastChoice = await submitLastChoice(last, { prompt: RESULTS_PROMPT });
    await assertAllWaitersReleasedTogether([first, second], lastChoice, {
      prompt: RESULTS_PROMPT
    });
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

test("last of four releases waiters and they catch up", { tag: "@both" }, async ({
  browser
}) => {
  // A larger group adds more wake targets on the same last-arriver request.
  // Members 1-3 must stay held until member 4 lands, then overlay-hop the
  // remaining stacked waits. Each hop can need its own hold-resume POST
  // (grouper, then init, then prepare). Three overlapping next-page renders
  // can spread overlay leave times on CI; waiter-release spread stays 2200ms.
  // Overlay linger is one 2500ms floor plus 1500ms per extra catch-up hop.
  const { experiment, sessions } = await startHoldExperiment(
    browser,
    TRIO_DIR,
    ["quartet_a", "quartet_b", "quartet_c", "quartet_d"],
    { env: { PSYNET_STACKED_GROUP_SIZE: "4" } }
  );
  const [first, second, third, last] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await enterWaitingHold(second, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await enterWaitingHold(third, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await assertStillHeld(first, GROUP_HOLD_TEXT);
    await assertStillHeld(second, GROUP_HOLD_TEXT);
    const lastEntry = await enterSkippingHold(last);
    await expect(last.page.getByRole("button", { name: "go" })).toBeVisible();
    await assertAllWaitersReleasedTogether([first, second, third], lastEntry);
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

test("two late choices complete a trio without a safety poll", { tag: "@both" }, async ({
  browser
}) => {
  // After grouping, the remaining race is POST /response. One member waits
  // on the post-choice barrier while the other two submit together. A skipper
  // filled that barrier. A late submit that first-paints a hold, even if the
  // chip is already gone, still has to resume from a server-driven
  // hold-resume rather than a skip. Poller and last-arriver GET /timeline can
  // both publish the same waiting token, then a stacked-hold reload posts
  // once more on websocket onOpen; allow three hold-resume POSTs on grouping
  // as well as on the later concurrent choices. Overlay linger uses one
  // 2500ms floor plus 1500ms per extra hop; spread/GET /timeline stay
  // 2200/3000.
  const { experiment, sessions } = await startHoldExperiment(browser, TRIO_DIR, [
    "trio_choice_wait",
    "trio_choice_late_a",
    "trio_choice_late_b"
  ]);
  const [first, lateA, lateB] = sessions;

  try {
    await enterWaitingHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    await enterWaitingHold(lateA, {
      holdText: GROUP_HOLD_TEXT,
      prompt: ACTION_PROMPT
    });
    const lastEntry = await enterSkippingHold(lateB);
    await assertAllWaitersReleasedTogether([first, lateA], lastEntry, {
      allowWebsocketResume: true,
      maxHoldResumePosts: 3
    });

    await armChoiceHold(first, {
      holdText: GROUP_HOLD_TEXT,
      prompt: RESULTS_PROMPT
    });
    const [choiceA, choiceB] = await Promise.all([
      submitChoiceMaybeHeld(lateA, {
        holdText: GROUP_HOLD_TEXT,
        prompt: RESULTS_PROMPT
      }),
      submitChoiceMaybeHeld(lateB, {
        holdText: GROUP_HOLD_TEXT,
        prompt: RESULTS_PROMPT
      })
    ]);
    const laterChoice = pickConcurrentLastArriver([choiceA, choiceB]);
    await assertWaiterReleasedWithLastArriver(first, laterChoice, {
      prompt: RESULTS_PROMPT,
      allowWebsocketResume: true,
      maxHoldResumePosts: 3
    });
    const heldLate = [];
    if (isAuthoredWaiterArrival(choiceA)) {
      heldLate.push(lateA);
    }
    if (isAuthoredWaiterArrival(choiceB)) {
      heldLate.push(lateB);
    }
    if (heldLate.length) {
      await assertAllWaitersReleasedTogether(heldLate, laterChoice, {
        prompt: RESULTS_PROMPT,
        allowWebsocketResume: true,
        maxHoldResumePosts: 3
      });
    }
    await assertNoSessionErrors(sessions);
  } finally {
    await closeHoldSessions(sessions);
    await stopExperiment(experiment.proc);
  }
});

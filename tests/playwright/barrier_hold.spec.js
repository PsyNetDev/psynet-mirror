const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertNoBackendError,
  beginExperiment,
  completeInitialGateway,
  startExperiment,
  startResponseSubmitTracker,
  stopExperiment,
  withFreshParticipantIds
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function delayChatSocketOpen(context) {
  let currentSocket;
  let socketCount = 0;
  const attempts = Array.from({ length: 2 }, () => ({
    created: deferred(),
    opened: deferred(),
    release: deferred()
  }));

  await context.routeWebSocket(
    (url) =>
      url.pathname === "/chat" &&
      url.searchParams.get("channel") === "modular_page_chat",
    async (socket) => {
      const attempt = socketCount;
      socketCount += 1;
      attempts[attempt]?.created.resolve();
      await attempts[attempt]?.release.promise;
      currentSocket = socket;
      const server = socket.connectToServer();
      socket.onMessage((message) => {
        if (String(message).includes('"type":"join_room"')) {
          attempts[attempt]?.opened.resolve();
        }
        server.send(message);
      });
    }
  );

  return {
    initial: {
      created: attempts[0].created.promise,
      opened: attempts[0].opened.promise,
      release: attempts[0].release.resolve
    },
    reconnect: {
      created: attempts[1].created.promise,
      opened: attempts[1].opened.promise,
      release: attempts[1].release.resolve
    },
    disconnect: () => {
      void currentSocket.close({
        code: 1012,
        reason: "Exercise chat reconnect"
      });
    },
    releaseAll: () =>
      attempts.forEach((attempt) => attempt.release.resolve())
  };
}

test("default barriers hold the current page until websocket release", { tag: "@inplace-only" }, async ({
  browser
}) => {
  const experiment = startExperiment(
    path.resolve("demos/experiments/rock_paper_scissors")
  );
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  const delayedChatSocket = await delayChatSocketOpen(firstContext);
  let firstParticipant;
  let secondParticipant;

  try {
    const recruitmentUrl = await experiment.urlPromise;
    firstParticipant = await beginExperiment(
      await firstContext.newPage(),
      firstContext,
      withFreshParticipantIds(recruitmentUrl, "barrier_hold_first")
    );
    secondParticipant = await beginExperiment(
      await secondContext.newPage(),
      secondContext,
      withFreshParticipantIds(recruitmentUrl, "barrier_hold_second")
    );

    // Both participants enter together, so this spec does not cover a
    // last-arriver first paint. See stacked_entry_holds.spec.js.
    await Promise.all([
      completeInitialGateway(firstParticipant),
      completeInitialGateway(secondParticipant)
    ]);
    await Promise.all([
      expect(firstParticipant.locator("#main-body")).toContainText(
        "Choose your action",
        { timeout: STEP_TIMEOUT_MS }
      ),
      expect(secondParticipant.locator("#main-body")).toContainText(
        "Choose your action",
        { timeout: STEP_TIMEOUT_MS }
      )
    ]);
    await secondParticipant.waitForFunction(
      () => Boolean(window.psynet?.arrivalUpdates?.connection?.isOpen?.()),
      { timeout: STEP_TIMEOUT_MS }
    );

    const pageErrors = [];
    firstParticipant.on("pageerror", (error) => pageErrors.push(error.message));
    secondParticipant.on("pageerror", (error) => pageErrors.push(error.message));
    const firstResponses = startResponseSubmitTracker(firstParticipant);
    await firstParticipant.getByRole("button", { name: "rock" }).click();
    await expect(
      firstParticipant.locator("#psynet-timeline-hold-indicator")
    ).toBeVisible({ timeout: STEP_TIMEOUT_MS });
    await expect(
      firstParticipant.locator(".psynet-timeline-hold-title")
    ).toHaveText("Waiting for your partner");
    await expect(
      firstParticipant.locator(".psynet-timeline-hold-progress")
    ).toHaveCount(0);
    // The partner is still on choose_action. Grouped pages must subscribe to
    // arrival_updates even when sync_group_links was not already loaded.
    const arrivalNotice = secondParticipant.locator("#psynet-arrival-notice");
    await expect(arrivalNotice).toHaveText("Your partner is ready.", {
      timeout: STEP_TIMEOUT_MS
    });
    await expect(arrivalNotice).toHaveCSS("white-space", "nowrap");
    await expect(arrivalNotice).toHaveAttribute("title", "Your partner is ready.");
    await expect(arrivalNotice).toBeVisible();
    await expect(
      secondParticipant.locator("#timeline-header #psynet-arrival-notice")
    ).toHaveCount(1);
    if (process.env.ARTIFACT_DIR) {
      await secondParticipant.setViewportSize({ width: 375, height: 667 });
      await secondParticipant.screenshot({
        path: `${process.env.ARTIFACT_DIR}/rps_arrival_notice_phone_default.png`,
      });
    }
    const longNoticeText =
      "Your partner is ready to continue. Please wait a little longer while we get everything ready for the next trial.";
    await secondParticipant.evaluate((message) => {
      window.psynet.showArrivalNotice(message);
    }, longNoticeText);
    await secondParticipant.setViewportSize({ width: 375, height: 667 });
    const longNotice = await arrivalNotice.evaluate((el) => ({
      height: el.getBoundingClientRect().height,
      overflowed: el.scrollWidth > el.clientWidth,
    }));
    expect(longNotice.height).toBeLessThan(48);
    expect(longNotice.overflowed).toBeTruthy();
    await expect(arrivalNotice).toHaveAttribute("title", longNoticeText);
    if (process.env.ARTIFACT_DIR) {
      await secondParticipant.screenshot({
        path: `${process.env.ARTIFACT_DIR}/rps_arrival_notice_phone.png`,
      });
    }
    await secondParticipant.setViewportSize({ width: 1280, height: 720 });
    await secondParticipant.evaluate(() => {
      window.psynet.showArrivalNotice("Your partner is ready.");
    });
    await expect(secondParticipant.locator("#main-body")).toContainText(
      "Choose your action"
    );
    await expect(firstParticipant.locator("#main-body")).toContainText(
      "Choose your action"
    );
    if (process.env.ARTIFACT_DIR) {
      await firstParticipant.screenshot({
        path: `${process.env.ARTIFACT_DIR}/rps_hold_progress.png`,
        fullPage: true
      });
      await secondParticipant.screenshot({
        path: `${process.env.ARTIFACT_DIR}/rps_arrival_notice.png`,
        fullPage: true
      });
    }
    await expect(firstParticipant.locator("body")).toHaveClass(/timeline-held/);

    // The initial WebSocket connection reconciles once. Afterwards a short
    // wait should not produce the old twice-per-second response polling.
    await firstParticipant.waitForTimeout(1000);
    const settledResponseCount = firstResponses.getCount();
    // The minimum safety-poll interval is 2000 ms, so this bounded window can
    // contain at most one fallback check regardless of jitter.
    await firstParticipant.waitForTimeout(1500);
    expect(firstResponses.getCount()).toBeLessThanOrEqual(
      settledResponseCount + 1
    );

    await secondParticipant.getByRole("button", { name: "paper" }).click();
    await Promise.all([
      expect(firstParticipant.locator("#main-body")).toContainText(
        "Round results",
        { timeout: STEP_TIMEOUT_MS }
      ),
      expect(secondParticipant.locator("#main-body")).toContainText(
        "Round results",
        { timeout: STEP_TIMEOUT_MS }
      )
    ]);
    await expect(firstParticipant.locator("#main-body")).toContainText(
      "You lost."
    );
    await expect(secondParticipant.locator("#main-body")).toContainText(
      "You won!"
    );
    await expect(
      firstParticipant.locator("#psynet-timeline-hold-indicator")
    ).toHaveCount(0);

    // The first participant's chat transport is still CONNECTING here. Hold
    // channels are not routed, so both participants must already have reached
    // the round results before the chat transport is released.
    await delayedChatSocket.initial.created;
    const chatMessage = "Barrier hold chatroom regression";
    const chatInput = firstParticipant.locator("#chatroom-chat-input");
    const sendButton = firstParticipant.locator("#chatroom-send-btn");
    await chatInput.fill(chatMessage);
    await expect(sendButton).toBeDisabled();

    // Exercise the close-after-enable race directly. A rejected send must
    // restore the disabled state and retain the participant's draft.
    await sendButton.evaluate((button) => {
      button.disabled = false;
      button.click();
    });
    await expect(sendButton).toBeDisabled();
    await expect(chatInput).toHaveValue(chatMessage);

    delayedChatSocket.initial.release();
    await delayedChatSocket.initial.opened;
    await expect(sendButton).toBeEnabled();
    await sendButton.click();
    await Promise.all([
      expect(firstParticipant.locator("#chatroom-messages")).toContainText(
        chatMessage,
        { timeout: STEP_TIMEOUT_MS }
      ),
      expect(secondParticipant.locator("#chatroom-messages")).toContainText(
        chatMessage,
        { timeout: STEP_TIMEOUT_MS }
      )
    ]);

    delayedChatSocket.disconnect();
    await delayedChatSocket.reconnect.created;
    await expect(sendButton).toBeDisabled();

    const reconnectMessage = "Chat still works after reconnect";
    await chatInput.fill(reconnectMessage);
    delayedChatSocket.reconnect.release();
    await delayedChatSocket.reconnect.opened;
    await expect(sendButton).toBeEnabled();
    await sendButton.click();
    await Promise.all([
      expect(firstParticipant.locator("#chatroom-messages")).toContainText(
        reconnectMessage,
        { timeout: STEP_TIMEOUT_MS }
      ),
      expect(secondParticipant.locator("#chatroom-messages")).toContainText(
        reconnectMessage,
        { timeout: STEP_TIMEOUT_MS }
      )
    ]);

    firstResponses.stop();
    await assertNoBackendError(firstParticipant);
    await assertNoBackendError(secondParticipant);
    expect(pageErrors).toEqual([]);
  } finally {
    delayedChatSocket.releaseAll();
    await firstContext.close();
    await secondContext.close();
    await stopExperiment(experiment.proc);
  }
});

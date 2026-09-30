const path = require("path");
const { test, expect } = require("./fixtures");
const {
  withExperiment, completeInitialGateway, waitForVideoRecordingReady,
  waitForNextEnabled,
} = require("./psynetHarness");

for (const receiveBeforeClosing of [false, true]) {
  test(`recording resolves after reload and close (server received: ${receiveBeforeClosing}) @inplace-only`, async ({page, context}) => {
    test.setTimeout(120000);
    let held;
    let received = false;
    await context.route("**/media-upload/*", async route => {
      held = route;
      if (receiveBeforeClosing) {
        const response = await route.fetch();
        expect(response.status()).toBe(204);
        received = true;
      }
      // Keep the browser request pending in both cases; only one sends bytes.
    });
    await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
      await completeInitialGateway(p);
      await expect(p.locator("#main-body")).toContainText("Record a short clip.");
      await waitForVideoRecordingReady(p, {timeoutMs:45000});
      await waitForNextEnabled(p,30000);
      const response = p.waitForResponse(r => new URL(r.url()).pathname === "/response" && r.request().method() === "POST");
      await p.locator("#next-button").click();
      const accepted = await (await response).json();
      expect(accepted.recording_uploads).toHaveLength(1);
      const id = accepted.recording_uploads[0].id;
      const stateUrl = new URL(`/test-recording-state/${id}`, p.url()).href;
      const readState = async () => {
        const response = await context.request.get(stateUrl);
        expect(response.ok()).toBe(true);
        return response.json();
      };
      await expect(p.locator("#main-body")).toContainText("Independent page reached.");
      await expect.poll(() => Boolean(held)).toBe(true);
      if (receiveBeforeClosing) await expect.poll(() => received).toBe(true);
      const initial = await readState();
      expect(initial.received).toBe(receiveBeforeClosing);
      expect(initial.trial_id).toBeNull();
      const dialogs = [];
      p.on("dialog", async dialog => { dialogs.push(dialog.type()); await dialog.accept(); });
      await p.reload({timeout:10000});
      await expect(p.locator("#main-body")).toContainText("Independent page reached.");
      expect(dialogs).toEqual([]);
      await p.close();
      await expect.poll(async () => (await readState()).status, {timeout:90000, intervals:[500,1000,2000]}).toBe(receiveBeforeClosing ? "deposited" : "expired");
      const final = await readState();
      expect(final.deadline).toBe(initial.deadline);
      expect(final.deposited).toBe(receiveBeforeClosing);
      expect(final.participant_failed).toBe(false);
    });
  });
}

test("Finish reaches recruiter exit while recording upload is held @inplace-only", async ({page, context}) => {
  test.setTimeout(60000);
  let held;
  await context.route("**/media-upload/*", route => { held = route; });
  const previous = process.env.PSYNET_TEST_RECORDING_EXIT;
  process.env.PSYNET_TEST_RECORDING_EXIT = "1";
  try {
    await withExperiment(page, context, path.resolve("tests/playwright/experiments/asynchronous_recording"), async p => {
      await completeInitialGateway(p);
      await expect(p.locator("#main-body")).toContainText("Record a short clip.");
      await waitForVideoRecordingReady(p, {timeoutMs:30000});
      await waitForNextEnabled(p,30000);
      await p.locator("#next-button").click();
      await expect(p.locator("#main-body")).toContainText("Independent page reached.");
      await expect.poll(() => Boolean(held)).toBe(true);
      await waitForNextEnabled(p,30000);
      await p.locator("#next-button").click();
      await expect(p.locator("#Finish")).toBeVisible();
      await p.locator("#Finish").click();
      await expect(p).toHaveURL(/recruiter-exit/, {timeout:10000});
    });
  } finally {
    if (previous === undefined) delete process.env.PSYNET_TEST_RECORDING_EXIT;
    else process.env.PSYNET_TEST_RECORDING_EXIT = previous;
  }
});

const path = require("path");
const {test, expect} = require("./fixtures");
const {withExperiment, completeInitialGateway, waitForVideoRecordingReady, waitForNextEnabled} = require("./psynetHarness");

test("missing answer expires and the unaffected imitation chain completes @inplace-only", async ({page, context}) => {
  test.setTimeout(180000);
  let uploads = 0;
  await context.route("**/media-upload/*", route => {
    uploads += 1;
    // Permanent transport rejection leaves the accepted reservation pending until
    // its real server deadline. Later recordings use the real receiver/worker.
    return uploads === 1 ? route.fulfill({status:403}) : route.continue();
  });
  await withExperiment(page, context, path.resolve("tests/playwright/experiments/missing_chain_recording"), async p => {
    await completeInitialGateway(p);
    for (let trial = 0; trial < 3; trial += 1) {
      if (trial === 2) {
        await expect(p.locator("#main-body")).toContainText("Watch the previous recording.");
        const video = p.locator("video#prompt");
        await expect.poll(() => video.evaluate(el => el.readyState >= 2)).toBe(true);
        await waitForNextEnabled(p,30000);
        await p.locator("#next-button").click();
      }
      await expect(p.locator("#main-body")).toContainText("Record the gesture.", {timeout:90000});
      await waitForVideoRecordingReady(p, {timeoutMs:30000});
      await waitForNextEnabled(p,30000);
      const acceptance = p.waitForResponse(r => new URL(r.url()).pathname === "/response" && r.request().method() === "POST");
      await p.locator("#next-button").click();
      const accepted = await (await acceptance).json();
      expect(accepted.submission).toBe("approved");
      expect(accepted.recording_uploads).toHaveLength(1);
      if (trial > 0) {
        await expect(p.locator("#main-body")).toContainText("Recording accepted.", {timeout:60000});
        await waitForNextEnabled(p,30000);
        await p.locator("#next-button").click();
      }
    }
    // The fixture also checks persisted failure/finalization, separate networks,
    // skipped analysis of missing media, and the ordinary 2/3 performance score.
    await expect(p.locator("#main-body")).toContainText("Chain checks passed.", {timeout:60000});
    expect(uploads).toBe(3);
  });
});

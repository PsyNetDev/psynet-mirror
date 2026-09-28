const path = require("path");
const {test,expect} = require("./fixtures");
const {withExperiment,completeInitialGateway,clickConsentButton,waitForTimelinePageReady,waitForNextEnabled} = require("./psynetHarness");
const experiment = path.resolve("demos/features/background_recording");

test("background clips survive page changes without changing button answers @inplace-only",async ({page,context}) => {
  test.setTimeout(120000);
  const held = [];
  await context.route("**/media-upload/*",route => {held.push(route);});
  await withExperiment(page,context,experiment,async p => {
    await completeInitialGateway(p);
    await expect(p.locator("#background-recording-permission")).toHaveCount(0);
    await clickConsentButton(p);
    await p.getByRole("button",{name:"Enable camera",exact:true}).click();
    const slots=[];
    for (const prompt of ["First judgment", "Second judgment"]) {
      await expect(p.locator("#main-body")).toContainText(prompt);
      await waitForTimelinePageReady(p);
      await expect.poll(() => p.locator("#background-recording-status").getAttribute("data-bytes").then(Number)).toBeGreaterThan(0);
      const response = p.waitForResponse(r => new URL(r.url()).pathname === "/response" && r.request().method() === "POST");
      await p.getByRole("button",{name:"Yes",exact:true}).click();
      const accepted = await (await response).json();
      expect(accepted.submission).toBe("approved");
      expect(accepted.recording_uploads).toHaveLength(1);
      slots.push(accepted.recording_uploads[0]);
    }
    await expect(p.locator("#main-body")).toContainText("Independent page reached.");
    expect(slots[0].id).not.toBe(slots[1].id);
    await expect.poll(() => held.length).toBe(2);
    for (const route of held) {
      const received = p.waitForResponse(r => r.url() === route.request().url());
      await route.continue();
      expect((await received).status()).toBe(204);
    }
    await waitForNextEnabled(p,30000);
  });
});

test("denied camera permission allows both answers without prompting again @inplace-only",async ({page,context}) => {
  test.setTimeout(120000);
  await context.addInitScript(() => {
    if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("Denied","NotAllowedError"));
  });
  await withExperiment(page,context,experiment,async p => {
    await completeInitialGateway(p);
    await clickConsentButton(p);
    await p.getByRole("button",{name:"Enable camera",exact:true}).click();
    for (const prompt of ["First judgment", "Second judgment"]) {
      await expect(p.locator("#main-body")).toContainText(prompt);
      await waitForTimelinePageReady(p);
      const response = p.waitForResponse(r => new URL(r.url()).pathname === "/response" && r.request().method() === "POST");
      await p.getByRole("button",{name:"Yes",exact:true}).click();
      const accepted = await (await response).json();
      expect(accepted.submission).toBe("approved");
      expect(accepted.recording_uploads).toEqual([]);
    }
    await expect(p.locator("#main-body")).toContainText("Independent page reached.");
  });
});

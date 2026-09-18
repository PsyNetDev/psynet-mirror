const path = require("path");
const { test, expect } = require("./fixtures");

const {
  assertInplaceTimelinePathActive,
  assertNoBackendError,
  clickNextAndWait,
  completeInitialGateway,
  waitForMainBodyContains,
  withExperiment
} = require("./psynetHarness");

const STEP_TIMEOUT_MS = 120000;

test("deprecated scripts and js_links force full reloads with classic globals", { tag: "@inplace-only" }, async ({
  page,
  context
}) => {
  await context.addInitScript(() => {
    window.__documentToken = `${Date.now()}-${Math.random()}`;
  });

  const absDir = path.resolve(
    "tests/playwright/experiments/legacy_page_javascript"
  );

  await withExperiment(page, context, absDir, async (experimentPage) => {
    await completeInitialGateway(experimentPage);
    await assertInplaceTimelinePathActive(experimentPage, 20000);

    await waitForMainBodyContains(
      experimentPage,
      "Legacy scripts page",
      STEP_TIMEOUT_MS
    );
    await expect(experimentPage.locator("#legacy-global-marker")).toHaveText(
      "from-scripts"
    );
    expect(
      await experimentPage.evaluate(() => ({
        requiresReload:
          window.psynet.page.attributes?.requires_full_page_reload === true,
        legacyGlobal: Function("return legacyGlobal")(),
        legacyLinks: window.__legacyLinkActivations
      }))
    ).toEqual({
      requiresReload: true,
      legacyGlobal: "from-scripts",
      legacyLinks: 1
    });

    const firstToken = await experimentPage.evaluate(
      () => window.__documentToken
    );
    let navigations = 0;
    experimentPage.on("framenavigated", (frame) => {
      if (frame === experimentPage.mainFrame()) {
        navigations += 1;
      }
    });

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Legacy checkpoint page",
      STEP_TIMEOUT_MS
    );

    const checkpoint = await experimentPage.evaluate(() => ({
      token: window.__documentToken,
      legacyGlobal:
        document.getElementById("legacy-checkpoint-marker")?.dataset
          .legacyGlobal || null,
      legacyLinks:
        document.getElementById("legacy-checkpoint-marker")?.dataset
          .legacyLinks || null,
      requiresReload:
        window.psynet.page.attributes?.requires_full_page_reload === true
    }));
    expect(checkpoint.token).not.toBe(firstToken);
    expect(navigations).toBeGreaterThanOrEqual(1);
    expect(checkpoint).toMatchObject({
      legacyGlobal: "missing",
      legacyLinks: "0",
      requiresReload: false
    });

    await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);
    await waitForMainBodyContains(
      experimentPage,
      "Legacy finish page",
      STEP_TIMEOUT_MS
    );
    await assertNoBackendError(experimentPage);
  });
});

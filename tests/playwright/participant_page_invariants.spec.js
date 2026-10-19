const path = require("path");
const { test, expect } = require("./fixtures");

const {
  beginExperiment,
  clickNextAndWait,
  completeInitialGateway,
  startExperiment,
  stopExperiment,
  waitForMainBodyContains,
  waitForTimelinePageReady
} = require("./psynetHarness");

const { assertPageInvariants } = require("./participantPageInvariants");

const STEP_TIMEOUT_MS = 120000;

// Inner viewport of a typical 13–14" laptop. A taller size (for example
// 1280×900) hides a centimetre of overflow that still produces a scrollbar.
const DESKTOP_VIEWPORT = { width: 1280, height: 720 };

// A narrow viewport exercises the mobile branch of the theme, where horizontal
// overflow is the failure that matters.
const MOBILE_VIEWPORT = { width: 375, height: 780 };

async function assertLaptopAndPhoneInvariants(page, label) {
  await page.setViewportSize(DESKTOP_VIEWPORT);
  await assertPageInvariants(page, `${label} (laptop)`);
  await page.setViewportSize(MOBILE_VIEWPORT);
  await page.waitForTimeout(300);
  await assertPageInvariants(page, `${label} (phone)`);
  await page.setViewportSize(DESKTOP_VIEWPORT);
}

/**
 * Walks the participant flow of a purpose-built experiment and asserts the
 * structural invariants on every page, including the pre-timeline pages.
 *
 * The experiment is deliberately small: the invariants are properties of the
 * shared chrome and layout primitives, so a handful of representative pages
 * exercises them without paying for a sweep over every demo.
 */
test(
  "participant pages satisfy structural layout invariants",
  { tag: "@both" },
  async ({ page, context }) => {
    const experimentDir = path.resolve(
      "tests/playwright/experiments/participant_page_invariants"
    );

    // startExperiment rather than withExperiment, so that the ad page can be
    // checked before beginExperiment clicks through it.
    const { proc, urlPromise } = startExperiment(experimentDir);

    try {
      const url = await urlPromise;

      await page.setViewportSize(DESKTOP_VIEWPORT);
      await page.goto(url);
      await page.waitForSelector("#begin-button, button.btn-primary", {
        timeout: 30000
      });
      await assertLaptopAndPhoneInvariants(page, "ad page");

      const experimentPage = await beginExperiment(page, context, url);
      await assertLaptopAndPhoneInvariants(experimentPage, "consent gateway");

      await completeInitialGateway(experimentPage);

      // The timeline is fixed, so each step is named rather than discovered.
      await waitForMainBodyContains(
        experimentPage,
        "plain information page",
        STEP_TIMEOUT_MS
      );
      await assertLaptopAndPhoneInvariants(experimentPage, "information page");
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await waitForMainBodyContains(experimentPage, "radio options", STEP_TIMEOUT_MS);
      await assertLaptopAndPhoneInvariants(experimentPage, "radio page (nothing selected)");
      await experimentPage.locator("#alpha").check();
      await assertLaptopAndPhoneInvariants(experimentPage, "radio page (option selected)");
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      await waitForMainBodyContains(experimentPage, "push buttons", STEP_TIMEOUT_MS);
      await assertLaptopAndPhoneInvariants(experimentPage, "push button page");
      await experimentPage.locator("#left").click();

      await waitForMainBodyContains(experimentPage, "tall graphic", STEP_TIMEOUT_MS);
      await waitForTimelinePageReady(experimentPage, STEP_TIMEOUT_MS);
      await assertLaptopAndPhoneInvariants(experimentPage, "graphic page");
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // A 16:9 graphic at 90% of the window would be wider than the 900px
      // surface. The box must shrink to the surface and keep that aspect
      // ratio, rather than clamping width independently of height.
      await waitForMainBodyContains(
        experimentPage,
        "landscape graphic",
        STEP_TIMEOUT_MS
      );
      await waitForTimelinePageReady(experimentPage, STEP_TIMEOUT_MS);
      await assertLaptopAndPhoneInvariants(experimentPage, "landscape graphic page");
      const landscapeBox = await experimentPage.locator("#graphic-prompt").boundingBox();
      expect(landscapeBox).not.toBeNull();
      expect(landscapeBox.width / landscapeBox.height).toBeCloseTo(16 / 9, 2);

      // A landscape phone is shorter than the laptop chrome allowance. The
      // graphic must remain visible rather than collapsing to 0px.
      await experimentPage.setViewportSize({ width: 780, height: 375 });
      await experimentPage.waitForTimeout(300);
      const landscapePhoneBox = await experimentPage
        .locator("#graphic-prompt")
        .boundingBox();
      expect(landscapePhoneBox).not.toBeNull();
      expect(landscapePhoneBox.width).toBeGreaterThan(80);
      expect(landscapePhoneBox.height).toBeGreaterThan(40);
      await experimentPage.setViewportSize(DESKTOP_VIEWPORT);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // A page that declares expect_scrolling=True is exempt from the
      // reachability check but must still keep its controls reachable at the
      // end of the scroll.
      await waitForMainBodyContains(
        experimentPage,
        "deliberately long page",
        STEP_TIMEOUT_MS
      );
      await assertPageInvariants(experimentPage, "long page (expect_scrolling)");

      // Re-check the same page narrow. The mobile branch of the theme changes
      // the surface's margins and padding, where horizontal overflow is the
      // failure that matters.
      await experimentPage.setViewportSize(MOBILE_VIEWPORT);
      await experimentPage.waitForTimeout(300);
      await assertPageInvariants(experimentPage, "long page (mobile viewport)");
      await experimentPage.setViewportSize(DESKTOP_VIEWPORT);
      await clickNextAndWait(experimentPage, STEP_TIMEOUT_MS);

      // A long option list grows its panel instead of scrolling inside it, so
      // the rows must stay reachable by scrolling the page.
      await waitForMainBodyContains(experimentPage, "long radio list", STEP_TIMEOUT_MS);
      await assertPageInvariants(experimentPage, "long radio list (expect_scrolling)");
      const optionPanelScroll = await experimentPage.evaluate(() => {
        const panel = document.querySelector(".psynet-options");
        return panel.scrollHeight - panel.clientHeight;
      });
      expect(optionPanelScroll).toBeLessThanOrEqual(1);
    } finally {
      await stopExperiment(proc);
    }
  }
);

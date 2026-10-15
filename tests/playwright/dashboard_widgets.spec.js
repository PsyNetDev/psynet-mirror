const path = require("path");
const { test, expect } = require("./fixtures");
const { startExperiment, stopExperiment } = require("./psynetHarness");

const DASHBOARD_CREDENTIALS = { username: "playwright", password: "playwright-dashboard" };

test.use({ httpCredentials: DASHBOARD_CREDENTIALS });

// PsyNet's dashboard pages extend Dallinger's dashboard, which loads jQuery 4
// and Bootstrap 5. The checks share one experiment and assert softly, so each
// broken widget is reported.
test("dashboard widgets", { tag: "@both" }, async ({ page }) => {
  const { proc, urlPromise } = startExperiment(path.resolve("demos/experiments/trial"), {
    env: {
      dashboard_user: DASHBOARD_CREDENTIALS.username,
      dashboard_password: DASHBOARD_CREDENTIALS.password
    }
  });
  try {
    const origin = new URL(await urlPromise).origin;

    // A page that loads a second Bootstrap bundle toggles each dropdown twice,
    // so it never opens.
    await test.step("Basic data Database dropdown", async () => {
      await page.goto(`${origin}/dashboard/data`);
      await page.locator(".dropdown-toggle", { hasText: "Database" }).click();
      await expect.soft(page.locator(".dropdown-menu.show")).toBeVisible();
    });

    // Bootstrap 5 escapes tooltip HTML unless the element sets data-bs-html.
    await test.step("timeline module tooltip", async () => {
      await page.goto(`${origin}/dashboard/timeline`);
      await page.locator(".progress.modules").first().click();
      await expect.soft(page.locator(".tooltip-inner b")).toHaveText("word_ratings");
    });

    // jQuery UI releases before 1.13 throw on jQuery 4, so the range slider
    // never initializes. Kept last because a throwing jQuery UI fails evaluate().
    await test.step("resources dashboard slider", async () => {
      await page.goto(`${origin}/dashboard/resources`);
      await expect.soft(page.locator("#slider-range")).toBeVisible();
      const slider = await page.evaluate(() => ({
        jquery: window.jQuery.fn.jquery,
        initialized: !!window.jQuery("#slider-range").slider("instance")
      }));
      expect.soft(slider).toEqual({ jquery: "4.0.0", initialized: true });
    });
  } finally {
    await stopExperiment(proc);
  }
});

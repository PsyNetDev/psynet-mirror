const path = require("path");
const { test, expect } = require("./fixtures");
const { startExperiment, stopExperiment } = require("./psynetHarness");

const DASHBOARD_CREDENTIALS = { username: "playwright", password: "playwright-dashboard" };

test.use({ httpCredentials: DASHBOARD_CREDENTIALS });

// The resources dashboard loads PsyNet's jQuery UI on top of the jQuery that
// Dallinger's dashboard provides. jQuery UI releases before 1.13 throw on
// jQuery 4, so the range slider never initializes.
test("resources dashboard slider", { tag: "@both" }, async ({ page }) => {
  const { proc, urlPromise } = startExperiment(path.resolve("demos/experiments/trial"), {
    env: {
      dashboard_user: DASHBOARD_CREDENTIALS.username,
      dashboard_password: DASHBOARD_CREDENTIALS.password
    }
  });
  try {
    const origin = new URL(await urlPromise).origin;

    await page.goto(`${origin}/dashboard/resources`);
    await expect(page.locator("#slider-range")).toBeVisible();
    const slider = await page.evaluate(() => ({
      jquery: window.jQuery.fn.jquery,
      initialized: !!window.jQuery("#slider-range").slider("instance")
    }));
    expect(slider).toEqual({ jquery: "4.0.0", initialized: true });
  } finally {
    await stopExperiment(proc);
  }
});

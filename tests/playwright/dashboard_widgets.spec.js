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

    // The page script fills in the window's start and end times once it has
    // set up the range inputs and drawn the plot.
    await test.step("resources dashboard range", async () => {
      await page.goto(`${origin}/dashboard/resources`);
      await expect.soft(page.locator("#range-from")).toBeVisible();
      await expect.soft(page.locator("#range-to")).toBeVisible();
      await expect.soft(page.locator("#min")).not.toBeEmpty();
      await expect.soft(page.locator("#max")).not.toBeEmpty();
    });
  } finally {
    await stopExperiment(proc);
  }
});

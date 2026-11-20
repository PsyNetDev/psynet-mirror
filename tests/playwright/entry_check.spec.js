const path = require("path");
const { test, expect } = require("./fixtures");
const { startExperiment, stopExperiment } = require("./psynetHarness");

const CHECK_TIMEOUT_MS = 30000;
const EXPERIMENT_DIR = "tests/playwright/experiments/entry_check";

// Helper: start server, navigate to ad URL, run check, stop server.
async function withAdPage(page, options, fn) {
  const { proc, urlPromise } = startExperiment(path.resolve(EXPERIMENT_DIR), options);
  try {
    const adUrl = await urlPromise;
    await page.goto(adUrl);
    await fn(page);
  } finally {
    await stopExperiment(proc);
  }
}

test(
  "css_has: compatibility warning shown when CSS :has is not supported",
  { tag: "@both" },
  async ({ page, context }) => {
    // Override CSS.supports so that :has selector support appears missing.
    // This validates the renderBrowserWarning() path and the JS syntax fix.
    await context.addInitScript(() => {
      const _orig = CSS.supports.bind(CSS);
      CSS.supports = (...args) => {
        if (args.length === 1 && /has/.test(args[0])) return false;
        return _orig(...args);
      };
    });

    await withAdPage(page, {}, async (adPage) => {
      await expect(adPage.locator("#browser-compatibility-modal")).toBeVisible({
        timeout: CHECK_TIMEOUT_MS,
      });
    });
  }
);

test(
  "no compatibility warning with default config",
  { tag: "@both" },
  async ({ page }) => {
    await withAdPage(page, {}, async (adPage) => {
      // Wait for the async browser check to complete, not just the Begin button
      // which appears before detectIncognito() resolves.
      await adPage.waitForFunction(
        () => window.browser?.isValidated === true,
        { timeout: CHECK_TIMEOUT_MS }
      );
      await expect(adPage.locator("#browser-compatibility-modal")).toBeHidden();
    });
  }
);

test(
  "force_google_chrome=True admits Chromium and warns other browsers",
  { tag: "@both" },
  async ({ page, browserName }) => {
    await withAdPage(
      page,
      { env: { force_google_chrome: "true" } },
      async (adPage) => {
        const modal = adPage.locator("#browser-compatibility-modal");
        if (browserName === "chromium") {
          await adPage.waitForFunction(
            () => window.browser?.isValidated === true,
            { timeout: CHECK_TIMEOUT_MS }
          );
          await expect(modal).toBeHidden();
        } else {
          await expect(modal).toBeVisible({ timeout: CHECK_TIMEOUT_MS });
        }
      }
    );
  }
);

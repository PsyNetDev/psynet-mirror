const headless = String(process.env.HEADLESS || "true").toLowerCase() !== "false";
const timeout = Number(process.env.PLAYWRIGHT_TIMEOUT_MS || 10 * 60 * 1000);

/** @type {import('@playwright/test').PlaywrightTestConfig} */
const config = {
  // Specs must declare a mode tag so CI can select without hardcoding paths:
  //   @both         — safe under inplace and legacy reload modes
  //   @inplace-only — requires default inplace_timeline_transitions
  //   @legacy-only  — requires inplace_timeline_transitions=false
  // CI: playwright_e2e_default uses --grep '@both|@inplace-only'
  //     playwright_e2e_legacy uses --grep '@both|@legacy-only'
  testDir: "tests/playwright",
  workers: 1,
  timeout,
  retries: 0,
  use: {
    headless,
    viewport: { width: 1024, height: 768 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    permissions: ["microphone", "camera"],
    launchOptions: {
      args: [
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--font-render-hinting=none",
        "--disable-font-subpixel-positioning",
        "--disable-lcd-text",
        "--force-color-profile=srgb",
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--allow-http-screen-capture",
        "--auto-select-desktop-capture-source=Entire screen",
        "--enable-usermedia-screen-capturing"
      ]
    }
  }
};

module.exports = config;

const base = require("../../../playwright.config");

/** @type {import('@playwright/test').PlaywrightTestConfig} */
module.exports = {
  ...base,
  testDir: __dirname,
  use: {
    ...base.use,
    viewport: { width: 390, height: 760 },
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
    screenshot: "off",
    video: "off",
    trace: "off"
  }
};

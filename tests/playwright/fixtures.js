const base = require("@playwright/test");
const { stopRunningExperiments } = require("./psynetHarness");

// Browsers report this when a ResizeObserver callback changes layout again
// within the same frame. The notifications are delivered in the next frame,
// so nothing is lost; SurveyJS triggers it on narrow mobile viewports.
const BENIGN_PAGE_ERRORS = [
  "ResizeObserver loop completed with undelivered notifications."
];

function formatPageError(entry) {
  return [
    `URL: ${entry.url || "<unknown>"}`,
    entry.message,
    entry.stack && entry.stack !== entry.message ? entry.stack : null
  ]
    .filter(Boolean)
    .join("\n");
}

const test = base.test.extend({
  failOnPageErrors: [
    async ({ context, page }, use) => {
      const errors = [];
      const trackedPages = new WeakSet();

      const trackPage = (candidate) => {
        if (!candidate || trackedPages.has(candidate)) {
          return;
        }
        trackedPages.add(candidate);
        candidate.on("pageerror", (error) => {
          const message = error.message || String(error);
          if (BENIGN_PAGE_ERRORS.includes(message)) {
            return;
          }
          errors.push({
            url: candidate.url(),
            message,
            stack: error.stack || ""
          });
        });
      };

      trackPage(page);
      context.pages().forEach(trackPage);
      context.on("page", trackPage);

      await use();

      if (errors.length > 0) {
        throw new Error(
          "Uncaught browser page error(s):\n\n" +
            errors.map(formatPageError).join("\n\n---\n\n")
        );
      }
    },
    { auto: true }
  ],
  // A test that times out never reaches its own stopExperiment, and the
  // server it leaves on the debug port would fail every later test.
  stopLeftoverExperiments: [
    async ({}, use) => {
      await use();
      await stopRunningExperiments();
    },
    { auto: true }
  ]
});

module.exports = {
  ...base,
  test,
  expect: base.expect
};

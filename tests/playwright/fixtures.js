const base = require("@playwright/test");

function formatPageError(entry) {
  return [
    `URL: ${entry.url || "<unknown>"}`,
    entry.message,
    entry.stack && entry.stack !== entry.message ? entry.stack : null
  ]
    .filter(Boolean)
    .join("\n");
}

// PsyNet logs this when a page shown in advance turned out different from the
// server's, for example because show_trial depends on an earlier answer.
const STALE_PAGE_WARNING = "The page shown in advance no longer matches the server's";

const test = base.test.extend({
  allowStalePages: [false, { option: true }],
  failOnStalePages: [
    async ({ context, allowStalePages }, use) => {
      const warnings = [];
      context.on("console", (message) => {
        if (message.text().includes(STALE_PAGE_WARNING)) {
          warnings.push(message.text());
        }
      });

      await use();

      if (warnings.length > 0 && !allowStalePages) {
        throw new Error(
          "Pages shown in advance didn't match the server's:\n\n" + warnings.join("\n")
        );
      }
    },
    { auto: true }
  ],
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
          errors.push({
            url: candidate.url(),
            message: error.message || String(error),
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
  ]
});

module.exports = {
  ...base,
  STALE_PAGE_WARNING,
  test,
  expect: base.expect
};

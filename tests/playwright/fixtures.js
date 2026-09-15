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
  test,
  expect: base.expect
};

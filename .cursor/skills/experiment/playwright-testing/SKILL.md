---
name: playwright-testing
description: Write Playwright tests for PsyNet participant pages, including layout checks and participant-flow specs. Use when adding tests/participant-flow.spec.js, calling psynetLayout.check(), asserting that pages fit the window, or driving a browser walk of an experiment.
compatibility: Requires Playwright.
---

# Playwright testing

Bots (`psynet test local`) walk the timeline and check answers. They never
render a layout. A Playwright walk is how you check that pages fit the window
and that participant-facing controls behave in a real browser.

Store the walk with the experiment as `tests/participant-flow.spec.js`. Prefer
JavaScript Playwright, and commit `package.json` / the lockfile when the test
depends on npm packages. Assert enabled and disabled controls, trial
transitions, validation or feedback, completion, and saved responses — not
only that the runner can click Next.

For constructing pages, use `develop-experiment-front-end/SKILL.md`. For
ffmpeg participant recordings, use `record-participant-video/SKILL.md`.

## Read first

Read these pages before acting. In a PsyNet source checkout read `docs/<page>.rst`; otherwise fetch `https://psynetdev.gitlab.io/PsyNet/<page>.html`.

- `test/frontend` — Playwright walks and `psynetLayout.check()`
- `test/backend` — what bots check and what they miss

## Setup

Install Playwright in the experiment directory and commit `package.json` and
`package-lock.json`:

```bash
npm init -y
npm install --save-dev @playwright/test
npx playwright install chromium
```

Add `node_modules/` and `test-results/` to `.gitignore`. The stock `deploy.toml`
already excludes `node_modules`; add `test-results` to its `[exclude].paths`.
Start the experiment with `psynet debug local` in one terminal and wait for the
ad URL in its log. Set `PSYNET_URL` to that URL's scheme, host and port, and run
the walk from another terminal:

```bash
PSYNET_URL=http://127.0.0.1:5000 npx playwright test tests/participant-flow.spec.js
```

PsyNet's own Playwright tests import helpers from `tests/playwright/` in the
PsyNet source repository. Those helpers are not installed with PsyNet, so an
experiment's tests define the few they need, as below.

## Walking the pages

Enter the timeline through the ad and consent pages, then wait for the first
timeline page:

```js
const { test, expect } = require("@playwright/test");

const BASE = process.env.PSYNET_URL || "http://127.0.0.1:5000";

async function startParticipant(page) {
  await page.goto(`${BASE}/ad?generate_tokens=true&recruiter=hotair`);
  await page.locator("#begin-button").click();
  await page.locator("#consent").waitFor();
  await clickAndWaitForNextPage(page, page.locator("#consent"));
}
```

After a click that leaves the page, wait for the **next** page, not for a
ready page. `#main-body[data-page-ready='true']` is still true on the old page
until the server answers, so waiting for it alone returns immediately and the
next check or screenshot runs one page behind. Every timeline page has its own
`window.pageUuid`; wait until it changes and the new page is ready:

```js
async function clickAndWaitForNextPage(page, locator) {
  const oldUuid = await page.evaluate(() => window.pageUuid ?? null);
  await locator.click();
  await page.waitForFunction(
    (uuid) =>
      window.pageUuid &&
      window.pageUuid !== uuid &&
      document.getElementById("main-body")?.dataset.pageReady === "true",
    oldUuid,
  );
}

await clickAndWaitForNextPage(page, page.locator("#next-button"));
await expect(page.locator("#main-body")).toContainText("How pleasant");
```

A barrier or `wait_while` hold keeps the visible page and its
`window.pageUuid` until the hold ends, so the helper also waits through holds.

## Layout checks

Every participant page loads `psynetLayout`. After the page is ready, call
`check()` and expect an empty list:

```js
async function assertPageLayout(page, label) {
  // Playwright's cursor stays where the last click left it, so a control can be
  // measured in its hover state unless the pointer is parked away from content.
  await page.mouse.move(0, 0).catch(() => {});
  const violations = await page.evaluate(async () => {
    if (!window.psynetLayout?.check) {
      throw new Error("psynetLayout.check is not available on this page");
    }
    return await window.psynetLayout.check();
  });
  expect(violations, label).toEqual([]);
}

await clickAndWaitForNextPage(page, page.locator("#next-button"));
await assertPageLayout(page, "radio page");
```

On ad or consent pages, wait for that page's own durable control (`#begin-button`
or `#consent`) instead of `#main-body`. Use a 1280×720 viewport. If the
experiment allows mobile devices (the default), repeat the check at 375×780.
Pages that are meant to be taller than the window must set
`expect_scrolling=True`; otherwise a scrollbar is a failure.

Run this check after each page is ready and before taking a screenshot. Do not
fold these checks into `psynet test local`.

## Stable waits

Wait for the effect the last action was supposed to produce: the next page (as
above), a durable prompt, a control becoming enabled, or a URL change. Do not
assert countdown text or short-lived status labels.

Gateway, consent, and timeline pages have different DOM. Do not assume
`#main-body` exists on the ad page. If the timeline is known in advance, encode
that sequence; treat a mismatch as a failure rather than hunting for a Next
button. Click normally; use `force: true` only for a known overlay that blocks
actionability.

For `AudioPrompt`, assert PsyNet sound-state or trial events, not a DOM
`<audio>` element. For `VideoPrompt`, assert `video#prompt`.

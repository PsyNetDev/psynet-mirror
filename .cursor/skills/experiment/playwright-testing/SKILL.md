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

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i --no-ignore "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

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

Set a short action timeout in `playwright.config.js`, so a click that can never
succeed fails within seconds instead of looking like a hang until the test
timeout:

```js
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests",
  use: { actionTimeout: 20000 },
});
```

Start the experiment with `psynet debug local` in one terminal and wait for the
ad URL in its log. From a non-interactive background shell, keep stdin open
(`tail -f /dev/null | psynet debug local`), or the server can stop silently.
Set `PSYNET_URL` to the ad URL's scheme, host and port, and run the walk from
another terminal:

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

## Rating controls

`RatingControl`, `MultiRatingControl` and `SurveyJSControl` are rendered by
SurveyJS, which hides each radio input behind its label. `radio.check()` then
retries until the action timeout ("label intercepts pointer events"). Click the
label and assert the radio:

```js
const main = page.locator("#main-body");
await main.locator("label.sd-rating__item").nth(rating - 1).click();
await expect(main.locator("input[type=radio]").nth(rating - 1)).toBeChecked();
```

## Built-in prescreeners

A headphone test can't be passed by listening in a headless browser. Built-in
prescreeners store the answer as `correct_answer` in the trial definition, and
PsyNet has no browser hook that exposes it, so read it from the experiment's
local database with `psql`. Point `DATABASE_URL` at the local database of the
experiment you are walking, never at a deployed experiment's database:

```js
const { execFileSync } = require("child_process");

const DATABASE_URL =
  process.env.DATABASE_URL || "postgresql://dallinger:dallinger@localhost/dallinger";

async function currentTrialDefinition(page) {
  const participantId = await page.evaluate(() => window.psynet.participantId);
  const query =
    `SELECT definition::text FROM trial WHERE participant_id = ${participantId} ` +
    "ORDER BY id DESC LIMIT 1";
  return JSON.parse(execFileSync("psql", [DATABASE_URL, "-At", "-c", query]).toString());
}

// Headphone tests show one button per answer, with the answer as its id.
const { correct_answer } = await currentTrialDefinition(page);
const answer = page.locator(`#main-body button[id="${correct_answer}"]`);
await expect(answer).toBeEnabled({ timeout: 20000 });
await clickAndWaitForNextPage(page, answer);
```

Test the failing path with bots rather than in the walk (see `test/backend`,
"Bots that fail a prescreener").

## Incognito mode

With `force_incognito_mode = True`, PsyNet guesses incognito mode from the
browser's storage quota, which headless Chromium reports inconsistently, so a
walk can stop at "You need to use the incognito mode". Report an
incognito-sized quota before any page loads:

```js
const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
await context.addInitScript(() => {
  const quota = 100 * 1024 * 1024;
  const storage = navigator.webkitTemporaryStorage;
  if (storage) storage.queryUsageAndQuota = (callback) => callback(0, quota);
  if (navigator.storage?.estimate) {
    navigator.storage.estimate = async () => ({ usage: 0, quota });
  }
});
const page = await context.newPage();
```

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

await page.waitForSelector("#main-body[data-page-ready='true']");
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

Wait for the effect the last action was supposed to produce: a durable prompt,
a control becoming enabled, or a URL change. Do not assert countdown text or
short-lived status labels. When the contract is first paint — for example the
last group member skipping a partner wait — assert the first `GET /timeline`
HTML. An eventual prompt can arrive from the poller after a hold was already
shown. `entry.timeline.durationMs` is that HTML 200 (or 503). Last-arrival
grouping work is `lastArriverWorkRecord` (the 302, or the submit POST), not
the follow-up body:

```js
const entry = await enterTimelineAfterGateway(page);
expect(entry.paint.type).toBe("ModularPage");
expect(entry.paint.showsHold).toBe(false);
expect(entry.timeline.busy).toBe(false);
expect(entry.timeline.durationMs).toBeLessThan(2500);
expect(requestHandlerMs(lastArriverWorkRecord(entry))).toBeLessThan(2500);
expect(entry.start.consentToTimelineMs).toBeLessThan(6000);
```

When a partner is already on a hold, use `stackedHoldHarness.js`:
`enterWaitingHold` wraps the resume probe, silences the 2s safety poll, and
arms `waitForHeldParticipantToResume` before the last arriver consents.
`assertWaiterReleasedWithLastArriver` then checks that overlay leave
(`resumedAtMs`) is timed from `lastArriverReleaseAtMs` (the grouping request
finish, not the follow-up HTML 200), resume is `server notification` or
`queued hold wake` (not `safety poll` or `hold timeout`), inplace mode issues no
extra `GET /timeline`, and overlay linger (wake→end wallclock, including
gunicorn listen-queue) stays under
`max(1800ms, hold-resume Server-Timing app + 500ms)`. A short HTTP 503 may
retry once; do not fold gunicorn `queue~` into linger or waiter spread. Print
`queue~` in summaries so a long wait can be split into handler time versus
pool occupancy. Spread is overlay leave times, at most 1500ms:

```js
await enterWaitingHold(first, { holdText: "Waiting for your partner" });
const lastEntry = await enterSkippingHold(last);
await assertWaiterReleasedWithLastArriver(first, lastEntry);
```

Legacy reload mode may issue one follow-up timeline document.

Concurrent late arrivals must wrap and arm at first paint, inside the same
`Promise.all` as consent. If the hold chip is already gone, still assert the
first-paint `wake_token`, a hold-resume POST, and no extra GET `/timeline` in
inplace mode. Those late waiters may resume from `websocket connection` as well
as `server notification`.

Gateway, consent, and timeline pages have different DOM. Do not assume
`#main-body` exists on the ad page. If the timeline is known in advance, encode
that sequence; treat a mismatch as a failure rather than hunting for a Next
button. Click normally; use `force: true` only for a known overlay that blocks
actionability.

For `AudioPrompt`, assert PsyNet sound-state or trial events, not a DOM
`<audio>` element. For `VideoPrompt`, assert `video#prompt`.

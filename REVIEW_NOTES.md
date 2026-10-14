# Review notes — issues/10085-browser-capability-screening

This file is review scaffolding; delete before merging.

---

## Decisions already made — please don't re-open

**`force_google_chrome` default flipped to `False`.**
`browser_capabilities` + `BrowserCapabilityCheck` make the setting largely
obsolete. Flipping the default now avoids a future breaking change and
reflects actual practice (most experiments don't need Chrome-only behavior).
Authors who need it set it explicitly.

**`force_google_chrome` semantics widened to Chromium-based browsers (Edge,
Brave, Opera).**
The setting has always meant "needs a Chromium engine," not literally Chrome.
Widening is more correct. Caveat documented: Lucid QuestionID 1035 still gates
on the Chrome brand at the panel level, so Lucid recruitment with
`force_google_chrome=True` continues to exclude Edge/Brave participants upstream
even though PsyNet now admits them.

**`min_browser_version` removed rather than extended to non-Chrome browsers.**
The `css_has` check (Chrome 105 / Safari 15.4 / Firefox 121) is a sufficient
and more principled floor. A per-browser version config adds complexity without
meaningful benefit over the feature-detect approach.

**`BrowserCapabilityCheck` uses `UnsuccessfulEndPage`, not
`terminateParticipant("missing-capability")`.**
`terminateParticipant` on ad/consent was dead code that would have thrown
`ReferenceError` (defined in `psynet.js`, not loaded there). The prescreener
runs inside the timeline where `UnsuccessfulEndPage` is the correct termination
path.

**Permission-requiring capabilities (`microphone`, `camera`) use approach (b):
dedicated intro page + `getUserMedia`, not silent pre-check.**
(a) skip-in-prescreener means failure surfaces mid-experiment after demographics.
(c) `permissions.query` is unreliable on Safari and can't distinguish
"not yet asked" from "denied". (b) gives the earliest possible failure with a
clear, contextual message.

**`browser_capabilities` is explicit-only; no auto-derivation from the
timeline.**
Auto-derivation is fragile — controls inside `PageMaker` lambdas or conditional
branches are invisible at startup. The explicit declaration is always
authoritative.

**`video_recording` is one token, not `video_recording_webm` +
`video_recording_mp4`.**
Experiment authors declare that they need video recording; PsyNet picks the best
supported format at runtime. Format-specific tokens deferred to a future
format-aware recording ticket.

---

## Explicitly deferred — not oversights

- **Prolific auto-derivation** of `device_compatibility` /
  `peripheral_requirements` from `browser_capabilities`. High-priority
  follow-on ticket. For now, authors using Prolific must set
  `prolific_recruitment_config` manually.
- **detectIncognito library upgrade** (1.3.0 → current). The `.catch()`
  fallback makes the old version safe; a library swap is no longer urgent.
- **`force_google_chrome` rename.** Agreed it should eventually become
  something like `require_chromium`; deferred to a cleanup ticket.
- **`browser-support.rst` doc page** (per-browser capability table). Not
  added; deferred.
- **`entry_check.spec.js` end-to-end execution.** Not yet run against a live
  server; deferred.

---

## CI failures found and fixed during review

**`browser_capability_check.spec.js` both tests failed** — three bugs found and fixed:

**1. `nextPage` timing** (both tests): `psynet.nextPage()` guards on `pageReady === true` and `nextPagePending === false`. `finalizePageReady()` begins with `await new Promise(r => setTimeout(r, 0))` — a macrotask — so a `setTimeout(0)` scheduled inside `activate()` fires before `pageReady` becomes true. Fixed in `browser-capability-check.js` by listening for the `timelinePageReady` event (dispatched by `setPageReady(true)` inside `finalizePageReady`) and deferring `nextPage` one further macrotask via `setTimeout(0)`, ensuring both guards have cleared.

**2. `conditional` lambda wrong parameter names** (pass test — server 500): `call_function` in `utils.py` dispatches kwargs by name. The lambda used `exp, p` but `call_function_with_context` passes `experiment=` and `participant=`. Neither matched, so the function was called with zero arguments. Fixed by renaming to `lambda participant: ...`.

**3. `media.initAudioContext()` threw when AudioContext unavailable** (fail test): `trial.init()` → `media.init()` → `initAudioContext()` was called unconditionally during page activation, throwing `"No AudioContext available"` before the capability check could call `nextPage({passed: false})`. This also means real participants without AudioContext would see "This page could not be loaded" instead of being routed to `UnsuccessfulEndPage`. Fixed by having `initAudioContext` log a warning and return instead of throwing, and guarding the two call sites (`audioContext?.state`, `audioContext?.currentTime ?? 0`).

---

## Non-obvious implementation choices

**`BrowserCapabilityCheck` uses `PageMaker` to resolve `browser_capabilities`
at runtime, not at class definition time.**
`Experiment.browser_capabilities` is a class attribute resolved by
`PageMaker(lambda exp, p: ...)` so the prescreener works correctly when
`capabilities=None` (the default) — it reads from the experiment instance that
is live at that point in the timeline, not from a stale closure.

**`renderBrowserWarning()` JS syntax fix.**
The original code was missing a closing `}` for the inner
`if (!browser.isChrome)` block inside `if (browser.forceGoogleChrome ...)`.
With `force_google_chrome=False` (now the default), `renderBrowserWarning()`
would silently build no warning HTML for `css_has` failures. The fix is in
`browser-detect.html`; the commit message is "JS syntax fix."

**`PERMISSION_CAPABILITY_TOKENS` separate from `BROWSER_CAPABILITY_TOKENS`.**
Permission-requiring capabilities need a dedicated intro page and a
`getUserMedia` call; non-permission capabilities are silent feature-detects.
Keeping them in separate frozensets lets the prescreener split the page
sequence without inspecting each token individually.

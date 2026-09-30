---
name: record-participant-video
description: Record PsyNet participant-flow visual evidence with Playwright-driven interaction, screenshots, and headless video with in-page audio capture. Use when collecting participant evidence, creating participant.mp4, or documenting participant-facing behavior.
compatibility: Requires Playwright with page.screencast (tested with 1.63), Chromium, ffmpeg and ffprobe. The alternative device-capture routes need Xvfb and PulseAudio on Linux, or BlackHole on macOS.
---

# Record participant visual evidence

## Goal

Create an MP4 recording of the participant-facing PsyNet flow that includes:

- The browser viewport seen by the participant.
- Experiment audio when the experiment produces audio.
- Enough of the flow for reviewers to judge instructions, trials, responses,
  feedback, and completion behavior.

Drive the participant browser with Playwright by default, and record it with
the audio-capture helper shipped in this skill's `scripts/` directory (see
[Record video with audio](#record-video-with-audio)). It works headless on any
OS. Do not use agent browser control for canonical evidence capture unless
Playwright cannot exercise the flow; reserve browser control for quick
exploratory inspection and debugging.

Participant videos must be short, review-focused evidence artifacts. Do not
commit or publish videos longer than 3 minutes. For long or repetitive
experiments, use a Playwright-run visual review profile or concise
representative excerpt instead of every trial, as long as the excerpt
demonstrates the instructions, representative trials, responses, and completion
behavior, and automated checks or exported data cover the full experimental
structure.

If an already-recorded flow is complete but slightly too long, prefer an
accelerated copy over a hard truncation when the full sequence matters for
review. Make the speed-up only as aggressive as needed to fit under 3 minutes,
verify the result remains understandable, and do not use speed-up when real-time
timing, audio quality, or participant pacing is itself the evidence being judged.

Published `audit/artifacts/participant.mp4` files must be no larger than 1280x720.
Prefer 15 fps for UI walkthrough evidence unless smooth motion is essential.
Use H.264 with CRF 30-34, AAC audio when audio is needed, and `+faststart` so
reviewers can stream the file promptly.

## Evidence strategy

Use screenshots as the primary visual review artifact for static UI states:
instructions, consent/ad pages, representative trials, feedback, validation
errors, completion pages, and edge-case states. Save targeted screenshots under
`audit/artifacts/screenshots/`, using ordered descriptive names such as
`01-instructions.png` or `03-masked-trial.png`.
Capture the participant viewport only. In Playwright, set `fullPage: false`
explicitly so the image matches what fits on screen. Full-page captures stitch
content below the fold and mislead reviewers about the experimental interface.

Run the layout check from `playwright-testing/SKILL.md` **before** each
screenshot, so a passing image cannot hide overflow or footer occlusion.

When screenshots need review-facing captions, add
`audit/artifacts/screenshots/manifest.json` with a `captions` object that maps
screenshot paths to concise descriptions of what each image demonstrates.

Use video for behavior that screenshots cannot prove well: audio playback,
timing-sensitive displays, animation, masking, continuous interaction, live
multi-participant coordination, or a concise canonical walkthrough. When a new
trial type is the main contribution, record a very short focused clip of that
trial type rather than analyzing a long full-flow video.

For Playwright evidence scripts:

- Write the walk with `playwright-testing/SKILL.md`. Reuse that script for
  screenshots and the participant recording when possible.
- Playwright writes video (`page.screencast`, `recordVideo`) with its own
  ffmpeg binary. Install it first with `npx playwright install ffmpeg`; it is
  separate from the system `ffmpeg`, and without it the first recorded run
  fails with "Video rendering requires ffmpeg binary".
- Pace the recording with explicit waits, `slowMo`, or experiment `time_factor`
  settings so the actions remain understandable. Do not blast through the flow,
  but do not wait for agent-speed browser control either.
- Write screenshots and logs from that test to `audit/artifacts/`, not only to
  Playwright's default transient output folders.
- Keep the canonical experiment path unchanged. Use a documented minimal visual
  review profile only to make screenshots or short recordings reviewable.
- Detect experiment completion with the locale-independent `/recruiter-exit`
  URL rather than matching English page text; text matching breaks for
  non-English locales (for example when recording the same flow in several
  languages). Also note that PsyNet's end page presents its "Finish" button as
  a single `button.push-button`, so a runner that requires two or more push
  buttons before clicking will deadlock there.

## Workflow

1. Start the PsyNet experiment and capture the generated ad page URL.
2. Write or reuse a Playwright runner as in `playwright-testing/SKILL.md` that
   completes the participant path and captures the targeted screenshots needed
   for review.
3. Confirm the viewports from that skill's layout checks. Larger sizes hide
   overflow that still produces a scrollbar on a typical laptop.
4. For multi-participant flows, use separate browser profiles or Playwright
   contexts for each participant, for example separate Chrome `--user-data-dir`
   directories. Do not rely on multiple windows from one shared profile; shared
   browser/session state can cause misleading grouping or identity failures.
5. Start the recording before the participant opens the ad page, as in
   [Record video with audio](#record-video-with-audio).
6. Run the Playwright participant flow at a readable pace.
7. Stop recording after the completion page or after the relevant behavior has
   been demonstrated.
8. Save the final file as `audit/artifacts/participant.mp4`.
9. Play the MP4 back, or otherwise inspect it, and run `psynet audit validate`,
   which warns when an audio track is silent.

If recording fails or audio is missing, do not imply the participant video is
complete. Record the failure and the missing evidence as an audit blocker (and
in `audit/REPORT.md` or `audit/TIMELINE.md` as appropriate).

## Record video with audio

Headless Playwright plays audio to no device, so neither `recordVideo` nor a
screen recorder hears it. `scripts/audio-capture.cjs` records what the page
would play: an init script taps every Web Audio destination and every
`<audio>`/`<video>` element into one in-page recorder per document, and the
helper muxes that audio with a `page.screencast` video into an H.264/AAC MP4
(≤1280x720, 15 fps, peaks limited to -1 dBFS). The skill copy lives under
`.cursor/skills/psynet/` in the experiment; run `psynet scripts update` if the
file is missing.

```js
const {
  AUDIO_CAPTURE_LAUNCH_ARGS,
  startParticipantRecording,
} = require("../.cursor/skills/psynet/record-participant-video/scripts/audio-capture.cjs");

test.use({ launchOptions: { args: AUDIO_CAPTURE_LAUNCH_ARGS } });

test("recorded participant walk", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const recording = await startParticipantRecording(context);
  const page = recording.page;
  await page.goto(`${BASE}/ad?generate_tokens=true&recruiter=hotair`);
  // ... drive the walk ...
  await recording.finish("audit/artifacts/participant.mp4");
  await context.close();
});
```

Use a fresh context, and the page returned by `startParticipantRecording`.
`AUDIO_CAPTURE_LAUNCH_ARGS` lets pages start audio without a click; without it
audio that starts before the first click is lost. `finish` also writes the raw
video, per-page audio segments and `recording.json` to `recording.workDir`
(pass `{ workDir }` to choose it).

Each segment is shifted by a fixed pipeline latency, 100 ms by default. It was
measured on macOS with Chromium headless shell. On another machine or browser
build, measure it once from the experiment directory and pass the result as
`PSYNET_AUDIO_LATENCY_MS`:

```bash
node .cursor/skills/psynet/record-participant-video/scripts/measure-latency.cjs --seconds 20
PSYNET_AUDIO_LATENCY_MS=<recommendedLatencyMs> npx playwright test tests/participant-flow.spec.js
```

The script records `scripts/sync-probe.html` (a white flash and a 1 kHz beep
together every second), prints the beep-minus-flash offsets and
`recommendedLatencyMs`, and keeps the probe MP4. Add `--latency-ms 100` to
check the residual offset with a correction applied, `--navigate-after 10` to
check a second page load, and `--seconds 200` to check drift. Keep the summary
with the audit logs when timing matters. With the default correction, the
mean residual offset was about +5 ms (standard deviation 14 ms) over 200
seconds on macOS, with no measurable drift, and -2 ms in the Linux Playwright
Docker image.

Known limits of in-page capture:

- It needs Chromium (`captureStream` and WebM/Opus `MediaRecorder`).
- Only the top-level document is recorded; audio inside iframes is missed.
- Cross-origin media served without CORS headers records as silence.
- Audio that plays outside the page (browser extensions, OS sounds) and
  `OfflineAudioContext` rendering are not recorded.
- Each full page load starts a new segment; audio playing across a navigation
  is cut at the page change. PsyNet timeline pages usually stay in one
  document.

If `finish` warns that audio was not recorded, or validation reports a silent
track, fix the capture or fall back to device capture below.

## Record real device output

Use device capture when the evidence must include what the operating system
actually played, or when in-page capture cannot hear the audio (iframes,
cross-origin media). These routes need a headed browser.

- **Linux / Cursor Cloud:** read `references/linux-recording.md` for X11,
  PulseAudio null-sink routing, ffmpeg capture, and audio verification.
- **macOS:** read `references/macos-recording.md` for avfoundation capture
  with virtual audio devices such as BlackHole (needs an admin install).

Calibrate device capture with `scripts/sync-probe.html` as described in the
Linux reference.

## Evidence notes

- Prefer a short successful recording over a long unfocused one. For repetitive
  experiments, show the interaction pattern once or a few times and rely on
  automated validation or exported data to prove completeness.
- Keep participant videos at or below 3 minutes and 1280x720. Re-encode or trim
  before committing if the recording exceeds either limit.
- If neither in-page nor device audio capture works, include the visual
  recording if possible and explicitly document the missing audio as an audit
  blocker (and in `audit/REPORT.md` when relevant).
- For audio-focused experiments, add supporting evidence such as generated
  stimulus files, event logs, exported data, or command logs.
- When sharing a recorded video inline in a Cursor final response, warn the
  user if the evidence depends on audio: the Cursor agent video player may not
  play the audio track. Tell them to download the MP4 directly or open it in a
  local media player to hear the audio.

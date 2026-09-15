---
name: record-participant-video
description: Record PsyNet participant-flow visual evidence with Playwright-driven interaction, screenshots, and ffmpeg screen/audio capture. Use when collecting participant evidence, creating participant.mp4, or documenting participant-facing behavior.
compatibility: Requires Playwright, ffmpeg, ffprobe, and on Linux/PulseAudio setups a null sink for browser audio routing.
---

# Record participant visual evidence

## Goal

Create an MP4 recording of the participant-facing PsyNet flow that includes:

- The browser viewport seen by the participant.
- Experiment audio when the experiment produces audio.
- Enough of the flow for reviewers to judge instructions, trials, responses,
  feedback, and completion behavior.

Drive the participant browser with Playwright by default. Use `ffmpeg` for video
recording because browser-only video capture can miss system audio. Do not use
agent browser control for canonical evidence capture unless Playwright cannot
exercise the flow; reserve browser control for quick exploratory inspection and
debugging.

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
- When recording video with Playwright's built-in `recordVideo`, install
  Playwright's own ffmpeg binary first with `npx playwright install ffmpeg`. It is
  separate from the system `ffmpeg`; without it the first recorded run fails with
  "Video rendering requires ffmpeg binary". Playwright records `.webm`, so
  re-encode to the canonical `audit/artifacts/participant.mp4` (H.264, ≤1280x720,
  `+faststart`) afterwards.
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
5. Start `ffmpeg` screen and audio capture before running the scripted flow.
6. Run the Playwright participant flow at a readable pace.
7. Stop recording after the completion page or after the relevant behavior has
   been demonstrated.
8. Save the final file as `audit/artifacts/participant.mp4`.
9. Play the MP4 back, or otherwise inspect it, before treating it as valid
   evidence.

If recording fails or audio is missing, do not imply the participant video is
complete. Record the failure and the missing evidence as an audit blocker (and
in `audit/REPORT.md` or `audit/TIMELINE.md` as appropriate).

For audio-sensitive evidence, do not rely on a shared desktop/audio session
without calibration. Use the calibrated Linux workflow below, or record and
document why calibration was not possible.

When sharing a recorded video inline in a Cursor final response, warn the user
if the evidence depends on audio: the Cursor agent video player may not play the
audio track. Tell them to download the MP4 directly or open it in a local media
player to hear the audio.

## Platform recording

- **Linux / Cursor Cloud:** read `references/linux-recording.md` for X11,
  PulseAudio null-sink routing, ffmpeg capture, and audio verification.
- **macOS:** read `references/macos-recording.md` for avfoundation capture
  with virtual audio devices.

## Evidence notes

- Prefer a short successful recording over a long unfocused one. For repetitive
  experiments, show the interaction pattern once or a few times and rely on
  automated validation or exported data to prove completeness.
- Keep participant videos at or below 3 minutes and 1280x720. Re-encode or trim
  before committing if the recording exceeds either limit.
- If system audio capture cannot be configured, include the visual recording if
  possible and explicitly document the missing audio as an audit blocker (and in
  `audit/REPORT.md` when relevant).
- For audio-focused experiments, add supporting evidence such as generated
  stimulus files, event logs, exported data, or command logs.

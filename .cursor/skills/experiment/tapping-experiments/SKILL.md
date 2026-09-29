---
name: tapping-experiments
description: Design-discipline checklist for PsyNet tapping, rhythm, beat-perception, and sensorimotor-synchronization experiments; participant flow with REPP calibration, timing rules, export fields, simulated tapping profiles, and public-safety rules. Use alongside implement-experiment when participants tap along to audio.
---

# Tapping experiments

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `code/participants/prescreening_and_questionnaires`: REPP volume calibration, tapping calibration, and recording tests
- `code/using_stimuli`: generated audio stimuli such as metronomes
- `code/writing_pages`: timing within a page and progress stages
- `code/writing_a_trial_maker`: performance checks that analyze tapping recordings
- `code/trials/assets`: recorded and generated assets
- `test/backend`: bots and `test_check_bot`

## Start from a demo

- `demos/experiments/repp_prescreen`: the REPP calibration and recording
  tests from `psynet.prescreen`, on their own.
- `demos/experiments/tapping_static`: metronome and music tapping with
  `psynet.prescreen` calibration and REPP analysis.
- `demos/pipelines/tapping`: a fuller battery. It keeps its own, diverging
  copies of the prescreens in `repp_prescreens.py` and analyzes recordings in
  `repp_utils.py`. Prefer the `psynet.prescreen` classes unless you need
  those changes.

The REPP prescreens and analyses import the `repp` package, which
`psynet[experiment]` does not install. Add `repp-tapping` to the experiment's `requirements.txt`,
pinned as in the demos.

## Related skills

- `filter-participants/SKILL.md` before adding device, audio, microphone,
  recording, or tapping capability gates.
- `psychophysics/SKILL.md` when visual timing or reaction time also matters.
- `simulate-participants/SKILL.md` for bot tapping profiles.
- `record-participant-video/SKILL.md` for audio-sensitive participant-flow
  evidence.
- `deploy-experiment/SKILL.md` for deployment, exports, and teardown.

## Participant flow

A robust tapping experiment usually includes:

1. Consent and a notice that audio will be recorded.
2. Device and environment instructions: quiet room, supported browser,
   microphone permission, and the speaker or headphone policy.
3. Volume calibration with representative audio.
4. A recording or marker test to check that taps can be captured.
5. Tapping calibration with simple isochronous rhythms.
6. Practice trials with clear start and stop cues, and feedback or pass/fail
   logic where appropriate.
7. The main tapping trials.
8. Demographic or music-background questionnaires when scientifically
   relevant.
9. Completion and recruiter redirect.

## Timing and audio rules

- Give explicit silent periods before and after the stimulus so participants
  know when not to tap.
- Show progress stages such as "wait in silence", "start tapping", "stop
  tapping", and "press next".
- Keep audio duration, recording duration, and progress stages in sync, and
  make the recording window cover the whole tapping period.
- Keep timing constants in one place rather than scattering them across page
  text, controls, and analysis scripts.
- Give stimuli stable IDs and metadata; use a manifest for multi-file sets or
  when condition metadata matters.
- Deterministic generated isochronous stimuli are fine for calibration,
  testing, and public examples when documented.
- Keep construction signals (participant taps, derived onsets, pooled-tap
  summaries) separate from validation signals (ground-truth annotations,
  listener ratings, algorithmic baselines). Do not use ground truth to build
  participant-facing outputs unless the task says so.

## Data and exports

Save enough to reconstruct trial-level timing and stimulus assignment:

- participant, trial, and stimulus IDs, condition, and the audio asset key or
  a public-safe filename;
- the recording asset reference;
- raw, derived, and (when available) aligned tap onset times, and the number
  of detected taps;
- analysis status, failure flag, and failure reason;
- stimulus and recording durations;
- calibration status and practice or isochronous tapping score;
- consented covariates needed for interpretation, such as music background.

Check in the export that tapping trials, participants, questionnaire
responses, and recording references are all present and keyed to the same
stimulus IDs as the manifest.

## Validation and simulation

- Run `psynet test local` with bots covering the success path and at least
  one calibration or failure branch.
- In a browser, confirm that audio plays, recording permission works,
  progress stages match the timing, and completion works.
- Record evidence of at least one calibration or practice trial and one main
  trial.
- Export local or simulated data and check tap onsets, failure flags, and
  stimulus IDs.
- Include an analysis script or notebook summarizing valid trials per
  stimulus, taps per trial, inter-tap intervals, failed recordings, and
  coverage by condition.

Useful simulated profiles: good (plausible intervals, passes calibration),
too few taps, too many taps, off-tempo (stable but wrong period), noisy (high
interval variability), phase-shifted (consistently early or late), and
dropout (missing recording or incomplete trials).

Reports must say that simulated tapping validates the workflow and analysis
code, not human rhythm perception.

## Public-safety rules

- Keep public examples self-contained, with generated or demo audio and
  synthetic or anonymized data.
- If a real research pipeline uses ground truth, proprietary audio, or
  private exports, reuse only the patterns and keep the material out of
  public skills and demos.

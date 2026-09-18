---
name: tapping-experiments
description: Implement PsyNet tapping, rhythm, beat perception, and sensorimotor synchronization experiments with audio recording, calibration, export checks, and conservative interpretation.
---

# PsyNet tapping experiments

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general planning,
  implementation, simulation, export, analysis, and report workflow.
- Read `filter-participants/SKILL.md` before adding device,
  audio, microphone, recording, or tapping capability gates.
- Read `psychophysics/SKILL.md` when visual timing, reaction time, or exact
  stimulus display matters alongside tapping.
- Read `record-participant-video/SKILL.md` for audio-sensitive participant-flow
  evidence.
- Read `simulate-participants/SKILL.md` for bot or scripted tapping
  profiles.
- Read `deploy-experiment/SKILL.md` if the work involves deployment,
  exports, recruiter setup, or teardown.

## Participant flow

A robust tapping experiment should usually include:

1. Consent and an audio/recording notice.
2. Device and environment instructions: quiet room, appropriate browser,
   microphone permission, and the intended speaker/headphone policy.
3. Volume calibration with representative audio.
4. Recording or marker prescreening to verify usable audio/tap capture.
5. Tapping calibration with simple isochronous rhythms.
6. Practice trials with clear start/stop cues and pass/fail or feedback logic
   when appropriate.
7. Main rhythm or music tapping trials.
8. Demographic or music-background questionnaires when scientifically relevant.
9. Clean completion and recruiter redirect.

For public examples, use generated tones, generated metronomes,
short placeholder audio, or public/demo assets only.

## Timing and audio rules

- Use explicit pre-roll and post-roll periods so participants know when not to
  tap.
- Use visible progress stages such as "wait in silence", "start tapping", "stop
  tapping", and "press next".
- Keep audio duration, recording duration, and progress display synchronized.
- Store timing constants centrally rather than scattering them across page text,
  controls, and analysis scripts.
- Ensure the recording window covers the full intended tapping response period.
- Use stable stimulus ids and metadata. Prefer manifests for multi-file audio
  sets or when condition metadata matters.
- Deterministic generated isochronous stimuli are acceptable for calibration,
  testing, and public examples when documented.
- Do not use ground-truth annotations to construct participant-facing
  crowd-derived outputs unless the task explicitly says so.
- Separate construction signals from validation signals:
  - construction: participant taps, derived tap onsets, internally inferred
    timing, and pooled-tap summaries;
  - validation: ground-truth annotations, listener ratings, and algorithmic
    baselines.

## Data and exports

Save enough data to reconstruct trial-level timing and stimulus assignment.
Recommended export-visible fields include:

- participant id;
- trial id;
- stimulus id or stimulus name;
- audio asset key or public-safe filename;
- condition;
- recording asset reference when available;
- raw or derived tap onset times;
- aligned tap onset times when available;
- analysis status and failure flag;
- failure reason;
- number of detected taps;
- stimulus and recording duration;
- calibration status;
- practice or isochronous tapping score;
- consented participant covariates needed for interpretation, such as music
  background.

Export checks should confirm that tapping trial rows, participant rows,
response/post-survey rows, and recording references are present and keyed to the
same stimulus ids used in the manifest.

## Validation and simulation

- Run a Python import smoke test when practical.
- Run `psynet test local` with bots that cover the ordinary success path and at
  least one calibration or failure branch.
- Inspect a browser/manual run to confirm that audio plays, recording permission
  works, progress stages match timing, and completion works.
- Record participant-flow evidence showing at least one calibration or practice
  trial and one main tapping trial.
- Export local or simulated data and verify tap onset fields, failure flags, and
  stimulus ids.
- Include an analysis script or notebook that summarizes valid trials per
  stimulus, taps per trial, inter-tap intervals, failed recordings, and coverage
  by condition or stimulus.

Useful simulated profiles include:

- good: enough taps, plausible inter-tap intervals, passes calibration;
- too-few-taps: fails a minimum-tap threshold;
- too-many-taps: fails a maximum-tap or quality threshold;
- off-tempo: taps at a wrong but internally stable period;
- noisy: high inter-tap variability;
- phase-shifted: stable taps consistently early or late;
- dropout: missing recording or incomplete trials.

Reports must state that simulated tapping validates workflow and analysis code,
not human rhythm perception.

## Public-safety rules

- Keep public examples self-contained with generated/demo audio and synthetic or
  clearly anonymized mock PsyNet-format data.
- If a real research pipeline uses ground truth, proprietary audio, or private
  exports, summarize reusable patterns only and keep the source material out of
  public skills and demos.

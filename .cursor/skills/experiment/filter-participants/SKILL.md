---
name: filter-participants
description: Design, implement, and validate task-specific pre-screening for PsyNet experiments, including recruiter/platform alignment and pass/fail handling.
---

# Implement task-specific pre-screening

## Prerequisites

- Inspect PsyNet's current prescreening docs and demos before custom code:
  `~/PsyNet/docs/tutorials/prescreening_tasks.rst`,
  `~/PsyNet/docs/api/prescreen.rst`, and relevant demos under
  `~/PsyNet/demos/features/` and `~/PsyNet/demos/experiments/`.
- Read `references/recruitment-platform-notes.md` when the prescreener affects
  Prolific, Lucid/Cint, CloudResearch Connect, MTurk, or lab recruiter setup.

## What pre-screening should entail

1. Define the eligibility contract before coding: who should pass, who should
   fail, why the requirement is scientifically necessary, and whether failure is
   exclusionary, stratifying, or only a covariate for analysis.
2. Separate platform targeting from in-experiment validation:
   - stable demographics and panel attributes usually belong in recruiter
     filters or qualification JSON;
   - device, environment, comprehension, attention, and current capability checks
     usually belong at the start of the PsyNet timeline;
   - sensitive, ambiguous, or nonessential measures should generally be recorded
     rather than used to fail participants.
3. Keep the participant experience fair: put exclusion checks early, make
   instructions explicit, avoid revealing the desired answer when that would bias
   responses, and configure the recruiter path so screened-out participants are
   paid or returned according to the platform's current policy.
4. Record enough data to audit the gate: answers, scores, thresholds, failure
   tags, recruiter branch, and relevant device/language/task metadata.
5. Make the main experiment robust to the prescreener outcome. A failed
   participant should exit cleanly and should not consume main-task trials,
   stimuli, quotas, or downstream grouping capacity.

## PsyNet implementation hints

- Prefer built-in PsyNet prescreeners before writing custom ones:
  `AttentionTest`, `HugginsHeadphoneTest`, `ColorBlindnessTest`,
  `ColorVocabularyTest`, `LexTaleTest`, `LanguageVocabularyTest`,
  `AudioForcedChoiceTest`, `WikiVocab`/`BibleVocab`, and the REPP calibration
  and recording tests.
- Match prescreeners to task requirements. Use `HugginsHeadphoneTest` for
  headphone-dependent audio, color checks for color-critical visual tasks,
  vocabulary/language checks for language-dependent tasks, `AudioForcedChoiceTest`
  for task-specific audio categorization, and REPP checks for tapping/microphone
  setup. Do not chain incompatible requirements such as REPP laptop-speaker
  calibration with headphone-only tasks unless the design explicitly needs both.
- Put gates early in the `Timeline`, after consent and before expensive main
  trials. Attention checks may be embedded among demography pages when that is
  scientifically and ethically appropriate.
- For a single-question gate, implement a `Module` or `ModularPage` followed by
  `conditional(..., UnsuccessfulEndPage(failure_tags=["performance_check",
  "<reason>"]))`.
- For a scored battery, use `StaticTrialMaker` with
  `check_performance_at_end=True`, `performance_check_type = "score"`, unique
  `id_`/labels, and usually `fail_trials_on_premature_exit=False`.
- Calibrate thresholds carefully. PsyNet's default score check is strict
  `score > performance_threshold`; set thresholds and comments so the intended
  minimum passing score is unambiguous.
- Implement bot paths for both pass and fail cases. `get_bot_response` or
  `bot_response` should produce the same formatted answer shape as a browser
  participant, and tests should assert failure status, module-state performance
  checks, and absence of main-task trials for failed bots.
- If the experiment may be translated, mark prescreener instructions, feedback,
  button labels, and failure messages for translation when you create them.

## Recruiter/platform alignment

- Mirror stable criteria in recruiter setup where available, then validate inside
  PsyNet only when the platform recommends or requires validation.
- For Prolific, prefer built-in filters for standard attributes. For niche
  criteria, use Prolific custom screening or a two-study approach when that is the
  launch plan. In PsyNet, verify the current Prolific failure path before launch;
  do not assume a failed `UnsuccessfulEndPage` automatically uses Prolific's
  screen-out API.
- For Lucid/Cint, keep qualification JSON, `LucidConsent`, and any
  `verify_lucid_qualifications(...)` pages synchronized with the in-experiment
  gate. `performance_check` failures are treated differently from ordinary
  terminations by the PsyNet Lucid recruiter.
- For lab recruiter or other custom recruiters, make sure `failure_tags` and
  `failed_reason` are meaningful enough for the external system and later audit.
- For deployment readiness, read `deploy-experiment/SKILL.md` and verify that
  qualification files, recruiter config, app description, estimated duration, and
  compensation match the prescreening flow.

## Validation

- Run the experiment's construction check and `psynet test local`; add or update
  bot tests that exercise at least one passing and one failing prescreener path.
- Confirm failed participants exit before main trials and receive the intended
  status, failure tags, time credit, and recruiter branch.
- Inspect the participant flow in `psynet debug local` when the gate is
  participant-facing, especially for audio playback, hidden/visible desired
  answers, translated text, button states, and clear exit messaging.
- Validate any qualification JSON or platform config by loading it from the same
  path the experiment uses. Do not commit real platform credentials.
- Check exported data or module state so the prescreen outcome can be audited
  later without replaying the session.

## Common failures

- Do not add a generic headphone, language, color, or attention gate without
  tying it to a task requirement and participant-payment plan.
- Do not let prescreeners silently consume main-task quotas, grouped-trial slots,
  or expensive external resources before failure is known.
- Do not expose the target eligibility answer in the study title, recruitment ad,
  or first line of the screener when that would bias self-report.
- Do not treat self-report pages such as hearing history as objective pass/fail
  tests unless the experiment explicitly defines and justifies that policy.
- Do not copy old platform assumptions. Recruitment platforms change screen-out,
  payment, and qualification behavior; verify the current docs before launch.

---
name: simulate-participants
description: Design, implement, and validate simulated participants for PsyNet experiments.
---

# PsyNet simulated participants

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general experiment
  workflow and required simulation/export/report artifacts.
- Read `implement-experiment/references/validation.md` for command
  details, `run_bot` pitfalls, and performance-test expectations.
- Read `participant-quality-telemetry/SKILL.md` when profiles exercise
  attention, paste, disclosure, or AI-assistance review signals.
- Read `prepare-experiment-tunnel/SKILL.md` when a temporary public preview is
  needed for live manual or human review. Do not replace live review with
  simulated data.
- Read `verify-ai-model-usability/SKILL.md` before any real LLM-in-the-loop
  simulation.
- Read `participant-response-models/SKILL.md` when simulated answers represent a
  scientific hypothesis about participant behavior.

## Choose the simulation type

- PsyNet bots: framework-driven local participants run by `psynet test local` or
  `psynet audit simulate`; use them for default trial flow, export, and performance
  validation.
- Deterministic scripted profiles: fixed answers, timings, checks, and metadata;
  use them for reproducible edge cases and regression tests.
- Stochastic profiles: sampled answers, latencies, omissions, and error rates;
  use them to stress randomization, analysis scripts, and aggregate reports.
- Mock LLM-style profiles: local deterministic or stochastic text generators
  that imitate the shape of LLM responses without API calls; use them for prompt
  plumbing, parsing, and telemetry validation.
- Offline LLM-generated fixtures: previously generated text/audio/image outputs
  stored as non-secret fixtures; record their provenance and never describe them
  as human data.
- Live LLM-in-the-loop profiles: real model calls during local testing only.
  Require explicit user approval for APIs, paid calls, credentials, or networked
  model use.

## Design profile behavior

Define profiles before coding and record each profile id in participant vars,
trial data, or export-visible metadata.

- Good: follows instructions, passes checks, gives plausible response timing, and
  covers ordinary success paths.
- Inattentive: rushes, skips optional work, fails checks, or gives low-effort
  answers.
- Adversarial: enters malformed, boundary, contradictory, repeated, or
  instruction-breaking responses.
- AI-assisted: discloses AI use or shows paste/scripted behavior for telemetry
  validation; do not claim this proves real AI use.
- Edge-case: tests empty stimuli, maximum lengths, unusual locales, missing media,
  repeated trials, failed comprehension, or network/grouping boundaries.
- Profile-specific: models task-relevant differences such as expertise,
  condition assignment, language, strategy, sensory threshold, or payoff policy.

Avoid hard-coded simulations that merely manufacture expected results. Let
profiles interact with experiment code through the same answer formatting,
validation, trial saving, participant vars, and export paths used by real
participants whenever possible.

## Implement and connect data

1. For scientific profiles, import the top-level `response_model/` package from a
   thin adapter near the experiment code that defines the trial response format.
   Engineering profiles may remain local. For custom pages, follow
   `develop-experiment-front-end` so `get_bot_response` and `format_answer` stay
   aligned.
2. Pass profile id, group, seed or run id, and scenario labels through participant
   vars or trial data so exports can distinguish simulated groups.
3. Save profile-relevant telemetry beside the response it qualifies. Keep export
   schemas stable enough that analysis scripts do not need to infer profiles from
   answer values.
4. For stochastic profiles, seed runs when reproducibility matters and report the
   seed or run id.
5. For browser-only JavaScript, focus, paste, keyboard, audio, websocket, or
   display behavior, add a Playwright walk with `playwright-testing/SKILL.md`;
   PsyNet bots alone may bypass these paths. Use `record-participant-video/SKILL.md`
   when you also need a recording.

## LLM simulation rules

- Ask for explicit user approval before using model APIs, paid calls, external
  credentials, or live networked LLMs.
- Keep API keys in environment variables or local secret stores only. Never
  commit `.env`, keys, provider logs with secrets, or credential dumps.
- Log model name, prompt template/version, temperature, seed or run id when
  available, latency, failures, retries, parser outcome, and response provenance.
- Label outputs as model behavior or fixture behavior, not human participant
  behavior.
- Prefer mock LLM-style profiles or offline fixtures when API availability, cost,
  privacy, or reproducibility is not central to the test.

## Validate

- Run `psynet test local` with enough bots to cover each required group, profile,
  condition, prescreener branch, and check failure path.
- Run `psynet audit simulate` and inspect
  `audit/simulate/analysis/simulated_export/`. Verify trial answers, trial data,
  participant vars, profile metadata, telemetry fields, and analysis inputs are
  present and typed as expected.
- Run `psynet audit performance-test` when profile logic changes timing,
  grouping, concurrency, AI calls, or trial generation load.
- Compare at least one bot/profile run with a real browser participant path when
  browser-only code or participant-facing UI matters.
- Run analysis scripts against the exported simulated data and confirm they
  handle good, inattentive, adversarial, edge-case, and profile-specific groups.

## Report limitations

Reports should separate workflow validation from claims about real behavior.
State which profiles were simulated, which data paths were exercised, which
paths still need live human review, and why simulated results should not be
interpreted as human behavior or real LLM behavior. Do not use real Prolific,
Cint, AWS, production credentials, private participant data, or paid recruitment
for this workflow.

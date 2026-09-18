---
name: participant-quality-telemetry
description: Implement PsyNet-native participant quality and AI-assistance telemetry for text-heavy or response-quality-sensitive experiments.
---

# PsyNet participant quality telemetry

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general PsyNet
  implementation workflow, local setup, and validation expectations.
- Read `psychophysics/SKILL.md` as needed when timing, reaction time, or
  modality-specific prescreeners are central to the study.
- Read `turn-pure-experiment-to-ai-hybrid/SKILL.md` only when the experiment is
  intentionally mixing human and AI participants.
- Read `simulate-participants/SKILL.md` when simulated profiles are
  broader than telemetry QA or need export/analysis validation.

## Threat model

Separate these cases before designing telemetry:

- Inattentive participants: verified humans who skip instructions, rush, miss
  checks, give low-effort text, or multitask.
- AI-assisted verified humans: real participants who use AI tools despite,
  or in accordance with, study instructions.
- Browser agents: scripted or automated clients that act through the browser
  flow without being ordinary human users.
- Platform or account fraud: identity, account, payment, geolocation, or
  recruiter-level problems outside what a PsyNet study can prove by itself.

PsyNet telemetry can support manual review. It must not be described as proof
of AI use, bot use, platform fraud, or bad faith.

## Collectable in-study signals

Choose signals that match the task and explain them in participant-facing terms
when required by consent or study policy:

- Page and trial timing, response latency, time on instructions, and unusually
  fast or slow completion patterns.
- Attention, comprehension, practice, or consistency checks that are relevant to
  the task rather than trick questions.
- Browser focus, blur, visibility, and tab-switch events when feasible.
- Paste events and pasted character counts for fields where original writing is
  expected.
- Keydown counts, first-key latency, inter-key summaries, or edit counts where
  feasible; avoid recording raw keystrokes.
- AI-use instructions and disclosure questions, including whether AI tools are
  allowed, forbidden, or must be reported.
- Optional ECLAIR-style open-text probes that ask participants to explain their
  approach, sources, or reasoning without turning the study into a surveillance
  exercise.

## Storage and privacy

- Save trial-specific telemetry with the trial answer, trial data, or node/trial
  metadata so it exports beside the response it qualifies.
- Save participant-level rollups such as check failures, total focus losses,
  paste counts, disclosure answers, and review flags in participant vars or a
  documented export table.
- Store derived summaries before raw event streams when they answer the review
  question.
- Do not record unnecessary sensitive data: raw keystrokes, clipboard contents,
  hidden browser data, private account data, production recruiter identifiers,
  IP-derived claims, or full free-text telemetry beyond the study response.
- Keep telemetry schema stable and documented so exported data can be reviewed
  without reading browser code.

## Implementation workflow

1. State the review question the telemetry should help answer, and map each
   signal to that question.
2. Add participant-facing instructions or disclosure items for AI use and
   telemetry collection where needed.
3. Prefer PsyNet-native pages, controls, trial data, participant vars, and
   exports. Keep custom JavaScript small and isolated to browser-only events
   such as focus, paste, and keydown summaries.
4. Record enough event context to audit behavior: page or trial id, timestamp or
   relative time, event type, and aggregate counts. Avoid raw text capture.
5. Simulate multiple local participant profiles:
   - attentive human-like timing with original typed responses;
   - rushed or inattentive completion;
   - disclosed AI-assisted responses;
   - pasted or scripted browser-agent-like responses.
6. Write a transparent manual-review flagging script that consumes exported
   data, prints the rule thresholds, lists the evidence for each flag, and keeps
   final inclusion or rejection decisions for human reviewers.
7. Write a short report describing signals collected, simulated profiles,
   exported fields, flagging rules, false-positive risks, and what remains
   outside the study's evidence.

## Validation

- Run `psynet test local` for the experiment and include bots or fixtures that
  exercise the telemetry-saving path.
- Collect browser evidence for at least two contrasting profiles, for example a
  normal typed response and a pasted or AI-disclosed response.
- Export local data and verify that trial telemetry, participant rollups, and
  disclosure fields appear with the expected schema.
- Run the manual-review flagging script on the export and confirm the report
  shows both flagged and unflagged examples with explainable reasons.

## Rules

- Do not use real Prolific, CINT, Qualtrics, AWS, recruiter, payment, or
  production credentials unless the user separately requests a real deployment
  workflow.
- Do not load, commit, export, or publish private participant data while
  developing telemetry.
- Do not automatically reject participants, block payment, or make production
  fraud decisions from telemetry unless the user explicitly asks for a real
  deployment policy and review workflow.
- Do not duplicate the general PsyNet setup, experiment scaffolding, deployment,
  or participant-evidence procedures; point to the owner skills instead.

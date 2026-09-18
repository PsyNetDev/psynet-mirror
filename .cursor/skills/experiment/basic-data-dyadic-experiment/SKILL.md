---
name: basic-data-dyadic-experiment
description: Use this skill when a PsyNet experiment has two participants interacting across rounds and the user needs exported or simulated data converted into a clean analysis dataset.
---

# Process dyadic experiment data

The default clean layout is one row per experimental batch, dyad, round or node,
and player.

## Prerequisites

- Read `implement-experiment/SKILL.md` for simulation, exported data,
  analysis-script, and report expectations.
- For grouped, barrier-based, or live two-player experiments, read
  `synchronous-experiments/SKILL.md`.
- For websocket or continuous live interaction, read
  `realtime-synchronous-experiments/SKILL.md`; it owns the distinction
  between raw events, reconstructed state, and participant-specific deliveries.

## Workflow

1. Reconstruct stable identifiers:
   - experimental batch;
   - dyad or group ID;
   - network, node, trial, or session ID;
   - round number;
   - participant ID;
   - player index, role, or side within the dyad;
   - partner participant ID.
2. Define the round state before flattening data. List the variables that
   determine the state, such as shared resources, private resources, visible
   signals, hidden attributes, current turn, previous actions, timers, and
   cumulative outcomes.
3. Extract each participant's action for each round. Include action values and
   any analysis-relevant metadata such as submission time, acceptance time,
   timeout status, validity, revision count, duplicate submission status, or
   out-of-turn rejection.
4. Extract scores at the right level:
   - player-round score;
   - partner score;
   - dyad or group score;
   - cumulative score;
   - bonus-relevant score;
   - score components when they are needed to audit the rule.
5. Build the canonical player-round table with one row per batch, dyad, round,
   and participant. Prefer explicit columns for commonly analyzed state and
   action variables. Keep nested `state_json`, `action_json`, or raw event IDs
   only when they remain useful for auditing.
6. Ask the user for feedback, presenting them a small example dataset for review.

## Validation checklist

- Each complete dyad-round has exactly two player rows.
- Each participant has at most one clean row per dyad-round-player role.
- Player order is stable across rounds, or role changes are explicitly recorded.
- Partner fields are symmetric and point to the other participant in the dyad.
- Round state can be reconstructed deterministically from the recorded sources.
- Clean action and score values match the authoritative raw events or trial
  answers.
- Timeouts, invalid actions, dropouts, skipped rounds, failed trials, and
  one-sided responses are represented according to a documented missingness
  policy.
- The clean table preserves enough IDs to trace any row back to the source
  event, trial, node, or export row.

## Common failures

- Do not silently treat browser-local state as authoritative when server events
  or accepted trial answers exist.
- Do not collapse dyad-round data to one row per round when the requested
  analysis needs one row per player.
- Do not hide role assignment or player ordering inside column names that cannot
  be compared across rounds.
- Do not discard raw event IDs, trial IDs, or node IDs before the clean dataset
  has passed audit checks.
- Do not finalize the schema before showing the user a partial reconstruction
  and asking whether irrelevant information should be removed or missing
  variables should be added.

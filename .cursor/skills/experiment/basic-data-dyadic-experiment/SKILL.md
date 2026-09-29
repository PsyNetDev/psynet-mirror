---
name: basic-data-dyadic-experiment
description: Use this skill when a PsyNet experiment has two participants interacting across rounds and the user needs exported or simulated data converted into a clean analysis dataset.
---

# Process dyadic experiment data

## Read first

Read these pages before acting. Get the docs folder once with `psynet docs path`, then read `<folder>/<page>.txt` (or `.rst` in a source checkout) and search with `rg -n -i "<term>" <folder>`. If there is no local copy, fetch the pages from the website URL that `psynet docs path` prints.

- `data/basic_data` — `get_basic_data`; its "Group experiments" section covers the group tables, rounds, the player-round layout and a worked example
- `data/analyzing_data` — joining group tables in an export
- `data/what_an_export_contains` — raw export tables and identifier separation
- `code/multiplayer/synchronization` — groups, barriers, regrouping and dropouts

## Prerequisites

- Read `implement-experiment/SKILL.md` for simulation, exported data,
  analysis-script, and report expectations.
- For grouped, barrier-based, or live two-player experiments, read
  `synchronous-experiments/SKILL.md`.
- For websocket or continuous live interaction, read
  `realtime-synchronous-experiments/SKILL.md`; it owns the distinction
  between raw events, reconstructed state, and participant-specific deliveries.

## Workflow

1. Locate each identifier the analysis needs (batch, group, round, participant,
   role or player index, partner) using "Group experiments" in
   `data/basic_data`. If a per-round value exists only in participant
   variables or browser state, change the experiment to save it on the trial
   before any data are collected.
2. Define the round state before flattening. List the variables that
   determine it, such as shared and private resources, visible signals,
   hidden attributes, current turn, previous actions, timers, and cumulative
   outcomes.
3. Extract each participant's action per round, with any analysis-relevant
   metadata: submission time, timeout status, validity, revision count,
   duplicate submissions, or out-of-turn rejections.
4. Extract scores at each level the analysis uses: player-round, partner,
   group, cumulative, and bonus-relevant scores, plus score components when
   they are needed to audit the scoring rule.
5. Build the player-round table in `get_basic_data`, starting from the
   worked example in `data/basic_data`. Give roles and player order their own
   columns. Keep nested JSON or raw event IDs only where they help auditing.
6. Run the experiment with bots or simulated participants
   (`simulate-participants/SKILL.md`), export it, and check the table against
   the validation checklist below. Compare the clean actions and scores with
   the values the simulated participants were given.
7. Show the user a small extract of the table and ask whether columns should
   be added or removed before finalizing the schema.

## Validation checklist

- Each complete group-round has one row per member (two for a dyad).
- Each participant has at most one row per group and round.
- Player order is stable across rounds, or role changes are recorded.
- Partner fields are symmetric.
- Round state can be reconstructed deterministically from the recorded
  sources.
- Clean actions and scores match the trial answers or authoritative server
  events, and match the simulated participants' inputs.
- Timeouts, invalid actions, dropouts, skipped rounds, failed trials, and
  one-sided responses follow a documented missingness policy.
- Every row keeps enough IDs to trace it back to its trial, node, or event.

## Common failures

- Treating browser-local state as authoritative when server events or
  accepted trial answers exist.
- Collapsing to one row per round when the analysis needs one row per player.
- Encoding role or player order only in column names that cannot be compared
  across rounds.
- Discarding trial, node, or event IDs before the clean table has passed the
  checks above.

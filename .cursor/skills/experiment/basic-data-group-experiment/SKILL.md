---
name: basic-data-group-experiment
description: Use this skill when a PsyNet experiment has two or more participants interacting across rounds and the user needs exported or simulated data converted into a clean analysis dataset.
---

# Process group experiment data

## Read first

Read these pages before acting. The "Documentation" section of the experiment's `AGENTS.md` explains how to find and search them.

- `data/basic_data` — `get_basic_data`; its "Group experiments" section covers the group tables, rounds, the player-round layout and worked examples
- `data/analyzing_data` — joining group tables in an export
- `data/what_an_export_contains` — raw export tables and identifier separation
- `code/multiplayer/synchronization` — groups, barriers, regrouping and dropouts
- `code/multiplayer/writing_a_round_based_experiment` — rounds as cued trials

## Prerequisites

- Read `implement-experiment/SKILL.md` for simulation, exported data,
  analysis-script, and report expectations.
- For grouped, barrier-based, or live multiplayer experiments, read
  `synchronous-experiments/SKILL.md`.
- For websocket or continuous live interaction, read
  `realtime-synchronous-experiments/SKILL.md`; it owns the distinction
  between raw events, reconstructed state, and participant-specific deliveries.

## Where each round is recorded

Play each round as one trial per player, so that PsyNet records the group
and round on the trial; a game written as pages without trials should
become one cued trial per player per round. Use these columns rather than
matching timestamps across tables.

- Trials of a trial maker with `sync_group_type`, and cued trials whose
  class sets `sync_group_type` (`Trial.cue(...)`), have
  `sync_group_id`, `sync_group_role` and `sync_group_round`. A group's
  trials with the same `sync_group_id` and `sync_group_round` are one round,
  including a latecomer's. Don't match rounds by `position`, which counts
  each participant's own trials.
- Save each player's results on their trial (`trial.var`), including
  outcomes the server computes, such as a move played for a player who ran
  out of time. A `GroupBarrier`'s `on_release` receives the members'
  `trials` for this. Pay bonuses through the trial's `score_answer` and
  `compute_performance_reward`, so that `trial.performance_reward` matches
  the payment.
- Cued trials of one group and round share a `SyncGroupNode`
  (`on_release` receives it as `node`): save the group's results once, in
  `node.var`, and export one row per group per round from
  `SyncGroupNode.query.filter_by(module_id=...)`.

Start from `get_basic_data` in the `lowest_unique_number` demo for cued
trials, in the `ultimatum_pairing` demo for pairs that change every round
(see "Games with a regrouper" in `data/basic_data`), or in the
`rock_paper_scissors` demo for a trial maker. If a per-round value exists
only in participant variables or browser state, change the experiment to
save it on the trial or node before any data are collected.

## Workflow

1. Find where the experiment records its rounds, as above, and the
   identifiers the analysis needs: batch, group, round, participant, role
   or player order, and partner.
2. Define the round state before flattening. List the variables that
   determine it, such as shared and private resources, visible signals,
   hidden attributes, current turn, previous actions, timers, and cumulative
   outcomes.
3. Extract each participant's action per round, with any analysis-relevant
   metadata: timeout status (a timed-out page saves `None`), validity,
   submission time, revision count, duplicate submissions, or out-of-turn
   rejections.
4. Extract scores at each level the analysis uses: player-round, partner,
   group, cumulative, and bonus-relevant scores, plus score components when
   they are needed to audit the scoring rule.
5. Build the player-round table in `get_basic_data` from the trials, and a
   group-round table from the `SyncGroupNode` rows if the game has group
   results. Give roles and player order their own columns. Keep nested JSON
   or raw event IDs only where they help auditing.
6. Run the experiment with bots or simulated participants
   (`simulate-participants/SKILL.md`), export it, and check the table against
   the validation checklist below. Compare the clean actions and scores with
   the values the simulated participants were given.
7. Show the user a small extract of the table and ask whether columns should
   be added or removed before finalizing the schema.

## Validation checklist

- Each complete group-round has one row per member, and each participant
  has at most one row per group and round.
- Each participant's bonuses in the table add up to their performance
  reward; assert that sum in the bot test.
- Player order is stable across rounds, or role changes are recorded.
- Partner fields are symmetric.
- Round state can be reconstructed deterministically from the recorded
  sources.
- Clean actions and scores match the trial answers, saved results or
  authoritative server events, and match the simulated participants' inputs.
- Timeouts, invalid actions, dropouts, sit-outs, failed trials, and
  one-sided responses follow a documented missingness policy.
- Every row keeps enough IDs to trace it back to its trial, node or event.

## Common failures

- Rebuilding rounds from response timestamps or current group membership
  when `trial.sync_group_id` and `trial.sync_group_round` exist.
- Keeping per-round results only in `participant.var`, which holds just the
  latest value.
- Treating browser-local state as authoritative when server events or
  accepted trial answers exist.
- Collapsing to one row per round when the analysis needs one row per player.
- Encoding role or player order only in column names that cannot be compared
  across rounds.
- Discarding trial, node, or event IDs before the clean table has passed the
  checks above.

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

Follow "Group experiments" in `data/basic_data`: play each round as one
trial per player, save each player's results on their trial and the
group's on its `SyncGroupNode`, and build the tables from those, not from
timestamps or `position`. For example:

```python
@classmethod
def score_round(cls, trials, node):  # GroupBarrier(..., on_release=cls.score_round)
    # Each player's choice is their trial's answer, None after a timeout.
    total = sum(t.answer or 0 for t in trials)
    node.var.total = total
    for trial in trials:
        trial.var.payoff = total / len(trials) - (trial.answer or 0)

# In the Experiment class:
@classmethod
def get_basic_data(cls, context=None, **kwargs):
    """Return one row per trial, including rounds that were never scored."""
    return {"player_round": [
        {
            "group_id": t.sync_group_id,
            "round": t.sync_group_round,
            "participant_id": t.participant_id,
            "trial_id": t.id,
            "choice": t.answer,
            "payoff": t.var.get("payoff"),
            "group_total": t.node.var.get("total"),
        }
        for t in MyTrial.query.all()
    ]}
```

Start from the `get_basic_data` of the demo closest to the design:

- `rock_paper_scissors`: a fixed pair playing cued trials.
- `public_goods`: a fixed group of three playing several rounds, with the
  group's results on its `SyncGroupNode` and a group-round table from the
  nodes.
- `ultimatum_pairing`: pairs that change every round, with a table per
  pair from the nodes (see "Games with a regrouper" in `data/basic_data`).
- Groups that each play one round, formed by a `Regrouper` without
  `within`: number each player's own trials as their `round`
  (`trial.position`); where a group plays several rounds, use
  `sync_group_round` instead.

If a per-round value exists only in participant variables or browser
state, change the experiment to save it on the trial or node before any
data are collected.

## Workflow

1. Find where the experiment records its rounds, as above, and the
   identifiers the analysis needs: batch, group, round, participant, role
   or player order, and partner.
2. Define the round state before flattening. List the variables that
   determine it, such as shared and private resources, visible signals,
   hidden attributes, current turn, previous actions, timers, and cumulative
   outcomes.
3. Extract each participant's action per round, with any analysis-relevant
   metadata: timeout status (read `trial.time_limit_reached` rather than
   inferring it from a `None` answer), validity, submission
   time, revision count, duplicate submissions, or out-of-turn rejections.
4. Extract scores at each level the analysis uses: player-round, partner,
   group, cumulative, and bonus-relevant scores, plus score components when
   they are needed to audit the scoring rule.
5. Build the player-round table in `get_basic_data` from the trials, one
   row for every trial, including rounds that were never scored or that
   the player left, with `None` in the columns they didn't reach; say so in
   the docstring. Add a group-round table from the `SyncGroupNode` rows if
   the game has group results. Give roles and player order their own
   columns. Keep nested JSON
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

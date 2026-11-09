---
name: synchronous-experiments
description: Design and implement PsyNet synchronous experiments using cohort, grouping, barrier, waiting-room, and recruiter coordination patterns without assuming websocket interaction.
---

# Implement synchronous PsyNet experiments

If participants exchange live actions or messages within a trial, also read
`realtime-synchronous-experiments/SKILL.md`.

## Read first

Read these pages before acting. The "Documentation" section of the experiment's `AGENTS.md` explains how to find and search them.

- `design/groups` — group design concepts
- `code/multiplayer/synchronization` — grouping, barriers, waiting, and release callbacks
- `reference/api/sync` — synchronization API

## Prerequisites

- Read `implement-experiment/SKILL.md` for the general PsyNet
  implementation workflow and validation expectations.
- Read `references/source-notes.md` for the source map, platform notes, and
  practical caveats behind this skill.
- Read these demos before coding, found as described in
  `explore-psynet-repository/SKILL.md` ("Finding demo code"):
  `demos/experiments/simple_sync_group`,
  `demos/experiments/create_rate_sync`,
  `demos/experiments/rock_paper_scissors`,
  `demos/experiments/sync_quorum`, and
  `demos/experiments/gibbs_within_sync`; for games played in rounds, also
  `demos/experiments/ultimatum_pairing` and
  `demos/experiments/lowest_unique_number`.

## Choose the synchronization model

1. Classify the design before coding:
   - cohort/quorum: participants must enter a phase together;
   - grouped trials: group members should receive the same node or trial order;
   - phase barriers: participants work independently, then wait for partners;
   - live interaction: use the realtime websocket skill as well.
2. Prefer PsyNet server-side grouping and barriers over browser-side polling or
   custom JavaScript for shared state.
3. Decide what happens to late arrivals, no-shows, dropouts, and overflow
   participants before implementing the happy path.
4. Size the study in whole groups. Align `target_n_participants`,
   `initial_recruitment_size`, platform slots, and any over-recruitment buffer.
5. Make waiting fair: explain the expected wait, cap waits with
   `max_wait_time`, and provide filler tasks or a paid exit when waits can be
   long.

## PsyNet implementation hints

- Make every round a trial, so its data stay on trials and nodes. Use a
  trial maker with `sync_group_type` when all group members should follow
  the leader's node allocation and trial sequence, and one cued trial per
  player per round (below) for games played in rounds, especially with
  changing partners. For choosing
  `StaticTrialMaker` vs chain-based makers, read
  `develop-experiment-back-end/SKILL.md`.
- Use `SimpleGrouper(group_type=..., initial_group_size=...)` to create cohorts
  and `GroupBarrier(id_=..., group_type=..., waiting_message=...)` to release
  group members together. Pass `waiting_message` to customize the hold
  overlay; omit `waiting_logic` unless you need a full wait page or filler
  task. Arrival notices are on by default. The partner-ready pill sits on
  the progress bar. Pair holds keep the title only; groups of three or more
  show remaining-not-ready copy (`2 of 3 not ready yet`). For notice length,
  see "Arrival notices" in `code/multiplayer/synchronization`. Groupers form
  groups when the last needed member arrives, without waiting for the
  barrier poller.
- Use `GroupBarrier(on_release=...)` for atomic shared updates such as role
  assignment, scoring, aggregation, or recording round outcomes. The
  callback's `barrier` argument is the reconstructed registry object; read
  `waiting_message` and timeouts from it. Wait pages stay on the live timeline
  barrier (see "Release callbacks" in `code/multiplayer/synchronization`).
  To share one callback between barriers, give each its own keyword
  arguments with `functools.partial` instead of parsing `barrier.id`
  (see "Release callbacks"). `on_release` doesn't run
  for members who left before the release or whose group dissolved, so read
  what it stores with `trial.var.get("score")` (or `participant.var.get`),
  which returns `None` when it isn't set. Pass the same function as `on_dissolve` too when members
  waiting at the barrier as the group dissolves should still get their
  result; it is called once, with all of them, because dissolving waits until
  no member's request is in flight. Members still on an earlier page get
  neither callback, so
  check their cued trial's `sync_group_outcome == "group_dissolved"` in a
  step after the barrier if they need a result too.
- Sort `sync_group.participants` by participant ID before deterministic role
  assignment; PsyNet does not guarantee the stored order.
- Put additional `GroupBarrier`s inside `Trial.show_trial` for phase boundaries
  such as submit, rate, reveal, score, or bonus computation.
- Read partner state through `participant.sync_group.participants`,
  participant vars, trial vars, node vars, or `on_release` outputs. Do not let
  the browser decide shared experiment state.
- For games played in rounds with changing partners or rooms, put a
  `Regrouper(group_type, group_size=..., within=...)` at the start of each
  round instead of a grouper and closer. Pass `deadline=` to split once
  everyone is back or the timeout passes (`ultimatum_pairing`), or `every=`
  for rounds on fixed ticks (`lowest_unique_number`). Participants who miss
  a split join the next one rather than being failed. For players who stop
  responding mid-round, follow "Moving slow players on" in
  `code/multiplayer/writing_a_round_based_experiment`: use
  `late_action="leave_all_groups"` so that they also leave the `within`
  group; see the quorum caveat there.
- A member on a timed page isn't treated as late until its limit plus 10 s,
  so `late_after` need not cover the page (see "Timeouts" in
  `code/multiplayer/synchronization`); the demos use 30 s so that a
  background tab can notice the round has started.
- The regrouper avoids last round's partners (`avoid_repeats="all_rounds"`
  avoids everyone met before), sits out whoever has played most, and counts
  rounds (`rounds_played`, `rounds_sat_out`); pass `roles=[...]` (with
  `keep_roles=True` for fixed roles) and read `regrouper.role(participant)`
  instead of assigning roles yourself. With `left_over="sit_out"`, odd
  players out sit out the round; with `within`, a player waiting alone first
  waits one more period for cohort members. The default `max_wait_time`
  allows for this; an explicit one must then exceed twice the `deadline` or
  `every` period.
- For a lobby that should not wait forever for a full group, use
  `SimpleGrouper(start_short_after=..., quorum=...)`; a short start forms a
  group of at least the quorum (`start_short_with` overrides that). To let
  latecomers join only before the game starts, follow "Letting latecomers
  join before the game starts" in `code/multiplayer/synchronization`.
  If groups keep taking newcomers after that, pass `pass_newcomers=True` to
  each `GroupBarrier` the group passes once, so a newcomer doesn't wait there
  for members further on (see "Letting latecomers join during the game").
  Never set it on a barrier in a loop or in `show_trial`.
  For a per-person condition (not a join window), such as a chain that is
  too far along for them to catch up with, pass `join_criterion` (see
  `join_criterion` under "Forming groups" in
  `code/multiplayer/synchronization`).
  To let participants who find no group carry on alone instead of being
  failed, pass the grouper `max_wait_action="continue_without_group"`.
- Branch on `participant.in_sync_group(group_type)` wherever the timeline
  needs a group: stop a rounds loop with it in the `while_loop` condition,
  and give a synchronized trial maker a solo alternative, for example
  `conditional("paired", in_pair, paired_trials, solo_trials)`.
- Give the steps of a round to `join(..., stop_if=left_pair)`, with
  `left_pair` returning `not participant.in_sync_group("pair")`, so a
  participant who loses their group partway skips the rest, instead of a
  `conditional` per page. `join` checks `stop_if` before each argument and
  never cuts a started argument short, so a barrier or cued trial runs whole.
  To end the rounds, pass the same `stop_if` to the `for_loop`. Put the
  grouper or `Regrouper` before the `join`, not among its arguments, or
  everyone not yet grouped skips it. A round that is one cued trial needs
  only a `conditional` (see "Rounds as cued trials").
- Follow with a `conditional` on the same function for what a member who
  left, or anyone who never had a group, does instead, such as answering the
  rest of the question alone. With a `Regrouper` in the loop, it is also the
  page for a player it sat out that round:
  `join(Regrouper(...), join(decision_page, barrier, outcome_page, stop_if=left_pair), conditional("sat_out", left_pair, sitting_out))`.
  Check `regrouper.sat_out(participant)` there to tell a sit-out from a
  player removed for being late.
- In a `Regrouper` game the player whose partner left stays in the pair, so
  they play the round out and see its outcome, as in `ultimatum_pairing`;
  only the player removed for being late is out of the pair, and gets their
  own page there. The barrier's `on_release` can take `left`, the members
  who left since the previous barrier, and
  `p.sync_group_removal_reason("pair")` tells the one who stayed whether
  their partner returned the study or was too slow.
- For lobbies/quorums, combine `SimpleGrouper(..., waiting_logic=...)` with
  filler work via `trial_maker.custom(...)`, as in `sync_quorum`.
- For chain or Gibbs designs, distinguish true co-presence from async
  across-participant chains. Use `wait_for_networks=True` when participants may
  otherwise exit while async network growth is still pending.
- Use `ChatRoom` only for participant communication; keep phase advancement
  and scoring in barriers. Inside a trial, scope the room with
  `self.sync_group.id`. Elsewhere use
  `participant.active_sync_groups.get(group_type)`, which is `None` after
  the participant left the group, so show no `ChatRoom` then.
  `participant.sync_group` raises if more than one group is active.
- A `PageMaker` builds its page again on submit, when the participant may
  have left the group. Never index `active_sync_groups[group_type]` there:
  it raises `KeyError`, which fails the participant.
- For games with turns one after the other, such as investor then trustee,
  follow "Turns one after the other" in
  `code/multiplayer/writing_a_round_based_experiment`.
- Prefer engaging waiting trials over passive wait screens when waits may be
  long. Participants may be distracted or running multiple experiments at once;
  useful filler tasks can improve retention and reduce idle no-shows.
- Add participant-facing alerts for important transitions, such as an audible
  cue when a group is matched or when the participant is expected to act. Make
  sure alerts are compatible with browser autoplay rules and the study's audio
  consent/device requirements.
- Use visible timers, warning states, automatic staging/submission, and clear
  timeout behavior for timed phases. These patterns keep groups responsive and
  prevent one inactive participant from blocking everyone else indefinitely.

### Rounds as cued trials

Follow "One trial per player per round" in
`code/multiplayer/writing_a_round_based_experiment`:

```python
class PickTrial(Trial):
    sync_group_type = "room"  # a room's trials in one round share a node
    time_estimate = 15

    def show_trial(self, experiment, participant):
        return join(
            self.choose_number(participant),
            GroupBarrier(id_="round_finished", group_type="room",
                         on_release=self.score_room),
        )

    @classmethod
    def score_room(cls, trials, node):
        # trial.answer holds each player's answer so far (None: timed out).
        # String keys, since node.var is stored as JSON.
        node.var.choices = {str(t.participant_id): t.answer for t in trials}

# The Module gives the nodes a module_id to find them by when exporting.
Module("game", for_loop(
    label="rounds", iterate_over=range(N_ROUNDS), time_estimate_per_iteration=20,
    logic=join(
        Regrouper("room", ...),
        # Players the regrouper left out see a page instead of a trial.
        conditional("in_room", lambda participant: participant.in_sync_group("room"),
                    PickTrial.cue({"numbers": NUMBERS}),
                    InfoPage("You skip this round.", time_estimate=5)),
    ),
))
```

- Keep a `GroupBarrier` in every round, inside `show_trial` after the
  answer page, so members stay in step. A cued round closes only when its
  barrier releases the group; a round without one never closes, and a
  latecomer can join it after the others have finished. For how
  `cue` numbers rounds and the definition rules, follow the guide above.
- When a fixed group plays a loop of rounds, pass the loop value as
  `round=` (`Trial.cue({"question": i}, round=i)`): late joiners then skip
  the rounds the group finished without them, and players who leave
  continue alone. A skipped cue leaves `participant.current_trial` as
  `None`, so guard later steps of the iteration that read it with a
  `conditional` on `participant.current_trial is not None`. Don't pass
  `round=` with a regrouper, and give each run of such a module its own
  module id.
- `on_release` reads each member's answer so far from `trial.answer`
  (`accumulate_answers = True` for several answer pages, which makes it a
  dict from the start), and `score_answer`, `show_feedback` and
  `get_basic_data` read the trial and `self.node.var`. `node.all_trials`
  keeps the trials of players who left during the round. Exports need no
  round counter of their own: `sync_group_round` counts the group's rounds,
  for what the group shares, and `position` counts the player's own
  trials in the module, grouped or not.
- Put `leave_group(group_type)` after a player's last round so that the
  rest of the group, and any `Regrouper`, stops waiting for them.
- Use `self.sync_group_role` for role-specific pages, and put the cue in a
  `conditional` on `participant.in_sync_group(...)`, with a page as the
  other branch, so a player the regrouper sat out gets a page instead of a
  trial. A started trial runs to its end even if the player leaves the
  group, so its `show_feedback` explains every outcome, including being
  removed for lateness. Read how the round ended for each player from
  `trial.sync_group_outcome` (`"stayed"`, or why they left, such as
  `"late"`), a partner's from their trial in `self.node.all_trials`, rather
  than from current group membership. A barrier's `waiting_screen` can take
  `trial` and `node` to show the round's state.

## Recruitment and platform design

- Treat Prolific, Connect, Cint, or Lucid as recruitment layers. PsyNet
  should still own the lobby, grouping, timeout, overflow, and completion logic.
- Prefer Prolific or CloudResearch Connect for small scheduled cohorts because
  they support participant IDs, targeted recontact, messages, quotas, and manual
  review workflows.
- Put session time, time zone, expected waiting window, device/audio
  requirements, no-show policy, and partial-payment policy in the study
  description and participant instructions

## Validation

- Run `psynet test local` with at least as many bots as the group size, plus
  extra bots for late-arrival or top-up paths.
- Use serial bot tests with `advance_past_wait_pages(bots)` for deterministic
  barrier progression. It polls for up to 10 s; pass a longer `timeout=` when
  rounds start on a clock or a deadline. Use concurrent bot runs when arrival
  races matter.
- Assert group formation, active group size, role assignment, shared node/trial
  IDs, barrier IDs, `on_release` side effects, and failed/overflow exits.
- Test each kind of dropout, as described in "Test dropouts" below, and
  top-ups, not only a complete group that finishes.
- Test waiting-phase retention aids: filler trials should save usable data or
  stay harmless, alerts should fire at the intended transition, timers should be
  visible, and automatic submissions should record a valid response or failure
  reason.
- For participant-facing waiting rooms or multi-browser behavior, collect
  separate browser-context evidence. Use `record-participant-video/SKILL.md` for
  participant-flow recordings.
- Inspect exported data to confirm group IDs, platform IDs, roles, phase
  timestamps, responses, failures, and partial-completion reasons are analyzable.

## Test dropouts

Real groups lose members in several ways; "Waiting and dropouts" in
`design/groups` lists them, and "Settings for each kind of dropout" in
`code/multiplayer/synchronization` gives the setting for each.
Write a serial bot test for every kind your design can meet, and check that
the experiment behaves sensibly for everyone involved: members who did
nothing wrong are not failed unless the design says so, their next page tells
them what happened, nobody waits for a partner who has gone, and nobody is
shown a page that only makes sense with a group.

| Dropout | Simulate it in the bot test |
|---|---|
| Returns the study | `bot.drop_out()` |
| Is failed by the experiment | `bot.allow_failure()`, then `bot.fail("reason")` |
| Runs out of time on a timed page | `bot.run_out_of_time()` |
| Closes the tab or stops responding | Stop taking pages for that bot and keep advancing the others |
| Comes back after being removed | Take pages for the silent bot again |
| Arrives when no group can form | Send one bot more than fills the groups to the grouper, and wait out its `max_wait_time` |

Read `references/test-dropouts.md` for a worked pair test with a quitter and a
silent member, and for how long to wait out timeouts in bot tests.

- Check why a bot left with
  `bot.with_participant(lambda p: p.sync_group_removal_reason("pair"))`, and
  read Regrouper roles with `bot.with_participant(pairing.role)`.
- Post chat messages with `bot.send_chat_message("...")`.
- Find who plays with whom with `bots_by_sync_group(bots, "pair")`, and
  finish bots that still wait for each other with
  `run_bots_to_completion(bots)`. For several groups in one test, and for
  `Regrouper` partners, follow "Bots that drop out" in `test/backend`.
- A member removed for being late sees "went on without you" only on the page
  they were on; assert `current_notice` before that bot takes the page. "After
  leaving a group" in `code/multiplayer/synchronization` gives the wording,
  which depends on how many members were left.
- Pytest doesn't show the compared values of a failed `assert` in
  `experiment.py`, so add a message: `assert text == "Round 2.", text`.

## Common failures

- Close a group with `GroupCloser` before a later grouper of the same
  `group_type` forms new groups. It is a `GroupBarrier`, so members wait there
  for each other; one isn't needed at the end of the timeline, because a group
  whose members have all finished closes by itself.
- Do not leave default wait limits in place for real recruitment sessions
  without checking whether they are appropriate.
- Do not assume top-ups are safe; define exactly which groups may accept late
  participants.
- Do not set recruitment targets that leave stranded participants unable to form
  a full group.
- Do not auto-reject participants who waited or were stranded by no-shows; plan
  a platform-compliant return, partial payment, or manual review path.

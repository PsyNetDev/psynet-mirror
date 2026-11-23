# README

A wisdom-of-crowds estimation game in an open lobby. Players wait for a group
of four, or start with three once the first of them has waited long enough,
and latecomers can join a group until its game starts. For each of two
questions, members estimate, see everyone's estimate and the group's median
in a `GroupPrompt`, and give a revised estimate, each within a time limit.
The median needs three estimates in time. A member who stops
responding is failed so the others don't wait for them, and the others carry
on while at least three remain.

Good reference for a `SimpleGrouper` with `start_short_after`, top-ups
(`join_existing_groups=True`) that stop when the game starts
(`GroupBarrier(stop_top_ups=True)`), `top_up_wait` for a group waiting for a
replacement, and barriers that fail late players (`late_action="fail"`).
Each question is one cued trial per player
(`Trial.cue(..., round=question)` on a trial class with `sync_group_type`):
the barrier that scores the question saves the group's estimates and median
on the round its members' trials share (`trial.group_round.var`), and on each trial whether its
estimate is in the median. A code block right after the estimate page stores
whether it timed out in `trial.var.estimate_timed_out`, from
`participant.last_response`, because `trial.time_limit_reached` later follows
the revision page. With `accumulate_answers = True`, the trial's answer holds
both the estimate and the revised estimate, by page label.
`get_basic_data` exports a row for every trial, including trials whose
player left before answering, and one per group and question from the
rounds.

## Dropouts and time-outs

- A median of two estimates is just their mean, so a group needs three
  members (its quorum).
- Latecomers can join only until the game starts, so that everyone in a
  group answers every question together. After that, a latecomer waits in
  the lobby for a new group.
- A participant for whom no group forms within `LOBBY_WAIT` seconds is
  failed (the grouper's default `max_wait_action="fail"`).
- A group that falls below three before the game starts waits up to
  `TOP_UP_WAIT` seconds, once its remaining members reach the start of the
  game, for a latecomer to replace the member who left.
- Each estimate has a time limit of `ANSWER_SECONDS`; a player who runs
  out of time gives none.
- A member who stops responding is failed as late, so nobody waits for them:
  at the start of the game `LATE_AFTER` seconds after they joined the group,
  and during a question `LATE_AFTER` seconds after the group's previous
  barrier, but not before their current page's time limit plus 10 seconds
  (see "Timeouts" in `docs/code/multiplayer/synchronization.rst`). The
  others carry on while at least three remain.
- A group that falls below three, once the game has started or when nobody
  replaces a member who left before it, ends, and its remaining members are
  failed (`below_quorum="fail"`): a group median needs three estimates, and
  nobody answers alone. Failing isn't a penalty here: it ends the session
  promptly, and participants are paid for what they completed.
- When fewer than three estimates arrive because players ran out of time,
  the group's estimates are saved without a median and there is nothing to
  revise.
- A player the experimenter removes from their group on the dashboard
  during a question can't revise their estimate, is told they were removed,
  and answers no more questions. One removed before the first question goes
  straight to the end of the experiment.

The timeouts are short so that the bot test runs quickly. A real deployment
would start short after about a minute, wait about three minutes in the
lobby, allow about 30 seconds for `ANSWER_SECONDS` and about a minute for
each of `TOP_UP_WAIT` and `LATE_AFTER`, which also covers reading the
introduction.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

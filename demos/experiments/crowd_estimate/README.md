# README

A wisdom-of-crowds estimation game in an open lobby. Players wait for a group
of four, or start with three once the first of them has waited long enough,
and latecomers can join a group until its game starts. For each of two
questions, members estimate, see everyone's estimate and the group's median
in a `GroupPrompt`, and give a revised estimate, each within a time limit.
The median needs three estimates in time. A member who stops
responding is removed so the others don't wait for them, and anyone left
without a group answers the questions alone instead of being failed.

Good reference for a `SimpleGrouper` with `start_short_after`, top-ups
(`join_existing_groups=True`) that stop when the game starts
(`GroupBarrier(stop_top_ups=True)`), `top_up_wait` for a group waiting for a
replacement, and `join(..., stop_if=...)` with a `conditional` for participants
without a group. Each question is one cued trial per player
(`Trial.cue(..., round=question)` on a trial class with `sync_group_type`):
the barrier that scores the question saves the group's estimates and median
on the node its members' trials share, and on each trial whether its
estimate is in the median. A code block right after the estimate page stores
whether it timed out in `trial.var.estimate_timed_out`, from
`participant.last_response`, because `trial.time_limit_reached` later follows
the revision page. Nothing runs when a group ends, so a
round whose group ended at that barrier keeps only each player's estimate,
in their trial's answer. With `accumulate_answers = True`, that answer holds
both the estimate and the revised estimate, by page label. A player without a
group gets an ungrouped trial that asks only for their estimate.
`get_basic_data` exports a row for every trial, including answers given alone
and trials whose player left before answering, and one per group and question
from the nodes.

## Dropouts and time-outs

- A median of two estimates is just their mean, so a group needs three
  members (its quorum).
- Latecomers can join only until the game starts, so that everyone in a
  group answers every question together. After that, a latecomer waits in
  the lobby for a new group.
- A group that falls below three before the game starts waits up to
  `TOP_UP_WAIT` seconds for a latecomer to replace the member who left.
- Each estimate has a time limit of `ANSWER_SECONDS`; a player who runs
  out of time gives none.
- A member who stops responding is removed as late, so nobody waits for them:
  at the start of the game `LATE_AFTER` seconds after they joined the group,
  and during a question `LATE_AFTER` seconds after the group's previous
  barrier, but not before their current page's time limit plus 10 seconds
  (see "Timeouts" in `docs/code/multiplayer/synchronization.rst`).
- A group that falls below three once the game has started ends.
- When fewer than three estimates arrive because players ran out of time,
  the group's estimates are saved without a median and there is nothing to
  revise. If the group ends while its members wait for the median, the round
  has no group estimates or median, and there is nothing to revise either.
- Nobody is failed for what another player did, or for waiting: anyone
  without a group, because none formed within `LOBBY_WAIT` seconds, their
  group ended, or they were removed, answers the remaining questions alone.

The timeouts are short so that the bot test runs quickly. A real deployment
would start short after about a minute, wait about three minutes in the
lobby, allow about 30 seconds for `ANSWER_SECONDS` and about a minute for
each of `TOP_UP_WAIT` and `LATE_AFTER`, which also covers reading the
introduction.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

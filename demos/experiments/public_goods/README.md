# README

A repeated public goods game in groups of three. Each round, every member
privately puts some of their tokens in a group pot, within a time limit; the
pot is multiplied and shared between the members who played the round, and
everyone sees the group's contributions and what they earned, paid as a
bonus.

Good reference for a `SimpleGrouper` with a `quorum` whose members carry on
without the group, a scoring `GroupBarrier` with `late_after`, `on_release`
and a `waiting_screen`, and `for_loop(..., stop_if=...)` with a
`conditional` afterwards for players without a group. Each round is one cued
trial per player (`Trial.cue(round=i)` on a trial class with
`sync_group_type`): the group's pot is saved once on the node its members'
trials share, and each player's contribution and payoff on their trial,
which pays the bonus. The basic data is read from the trials and nodes.

## Time-outs and dropouts

- A player who runs out of time puts nothing in the pot, keeps their tokens
  and still gets their share. The trial's `time_limit_reached` records this.
- A player who returns the study, or closes the page and so is late for the
  end of a round (`LATE_AFTER`), leaves the group and earns nothing for that
  round. The others carry on while at least two remain, sharing the pot
  between fewer players.
- When only one player remains, the group dissolves: the round is cancelled,
  the node's `sync_group_dissolved_at` records when (exported as the ISO
  timestamp `dissolved_at` in the `team_round` table), and the last player
  keeps their tokens for it, whether or not they had already contributed.
  `score_answer` pays each player by their trial's `sync_group_outcome`.
- Nobody is failed because others left: the last player, a player who comes
  back after being removed, and a participant for whom no group forms within
  `GROUPING_WAIT` are each told why the game ended for them.
- A player the experimenter removes on the dashboard earns nothing for
  that round and is told they were removed from the game.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

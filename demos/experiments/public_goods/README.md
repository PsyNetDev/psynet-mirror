# README

A repeated public goods game in groups of three. Each round, every member
privately puts some of their tokens in a group pot, within a time limit; the
pot is multiplied and shared between the members who played the round, and
everyone sees the group's contributions and what they earned, paid as a
bonus.

Good reference for a `SimpleGrouper` with a `quorum` below its size, so
that the group carries on with fewer players, a scoring `GroupBarrier` that
fails late players (`late_after` with `late_action="fail"`), `on_release`
and a `waiting_screen`. Each round is one cued
trial per player (`Trial.cue(round=i)` on a trial class with
`sync_group_type`): the group's pot is saved once on the round its members'
trials share (`trial.group_round.var`), and each player's contribution and payoff on their trial,
which pays the bonus (`score_answer` and
`compute_performance_reward`). The basic data is read from the trials and rounds.

## Time-outs and dropouts

- A player who runs out of time puts nothing in the pot, keeps their tokens
  and still gets their share. The trial's `time_limit_reached` records this.
- A player who returns the study, or closes the page and so is late for the
  end of a round (`LATE_AFTER`, `late_action="fail"`), is failed and earns
  nothing for that round. The others carry on while at least two remain,
  sharing the pot between fewer players.
- When only one player remains, the group dissolves and that player is
  failed too (`below_quorum="fail"`), because a public goods game needs
  others to play with. The round is cancelled, and the round's
  `dissolved_at` records when (exported as the ISO timestamp `dissolved_at`
  in the `team_round` table).
- A participant for whom no group forms within `GROUPING_WAIT` is failed
  (the grouper's default `max_wait_action="fail"`).
- Failing isn't a penalty here: it ends the session promptly, and failed
  participants are paid for the rounds they completed. Only finished trials
  are scored, so a failed player earns nothing for the round they left in.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

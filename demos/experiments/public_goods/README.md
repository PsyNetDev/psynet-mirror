# README

A repeated public goods game in groups of three. Each round, every member
privately puts some of their tokens in a group pot, within a time limit; the
pot is multiplied and shared between the members who played the round, and
everyone sees the group's contributions and what they earned, paid as a
bonus. The game carries on when a member returns the study or stops
responding, sharing the pot between fewer players, until only one is left.
Nobody is failed for someone else leaving: the last player, a player who was
away too long, and a participant for whom no group forms are each told why
the game ended for them.

Good reference for a `SimpleGrouper` with a `quorum` whose members carry on
without the group, a scoring `GroupBarrier` with `late_after`, `on_release`
and `on_dissolve`, and `only_in_group(..., otherwise=...)` for players without
a group. Each round is one cued trial per player (`Trial.cue(..., round=...)`
with `sync_group_type`): the group's pot is saved once on the node its
members' trials share, each player's contribution and payoff on their trial,
which pays the bonus, and the basic data is read from the trials and nodes.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

# README

A repeated public goods game in groups of three. Each round, every member
privately puts some of their tokens in a group pot, within a time limit; the
pot is multiplied and shared between the members who played the round, and
everyone sees the group's contributions and what they earned, paid as a
bonus. A member who runs out of time puts nothing in but keeps their tokens
and their share. The game carries on when a member returns the study or stops
responding, sharing the pot between fewer players, until only one is left; a
member who leaves this way earns nothing for that round.
Nobody is failed for someone else leaving: the last player, a player who was
away too long, and a participant for whom no group forms are each told why
the game ended for them.

Good reference for a `SimpleGrouper` with a `quorum` whose members carry on
without the group, a scoring `GroupBarrier` with `late_after`, `on_release`,
`on_dissolve` and a `waiting_screen`, and `for_loop(..., stop_if=...)` with a
`conditional` afterwards for players without a group. Each round is one cued
trial per player (`Trial.cue(round=i)` on a trial class with
`sync_group_type`, the loop of a fixed group): the group's pot is saved once
on the node its members' trials share, each player's contribution and payoff
on their trial, which pays the bonus, and the trial's `sync_group_outcome`
says whether the player stayed to the end of the round or why they left. The
basic data is read from the trials and nodes.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

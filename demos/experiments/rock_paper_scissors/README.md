# README

A synchronized two-player game: partners simultaneously choose rock, paper, or
scissors, see the scored outcome, then chat about the round in a shared room.
A `GroupPrompt` shows both partners, with a tick once the partner has chosen,
and then both choices in speech bubbles with the winner highlighted.
Good reference for combining `SimpleGrouper`, group barriers, scoring and
`ChatRoom` feedback in one loop. Each round is one cued trial per player
(`Trial.cue(round=i)` on a trial class with `sync_group_type`): the barrier
that ends the round saves each player's action, their partner's action and
the result on the player's trial, and `get_basic_data` exports one row per
player per round from the trials.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

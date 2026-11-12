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

## Dropouts

The demo doesn't handle dropouts; see `public_goods` for a game that carries
on when players leave.

- A player whose partner goes silent waits up to `PARTNER_WAIT_SECONDS` at
  the next barrier and is then failed, as is a participant for whom no
  partner arrives in that time.
- A partner who is removed from the pair instead, for example by returning
  the study or being failed elsewhere, dissolves it at once, and the
  remaining player is failed with no wait.
- Each trial's `sync_group_outcome` (the `outcome` column of the basic data)
  is `"stayed"` if the round was scored. Otherwise it records how the player
  left the pair: when a partner goes silent, the player who waited for them
  leaves as `"waited_too_long"` and the silent partner, if they had started
  that round, as `"group_dissolved"`; a partner who went silent between
  rounds has no row for the next round. A round that was never scored has no results page and
  `None` in the result columns.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

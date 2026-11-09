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
(`Trial.cue(...)` on a trial class with `sync_group_type`): the group's estimates
and median are saved once on the node its members' trials share, and a
player without a group gets an ungrouped trial that asks only for their
estimate. `get_basic_data` exports a row for every trial, including answers
given alone and trials whose player left before answering, and the medians
from the nodes.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

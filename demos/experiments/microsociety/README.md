# README

A microsociety of three fishers whose members are replaced one at a time.
Each round, every member picks one of eight fishing spots and catches a
noisy number of fish around the spot's hidden average; then everyone sees
where the others fished and what they caught, and each fish pays a bonus.

The society keeps taking newcomers. A newcomer first reads the society's
recent catches and the tips left by members who have gone, then joins the
round in progress. At the end of that round the longest-serving member
retires, so the society is back to three. A member also stops after
`MAX_ROUNDS` rounds. Members who retire or reach the cap leave a tip for
those who come after them. This lets you study whether knowledge of the
good spots survives the turnover of the people who found them.

Good reference for a group that runs on with changing membership:
`SimpleGrouper(..., join_existing_groups=True)` with a `max_group_size` one
above the society's size, a `while_loop` of cued trials without `round=`
(so a newcomer's cue joins the round in progress), a round's single
`GroupBarrier` whose `on_release` scores the round and uses `group_seats`
to find the longest-serving member, and `SyncGroup.rounds` to show a
newcomer the society's history. Tips are stored on the leaving member's
last trial, so no two participants write the same record.

## How memberships end

`life_stage` names each case; the rounds loop runs while it is `"playing"`.
The stage is stored as `participant.var.left_as` before the member leaves
the society, and the end of the timeline shows the page for it.

| Stage | Caused by | What happens |
|---|---|---|
| `retired` | A newcomer played a round with the member, who was the longest-serving. | Leaves a tip. |
| `played_max_rounds` | The member played `MAX_ROUNDS` rounds. | Leaves a tip. |
| `late` | The member returned the study or closed the page, and so missed the end of a round (`LATE_AFTER`). | Earns nothing for that round; the others carry on. |
| `group_dissolved` | One member was left, and no newcomer joined within `TOP_UP_WAIT`. | Told the society ended. |
| `removed` | The experimenter removed the member on the dashboard. | Told they were removed. |
| `no_group_formed` | No society formed or had room within `GROUPING_WAIT`. | Told no society was found. |

A member who runs out of time in a round stays in the society: they catch
nothing that round, and the trial's `time_limit_reached` records it.

A member left alone keeps playing: they wait at the end of their next round
for up to `TOP_UP_WAIT` seconds for a newcomer to join them. So the society
only lasts while people keep arriving. With recruitment in bursts, a society
can dwindle to one member between bursts and end; a later burst then starts
new societies. Raise `TOP_UP_WAIT` if newcomers arrive slowly.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

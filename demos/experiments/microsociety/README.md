# README

A microsociety of three fishers whose members are replaced one at a time.
Each round, every member picks one of eight fishing spots and catches a
noisy number of fish around the spot's hidden average; then everyone sees
where the others fished and what they caught, and each fish pays a bonus.

The society keeps taking newcomers. A newcomer first reads the society's
recent catches and the tips left by members who have gone, then joins the
round in progress. If that round had more than three members, the
longest-serving member retires at its end, so while newcomers keep arriving,
one member leaves per newcomer. `MAX_ROUNDS` is a safety limit for when they
stop. Members who retire or reach the cap leave a tip for
those who come after them. This lets you study whether knowledge of the
good spots survives the turnover of the people who found them.

Good reference for a group that runs on with changing membership:
`SimpleGrouper(..., join_existing_groups=True)` with a `max_group_size` one
above the society's size, a `while_loop` of cued trials without `round=`
(so a newcomer's cue joins the round in progress), a round's single
`GroupBarrier` whose `on_release` scores the round and uses `group_seats`
to find the longest-serving member, `SyncGroup.is_newcomer` to tell
newcomers from founders, and `SyncGroup.rounds` on
`participant.latest_sync_group(...)` to show a newcomer the society's
history, which still works if they leave while reading it. Tips are stored on the leaving member's
last trial, so no two participants write the same record.

## How memberships end

`life_stage` names each case from the member's trials and their removal
reason; the rounds loop runs while it is `"playing"`, the end of the timeline
shows the page for the case, and the `member` export table records it.
Retiring members and members who played `MAX_ROUNDS` rounds leave the society
when their last round is scored, so the next round doesn't wait while they
read their results.

| Stage | Caused by | What happens |
|---|---|---|
| `retired` | A newcomer played a round with the member, who was the longest-serving. Takes precedence if that round was also their `MAX_ROUNDS`th. | Leaves a tip. |
| `played_max_rounds` | The member played `MAX_ROUNDS` rounds. | Leaves a tip. |
| `late` | The member was inactive for longer than `LATE_AFTER`, for example by closing the page, and missed the end of a round. | Earns nothing for that round; the others carry on. Sees the page if they come back. |
| `left_experiment` | The member returned the study or was failed. | Sees no page; the others carry on. |
| `group_dissolved` | One member was left, and no newcomer joined within `TOP_UP_WAIT`. | Keeps the catch of the round in progress, and is told the society ended. |
| `removed` | The experimenter removed the member on the dashboard. | Told they were removed. |
| `no_group_formed` | No society formed or had room within `GROUPING_WAIT`. | Told no society was found. |

A member who leaves in their last round leaves for that reason and writes
no tip. In the export, a member who is away but not yet removed is
`"playing"`.

A member who runs out of time in a round stays in the society: they catch
nothing that round, and the trial's `time_limit_reached` records it.

A member left alone keeps playing, and the society dissolves if no newcomer
joins within `TOP_UP_WAIT` seconds of the others leaving. This time includes
the lone member's results and decision pages, so `TOP_UP_WAIT` is set well
above them. So the society
only lasts while people keep arriving. With recruitment in bursts, a society
can dwindle to one member between bursts and end; a later burst then starts
new societies. Raise `TOP_UP_WAIT` if newcomers arrive slowly. A society
takes newcomers only up to four members (`max_group_size` is one above its
size), so a full society takes one at a time; when several people arrive
together, those it has no room for wait at the grouper and may end as
`no_group_formed` after `GROUPING_WAIT`.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

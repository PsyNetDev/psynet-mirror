# README

A microsociety of three fishers whose members are replaced one at a time.
Each round, every member picks one of eight fishing spots and catches a
noisy number of fish around the spot's hidden average; then everyone sees
where the others fished and what they caught, and each fish pays a bonus.

The society keeps taking newcomers. A newcomer waits for the next round to
start, then reads the society's recent catches and the tips left by members
who have gone, and plays that round. If that round had more than three
members, the longest-serving member retires at its end, so while newcomers keep arriving,
one member leaves per newcomer. `MAX_ROUNDS` is a safety limit for when they
stop. Members who retire or reach the cap leave a tip for
those who come after them. This lets you study whether knowledge of the
good spots survives the turnover of the people who found them.

Good reference for a group that runs on with changing membership:
`SimpleGrouper(..., join_existing_groups=True,
use_admission_points=True)` with a `max_group_size` one above
the society's size, a `while_loop` whose rounds start at a
`GroupBarrier(admission_point=True, newcomer_page=...)` that admits waiting
newcomers and shows them the society's history, then cued trials without
`round=`, a round-end `GroupBarrier` whose `on_release` scores the round and
uses `SyncGroup.seats` to find the longest-serving member, and `SyncGroup.rounds`
on `participant.latest_sync_group(...)` for the history, which still works
if the newcomer leaves while reading it. Tips are stored
on the leaving member's last trial, so no two participants write the same
record.

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
| `late` | The member was inactive, for example by closing the page, and missed the start of a round (`LATE_AFTER`) or its end (`FINISH_LATE_AFTER`, counted from 10 seconds after the fishing page's time limit). | Failed (`late_action="fail"`), earning nothing for that round; the others carry on. |
| `left_experiment` | The member returned the study or was failed for another reason. | Sees no page; the others carry on. |
| `group_dissolved` | One member was left: during a round, when the round's `round_finished` barrier is next checked, or at the start of a round, if no newcomer joined within `TOP_UP_WAIT`. | Failed (`below_quorum="fail"`), because nobody fishes in a society of one. |
| `no_group_formed` | No society formed or had room within `GROUPING_WAIT`. | Failed (the grouper's default `max_wait_action="fail"`). |
| `not_admitted` | A newcomer was still waiting for a round to start after `NEWCOMER_MAX_WAIT`, or the society ended first. | Told on their next page, and that they didn't play. |

Failing isn't a penalty here: it ends the session promptly, and failed
participants are paid for what they completed. A member who leaves in their
last round leaves for that reason and writes no tip. In the export, a member
who is away but not yet removed is `"playing"`.

A member who runs out of time in a round stays in the society: they catch
nothing that round, and the trial's `time_limit_reached` records it.

A member left alone between rounds waits at the start of the next round for
up to `TOP_UP_WAIT` seconds for a newcomer to join them, and is failed if
none does. A member left alone during a round ends the society at the
round's `round_finished` barrier, and is failed:
the society still accepts newcomers, so the departure itself doesn't
dissolve it, but that barrier isn't an admission point, so it can't wait
for one. So the society
only lasts while people keep arriving. With recruitment in bursts, a society
can dwindle to one member between bursts and end; a later burst then starts
new societies. Raise `TOP_UP_WAIT` if newcomers arrive slowly. A society
takes newcomers only up to four members (`max_group_size` is one above its
size), so a full society takes one at a time; when several people arrive
together, those it has no room for wait at the grouper and may be failed as
`no_group_formed` after `GROUPING_WAIT`.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

# README

A round-based multiplayer game. Every 10 seconds, everyone who is ready is
put into rooms of up to eight players, and each player picks a number. The
lowest number that nobody else in the room picked wins a bonus.

Players who don't choose in time sit out that round and join the next one,
instead of holding up their room or being failed. Someone left waiting with
nobody to play with skips the round after 60 seconds with a short message,
instead of being failed. Good
reference for `Regrouper(every=...)` rounds on fixed ticks, the `{SECONDS}` countdown,
a page `time_limit`, and `GroupBarrier` timeouts that remove late players from the group rather than fail them.
Each round is one cued trial per player (`Trial.cue(...)` with
`sync_group_type`), so the room's results live on a node shared by its trials
and the basic data is read from trials and nodes.

A player the experimenter removes from their room on the dashboard misses
that round, is told why, and joins the next one.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

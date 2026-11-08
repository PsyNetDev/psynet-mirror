# README

A round-based multiplayer game. Every 10 seconds, everyone who is ready is
put into rooms of up to eight players, and each player picks a number. The
lowest number that nobody else in the room picked wins.

Players who don't choose in time sit out that round and join the next one,
instead of holding up their room or being failed. Someone left waiting with
nobody to play with is still failed after the usual five-minute wait. Good
reference for `Regrouper(every=...)` rounds on fixed ticks, the `{SECONDS}` countdown,
a page `time_limit`, and `GroupBarrier` timeouts that remove late players from the group rather than fail them.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

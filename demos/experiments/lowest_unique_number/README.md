# README

A round-based multiplayer game. Every 10 seconds, everyone who is ready is
put into rooms of up to eight players, and each player picks a number. The
lowest number that nobody else in the room picked wins.

Players who don't choose in time sit out that round and join the next one,
instead of holding up their room or being failed. Good reference for
`Regrouper` with a `Clock` deadline, the `{SECONDS}` countdown, a page
`time_limit`, and `GroupBarrier` timeouts that kick rather than fail.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

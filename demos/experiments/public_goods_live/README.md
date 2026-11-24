# README

A repeated public goods game in teams of three, played live. Each round,
every member chooses how many of their 10 tokens to put in the group pot,
sees the others' contributions as they change, and can change their own
until the round's time is up. The pot is then multiplied by 1.5 and shared
between the members.

It is the live counterpart of `public_goods`, with the same team set-up:

- A member who doesn't come back for the next round within `LATE_AFTER`
  seconds of reading the results is failed (`late_action="fail"`). The
  other two carry on, sharing the pot between them.
- A member who reaches a round but doesn't open its game page within
  `LATE_AFTER` seconds isn't coming, for example because they closed their
  page as the round began. The round starts without them, and the others'
  pages show them as not here. Unless they arrive in time to play, they
  don't share the pot, aren't paid for the round, and are failed once the
  round ends (`absent_action="fail"`). The export's `arrived` column is
  `False` for them.
- A member who closes the game page during a round, or never opens it, is
  gone once they have been away for `AWAY_SECONDS`, 10 seconds (the game's
  `away_timeout`). If fewer than two members are left, the round ends early
  with nothing in the pot, rather than being played alone, and each member
  who played it keeps their 10 tokens.
- When only one member remains, they are failed too (`below_quorum="fail"`),
  because a public goods game needs others to play with. So is a
  participant for whom no team forms within `GROUPING_WAIT` (the grouper's
  default `max_wait_action="fail"`).
- Failing isn't a penalty: it ends a session that can no longer
  contribute, and failed participants are paid for the rounds they
  completed.

## Usage

Run `psynet debug local` and open the participant link in three browser
windows. `psynet test local` plays the first round with three bots, then
has one go quiet, so it is failed, while the other two play the last two
rounds.

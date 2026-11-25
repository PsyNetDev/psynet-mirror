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
  `READY_SECONDS`, 15 seconds (the game's `ready_timeout`), isn't coming,
  for example because they closed their page as the round began. The round
  starts without them, and the others' pages show them as not here. If
  they open the page during the round, they join it and share the pot.
  Otherwise they don't share the pot, aren't paid for the round, and are
  failed once the round ends (`absent_action="fail"`).
- If fewer than two members (the game's `min_players`) open a round's game
  page within `READY_SECONDS`, the round can't be played: PsyNet ends it
  without starting it, with the end reason `"too_few_ready"`, rather than
  letting it be played alone, and it has no pot. The member who opened it
  keeps their 10 tokens for the round, and their page says so. The members who
  didn't are failed, which leaves the team below its quorum, so the member
  who opened it is failed too, as below, and goes to the end of the
  experiment without a feedback page.
- A member who closes the game page during a round still counts for it:
  their contribution stays in the pot, they are paid for the round, and
  they are failed at the next round if they don't come back.
- When only one member remains, they are failed too (`below_quorum="fail"`),
  because a public goods game needs others to play with. So is a
  participant for whom no team forms within `GROUPING_WAIT` (the grouper's
  default `max_wait_action="fail"`).
- The export's `player_round` rows say how each round ended
  (`end_reason`: `"finished"` or `"too_few_ready"`), whether the
  player opened it (`arrived`), and how many players did (`n_players`).
- Failing isn't a penalty: it ends a session that can no longer
  contribute, and failed participants are paid for the rounds they
  completed.

## Usage

Run `psynet debug local` and open the participant link in three browser
windows. `psynet test local` plays the first round with three bots, then
has one go quiet, so it is failed, while the other two play the last two
rounds.

# README

Pairs of participants play two live games of rock, paper, scissors, of five
and then three throws, each game on one page. The server
keeps the game's state, scores each throw once both players have chosen, and
sends each player's page its own view of the game, so a page that reloads
shows the game as it stands. If a player's partner leaves the page, the
player's page says so.

Each game is one cued trial per player. The trial's definition says how many
throws the game has and what a throw won pays, which is more in the second
game. The trial starts the pair's game, with the number of throws as the
game's settings, along with what a throw won pays, and shows the game page.
The trial's answer is the player's part of the game's outcome: their throws,
with both choices and the result for them, the throws each player won, and
whether the game was played to the end. The pair's whole outcome is
on the trial's `group_round`. The trial's score is the number of throws the
player won. The game's `performance_reward` pays the reward for them when
the game's result is saved, whether or not the player is still on the page,
and PsyNet records it on the trial, so each trial's `performance_reward` is
what its game paid.

## When a partner leaves

- A partner who never opens the game page, for example because they closed
  their page just as the pair formed: a game for two can't start without
  them, so it ends unplayed after `READY_SECONDS`, 20 seconds (the game's
  `ready_timeout`), with PsyNet's end reason `"too_few_ready"`. The other
  player's page briefly says that the game can't be played without their
  partner, then moves on to the result.
- A partner who closes the game page during a game: the other player's page
  says so. If the partner doesn't come back within 30 seconds, the game's
  `away_timeout`, the game ends. Both players are paid for the throws they
  won, including the partner who never comes back.
- In both cases, the other player sees their result and then, after the
  first game, waits for the partner at the start of the second game, as in
  the next case, but only until 30 seconds after the game ended: 10 seconds
  for a late answer to arrive and then `LATE_AFTER`, 20 seconds. The
  partner never opened their result page, so its time doesn't count. After
  the second game nobody waits for them, so they aren't failed.
- A partner who saw their result but doesn't come back for the second
  game: the other player waits for them at the start of the game, for as
  long as the partner's 30-second result page, 10 seconds for a late answer
  to arrive and then `LATE_AFTER`, 20 seconds. The partner is
  then late and failed (`late_action="fail"`). The pair can't play a game
  for two without them, so the player who waited is failed too
  (`below_quorum="fail"`).
- Failing isn't a penalty: it ends a session that can no longer
  contribute, and both players keep what they earned.

`psynet test` plays both games with two bots.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

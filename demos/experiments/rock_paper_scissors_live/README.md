# README

Pairs of participants play two games of rock, paper, scissors as live
sessions, of five and then three rounds, each game on one page. The server
keeps the game's state, scores each round once both players have chosen, and
sends each player's page its own view of the game, so a page that reloads
shows the game as it stands. If a player's partner leaves the page, the
player's page says so.

Each game is one cued trial per player. The trial's definition says how many
rounds the game has and what a round won pays, which is more in the second
game. The trial starts the pair's session, with the number of rounds as the
session's settings, and shows the game page. The game's outcome is the
trial's answer. The trial's score is the number of rounds the player won, and
the trial pays the bonus for them, so each trial's `performance_reward` is
what its game paid.

## When a partner leaves

- A partner who closes the game page during a game: the other player's page
  says so, and the game ends when the pair finishes it or at its five-minute
  limit. Both players are paid for the rounds they won.
- A partner who doesn't come back for the second game: the other player
  waits five minutes for them at the start of the game, then leaves the pair.
  Their game page has no session and shows no game, and their trial has no
  answer and pays nothing. A page after the games tells them there are no
  more, with their bonus.
- The partner who was away, if they come back after that, is no longer in a
  pair either. The loop of games stops for them, and the page after the games
  tells them so.

`psynet test` plays both games with two bots.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

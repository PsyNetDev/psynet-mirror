# README

Pairs of participants play two games of rock, paper, scissors as live
sessions, each of five rounds on one page. The server keeps the game's state,
scores each round once both players have chosen, and sends each player's page
its own view of the game, so a page that reloads shows the game as it stands.
If a player's partner leaves the page, the player's page says so.

Each game is one cued trial per player. The trial starts the pair's session
and shows the game page, and the game's outcome is the trial's answer. Each
round won pays a bonus, which is larger in the second game. The amount is in
the trial's definition, which the trial passes to the game as the session's
settings.

A player whose partner doesn't come back for the second game waits a minute
for them, then leaves the pair and finishes the experiment without playing
it. `psynet test` plays both games with two bots.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

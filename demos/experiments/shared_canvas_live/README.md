# README

In this live session, a group of players moves around a shared canvas with the
arrow keys for 30 seconds, collecting coins. Players speed up while a key is
held and slow down once it's released. More coins appear while the game runs,
and each coin collected pays a bonus.

The server keeps every player's position. Each page sends which keys were held
and for how long. The game works out where that takes the player and which
coins they pass, and it charges each move against its own clock, so every
player moves at the same speed however many moves their page sends.

The page shows the player's own moves at once by predicting them. It uses the
same arithmetic as the game, with the rules `experiment.py` passes it in
`RULES`, so the prediction matches the game's views exactly unless the game
has to shorten a move. The page draws the other players moving smoothly by
interpolating between the game's ticks.

`GROUP_SIZE` in `experiment.py` sets how many play together, from 2 to 8.
Bots head for the nearest coin that isn't much farther from them than from
anyone else. They leave a coin to the others once two players are nearer to
it, so that in a big group they spread out. `BOT_SPEED`, from 0 to 1, sets how
hard they are to beat. `psynet test` plays the game with bots.

## How the movement differs from Dallinger's coins demo

This game is much like Dallinger's
[coins demo](https://github.com/Dallinger/Dallinger/tree/master/demos/dlgr/demos/coins),
and holds players to the game's clock in the same way: each move is charged
against the clock, and a player can catch up on at most `SAVED_MOVEMENT`
seconds. What differs is how players move.

In the coins demo, a player moves at a fixed speed while a key is held and
stops as soon as it's released. Where a move takes them depends only on where
they started, which way they went and for how long. So each move is a single
sum, and the state only needs each player's position.

Here, a player speeds up while a key is held, and keeps moving once it's
released, slowing down until they stop. That feels more like moving a real
object, and it changes five things:

- The state keeps each player's velocity as well as their position, and the
  views pass it on to the pages.
- A player can move with no key held. So the page keeps sending moves with no
  keys while its player coasts, and one more when they come to rest. If the
  page stops sending, as when it's closed, the game's `tick` lets the player
  coast to a stop (see `COAST_AFTER`).
- Where a move takes a player depends on the whole path, not just how long it
  lasts. So `advance` works out each move in small steps of `STEP` seconds,
  and collects any coin the player passes during each step.
- For the page's prediction to match the game exactly, the page has to take
  the same steps, in the same order, with the same numbers. So
  `static/shared-canvas.js` repeats `advance` line for line, and reads the
  rules from `RULES`, which `experiment.py` passes to the page, instead of
  keeping its own copy. A test in PsyNet's own test suite checks that the two
  agree.
- Bots allow for coasting too. A bot aims short of where it's heading by the
  distance it would coast, so it slows down as it gets there.

## What's saved

The game page's answer is the game's outcome: each player's coins, keyed by
participant id, and every coin collected, with who collected it and the
session time when the game counted it. Pages send many moves a second, so the
session's record keeps only the moves that collected a coin. Each of those
saved moves also says when the participant's page sent it, by the browser's
clock, for analyses that need the participant's own timing.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

To try it yourself, run `psynet debug local --legacy` and open the participant
link in two browser windows. `--legacy` runs gunicorn, the web server deployed
experiments use, instead of the auto-reloading development server. Under the
development server, the other players' movement can pause now and then.

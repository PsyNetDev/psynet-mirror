# README

In this live game, each player in a group steers a snake around a shared
board with the arrow keys for 60 seconds. A snake grows each time it eats a
piece of food. If it hits a wall or any snake, its own body included, it
crashes and comes back two seconds later somewhere else. Each piece of food
eaten pays a reward.

The game moves every snake one square on each of its ticks, eight times a
second. A page only sends the game which way the player wants to turn. The
game keeps up to two turns per player and makes one on each tick, so two
quick key presses make a U-turn. On each tick it moves all the snakes first
and then works out the crashes, so that no player gains from having their
snake moved first. A head that lands on another head crashes both snakes.

`GROUP_SIZE` in `experiment.py` sets how many play together, from 2 to 4.
Bots head for the nearest food, turning only onto empty squares. `psynet test`
plays the game with bots.

A player who hasn't opened the game page 60 seconds after the group formed
is failed (`late_action="fail"`). The others play without them, as long as
at least two are left; a player left alone is failed too
(`below_quorum="fail"`). Failing isn't a penalty: it ends a session that
can no longer contribute.

## How this differs from the other live game demos

In the shared canvas demo, each page sends the keys its player is holding
many times a second, and it predicts the player's moves and interpolates
between ticks to look smooth. Here, the page sends only the player's turns,
and each tick's view shows the whole board. Snakes move a whole square at a
time, so the page just draws each view as it arrives, with no prediction or
interpolation. That is the simplest way to write a game page, and it's enough
for many games.

A turn takes effect on the next tick, so players see their snake turn within
about an eighth of a second of pressing a key.

## What's saved

The game's outcome records how many pieces of food each player's snake ate
and how many times it crashed, in player order. Each player's
answer on the game page is their own part of it: their score (the food
their snake ate), whether it was the best, their crashes,
and whether the game was played to the end.
Players send only a few turns a second, so the game's record keeps every
turn, with when the participant's page sent it.

## Usage

For instructions on how to run PsyNet experiments like this one, visit the
[PsyNet documentation](https://psynetdev.gitlab.io/PsyNet/).

To try it yourself, run `psynet debug local --legacy` and open the participant
link in two browser windows. `--legacy` runs gunicorn, the web server deployed
experiments use, instead of the auto-reloading development server. Under the
development server, the snakes can pause now and then.

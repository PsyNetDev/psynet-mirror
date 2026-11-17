.. _design-live-games:

Live games
==========

In most group experiments, members interact by moving through pages: each
answers on their own page, a barrier waits for all of them, and then everyone
moves on to a page that shows the result. In a **live game**, the members
stay on one page, and what one player does reaches the others while they
play: offers go back and forth in a negotiation, players steer around a
shared board, or a society fishes on a lake while its members come and go.

Two ways for a group to interact
--------------------------------

In a round-based design, each step is a request to the server, which saves
the answer and renders the next page. On one computer that takes about 30 ms
for a page, and 100 ms at a barrier, plus the network's round trip, typically
20–150 ms. Above all, the group moves at the pace of its slowest member:
nothing reaches the others until everyone has submitted a page.

In a live game, the page stays open, and each move travels over an open
connection to the game and back to every player, in about 5 ms plus the round
trip. Each move reaches the others as soon as it's made, so players can react
to each other while they act. That's the reason to choose a live game. A
design in which each player decides and then sees everyone's decisions is a
round of trials, and needs no live game.

The network still sets a limit. Players see each other's moves a round trip
late, so a live game can't keep players in step more closely than that, which
rules out tasks such as tapping together in time.

How it works
------------

A game is played from start to end like this:

1. A group reaches the game in the timeline and waits there until all its
   members have arrived, as at any group barrier.
2. The server creates the game and its **state**: everything the game needs
   to know, such as each player's position or the offers made so far. The
   game starts once every player's page has opened, so that nobody misses
   the start.
3. When a player acts, their page sends the game a **message**, such as
   "move to this square". The game's rules apply it to the state, or reject
   it with a reason the page shows.
4. After each change, the server sends each player their **view**: the part
   of the state they may see. Their page updates itself from it, without
   moving to another page.
5. A game can also change by itself on a clock, such as snakes that keep
   moving whether anyone presses a key. It then **ticks** several times a
   second, and sends new views after each tick.
6. Players may close the page and come back, and in some games new players
   join while it runs, or a player finishes before the others.
7. The game ends when its rules say so, when its time is up, or when too
   many players have left. Each player's result is worked out from the state
   and saved, and their page moves on.

Only the server changes the state, so every player plays the same game, a
participant can't change the result by editing their page, and a page that
reloads gets the game as it stands. Every time in a game is in seconds since
it started, on a clock that the server and the pages share.

Designing a live game
---------------------

Messages and rules
~~~~~~~~~~~~~~~~~~

Each thing a player can do is a kind of message, with its own rule, so a
game's rules are split between its message types: "propose a split" and
"accept the offer" in bargaining, "turn left" in snake. A message is a
request from the participant's browser, which they control, so the rule
checks everything that matters to the result, such as that it's the
player's turn, or that a player can't move faster than the game allows by
sending many moves at once.

When players act at the same moment, the server still handles their messages
one at a time, so a rule that settles everything as each message arrives can
favour whoever's message happened to arrive first. Snake moves every snake on
each tick before it works out any crashes, so no snake gets a contested square
just by moving first.

What each player sees
~~~~~~~~~~~~~~~~~~~~~

Whatever isn't in a player's view never reaches their browser, so the view
decides what information is private. In rock, paper, scissors, a player
sees that their partner has chosen, but not what, until both have. What
players see of each other is often part of the design itself: in
``public_goods_live``, each member sees the others' contributions as they
change, which invites them to follow each other, unlike the sealed
contributions of the round-based ``public_goods``.

Time
~~~~

A game can last a fixed time, as snake's 60 seconds do, or end by itself,
such as once every throw has been played, with a limit in case it doesn't.
Players who know when the game ends behave differently near the end, such as
conceding at the last moment in a negotiation.

A game that ticks, or in which players move quickly, has to hide the
network's delay, or the player's own moves would show a round trip late and
other players would jump from tick to tick. The page **predicts** the
player's own move, showing it at once, before the server has answered, and
**interpolates** other players, drawing them a moment in the past, moving
smoothly between ticks. A prediction repeats the game's rule on the page, so
keep it to rules that are easy to repeat.

Delay also differs between players: someone on a slower connection sees
others' moves later. So a rule that rewards being first, such as the first to
grab a coin, partly rewards the faster connection, and times measured on the
server include each player's network delay.

Who plays
~~~~~~~~~

Most games are played from start to end by the group that started them. A
player who closes the page or loses their connection is **away**, and counts
as gone only after a grace period, long enough for a reload. The game then
ends for everyone, carries on without them, or hands their part on, as its
design says.

Some games keep going while their members change. A newcomer who reaches the
game while their group is playing joins it, and the game makes room for them,
such as a new boat on the lake. Each player can also finish in their own
time, such as after a set time on the lake, while the others play on. Such
games suit designs about what a group passes on as its members change.

A game can also be played as a trial in each round of a group's trials, so
that each player's result is their trial's answer, and what differs between
games, such as the stake, is in the trial's definition.

The wait before the game
~~~~~~~~~~~~~~~~~~~~~~~~

The wait for the group's members is a group barrier, so everything
:doc:`groups` says about waiting applies. In particular, it needs a limit:
usually how long a member may keep the others waiting before they're late
and leave the group. A group that takes newcomers can't wait for its slowest
member, since it can't tell a slow member from one who hasn't joined yet, so
there each member waits a set time and then moves on.

Kinds of live game
------------------

Live games differ in what moves them on, who plays, and how they end.
PsyNet's demos cover these:

.. list-table::
   :header-rows: 1
   :widths: 20 22 22 18 18

   * - Demo
     - What moves it on
     - Who plays
     - How it ends
     - What it shows
   * - `rock_paper_scissors_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/rock_paper_scissors_live>`__
     - players' choices
     - a fixed pair
     - after its throws
     - hidden choices, revealed together; games as trials
   * - `bargaining_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/bargaining_live>`__
     - players' offers, against a deadline
     - pairs from a cohort, new each round
     - a deal, or time's up
     - offers answered as they're made
   * - `public_goods_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/public_goods_live>`__
     - players' contributions, against a deadline
     - a team that carries on if one leaves
     - time's up
     - others' contributions seen as they change
   * - `snake_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/snake_live>`__
     - ticks, 8 a second
     - a fixed group
     - after 60 seconds
     - a game that moves by itself, with fair rules for simultaneous moves
   * - `shared_canvas_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/shared_canvas_live>`__
     - ticks, 20 a second
     - a fixed group
     - a set time
     - smooth movement, with prediction and interpolation
   * - `microsociety_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/microsociety_live>`__
     - ticks, and catches every few seconds
     - a society that members join and leave while it plays
     - once nobody's left
     - joining a running game, finishing early, and moments

Other designs fit the same pattern. An auction in which bids rise until
nobody outbids moves on players' messages, against a deadline. Players
converging on a meeting point move on a clock. Collaborative drawing, with
each stroke a message, is a fixed group that plays until the drawing is done.

Where the data goes
-------------------

Each game's record is saved with the experiment's data:

- its **outcome**, worked out from the state when it ends, such as each
  player's score. Each player's **answer** is their part of it, which their
  game page saves, so a game played as a trial gives the trial an answer
  like any other.
- its **messages**: every message a page sent, in order, with when it arrived
  and whether the game accepted it. This is the complete record of what each
  player did and when. A fast game can send many messages a second, so it can
  leave out those the analysis won't need, such as every small movement.
- its **moments**: events the game records as they happen, such as each
  catch or each deal, with when they happened. An analysis of what happened
  during a long game reads these, rather than every message.
- **checkpoints**: copies of the whole state, every few seconds and at the
  end, which help to check what a game did.

When planning the analysis, check that the outcome holds how each game ended,
and that what happened along the way is in its moments or its messages.

.. _design-live-games-checks:

What to check when reviewing live games
---------------------------------------

- Do players need to react to each other as they act? If not, a round of
  trials is simpler.
- Can a player see anything in their view that's meant only for others?
- Does each rule check what a player's message could get wrong, or claim
  falsely?
- Is anything decided by speed, and so partly by each player's connection?
- What happens to the others when a player leaves, and how long does the
  game wait for them to come back?
- Does the wait before the game have a limit, and does the game itself
  always end?
- Is what the analysis needs in the outcome, the moments or the messages?

.. seealso::

   :doc:`/code/multiplayer/live_game_tutorial` builds three of the demos step
   by step, and :doc:`/code/multiplayer/live_games` is the reference.

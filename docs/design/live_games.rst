.. _design-live-games:

Live games
==========

In a **live game**, a group plays together on one page in real time: offers
go back and forth in a negotiation, players steer around a shared board, or a
society fishes on a lake while its members come and go.

Two ways for a group to interact
--------------------------------

In a round-based design, each step is a request to the server, which saves
the participant's answer and renders their next page, and a barrier waits
until every member has made that step. Above all, the group moves at the pace
of its slowest member: nothing reaches the others until everyone has
submitted a page.

In a live game, the page stays open, and each move travels over an open
connection to the game and straight back to every player, with nothing to
save or render in between. On one computer, a move reaches the other players
in about 5 ms, against about 30 ms for a page and 100 ms for a barrier. Over
the internet, the network's round trip, typically 20–150 ms, comes on top of
each. What matters more is that each move reaches the others as soon as it's
made, so players can react to each other while they act. That's the reason
to choose a live game. A design in which each player decides and then sees
everyone's decisions is a round of trials, and needs no live game.

All the players need to be online at the same time, as in any group
experiment (see :doc:`groups`).

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
   and saved, and their page moves on. If the game's own code raises an
   error, the game ends as *failed*: the pages keep what they showed, and the
   players move on without an answer.

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
"accept the offer" in bargaining, "turn left" in snake. A message comes from
a browser the participant controls, so its rule checks everything that
matters to the result, such as that it's the player's turn.

The server handles messages one at a time, even when players act at the same
moment, so a rule that settles everything as each message arrives can favour
whoever's message happened to arrive first. Snake moves every snake on each
tick before it works out any crashes, so no snake wins a contested square
just by moving first.

What each player sees
~~~~~~~~~~~~~~~~~~~~~

Whatever isn't in a player's view never reaches their browser, so the view
decides what information is private. In rock, paper, scissors, a player sees
that their partner has chosen, but not what, until both have. What players
see of each other is often part of the design itself: in
``public_goods_live``, each member sees the others' contributions as they
change, which invites them to follow each other, unlike the sealed
contributions of the round-based ``public_goods``.

Players see each other by their pseudonyms, such as "Pink koala", as on the
group's other pages, so they can recognise someone they've played before.
If that could change how they play, such as by building a reputation, the
game page can show everyone as the same anonymous figure instead (see
:doc:`groups`).

Delay
~~~~~

In a fast game, the page hides the round trip. It **predicts** the player's own move, showing it
at once, before the server has answered, and **interpolates** other players
in a game that ticks, drawing them a moment in the past, moving smoothly
between ticks rather than jumping from one to the next. A prediction repeats
the game's rule on the page, so keep it to rules that are easy to repeat.

What the page can't hide is that delay differs between players: someone on a
slower connection sees others' moves later, and their own moves arrive later.
So a rule that rewards being first, such as the first to grab a coin, partly
rewards the faster connection, and times measured on the server include each
player's network delay. Nor can a game keep players in step more closely than
their round trip, which rules out tasks such as tapping together in time.

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

A game can pay each player from its result, or as they earn during the game,
such as for each coin they collect. A player who leaves early keeps what they
earned during the game, and is paid from the result too, once the game ends,
or once their own game ends in a game that lets players finish early.

Around the game
---------------

A live game is one step in the timeline, between barriers like any other
group step:

- **The wait before it** is a group barrier, so everything :doc:`groups` says
  about waiting applies, and it needs a limit: usually how long a member may
  keep the others waiting before they're late and leave the group. A group
  that takes newcomers can't wait for its slowest member, since it can't tell
  a slow member from one who hasn't joined yet, so there each member waits a
  set time and then moves on.
- **The end:** a later barrier counts from when each player's result is
  saved, so a long game doesn't make its players late for the next step.
- **Games played as trials**: a game can be each player's trial in a round
  of a group's trials, with the round's barrier the game's, each player's
  result their trial's answer, and what differs between games, such as the
  stake, in the trial's definition.

Kinds of live game
------------------

Live games differ in what moves them on (only the players' messages, or a
clock too), who plays (a fixed group, or one whose members change), and how
they end (when the rules say so, or when the time is up):

.. list-table::
   :header-rows: 1
   :widths: 30 24 26 20

   * - Demo
     - What moves it on
     - Who plays
     - How it ends
   * - `rock_paper_scissors_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/rock_paper_scissors_live>`__
     - players' choices
     - a fixed pair
     - after its throws
   * - `bargaining_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/bargaining_live>`__
     - players' offers
     - pairs from a cohort, new each round
     - a deal, or time's up
   * - `public_goods_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/public_goods_live>`__
     - players' contributions
     - a team that carries on if one leaves
     - time's up
   * - `snake_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/snake_live>`__
     - ticks, 8 a second
     - a fixed group
     - time's up
   * - `shared_canvas_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/shared_canvas_live>`__
     - ticks, 20 a second
     - a fixed group
     - time's up
   * - `microsociety_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/microsociety_live>`__
     - ticks
     - a society that members join and leave while it plays
     - once nobody's left

Start from:

- ``rock_paper_scissors_live`` for a game of hidden choices revealed
  together, played as trials;
- ``bargaining_live`` or ``public_goods_live`` for players responding to each
  other against a deadline;
- ``snake_live`` for a game that moves by itself;
- ``shared_canvas_live`` for smooth movement, with prediction and
  interpolation;
- ``microsociety_live`` for a game that players join and leave while it
  runs, recording what happens along the way.

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
  Does the analysis leave out games that failed?
- Will the game's code keep up with as many games as will run at once?
- Has someone played the game in several browser windows, reloading one
  and closing another during the game?

.. seealso::

   :doc:`/code/multiplayer/live_game_tutorial` builds three of the demos step
   by step, and :doc:`the reference </code/multiplayer/live_games>` is for looking things up.

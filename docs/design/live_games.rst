.. _design-live-games:

Live games
==========

In most group experiments, members interact by moving through pages: each
answers on their own page, a barrier waits for all of them, and then everyone
moves on to a page that shows the result. A **live game** works differently.
The members stay on one page, and what one player does reaches the others'
screens while they play. This page explains how the two differ, the ideas a
live game is built from, and the kinds of game they make possible. To build
one, read :doc:`/code/multiplayer/live_game_tutorial` next.

Moving pages and redrawing a page
---------------------------------

**Moving pages.** Each step a participant takes is a request to the server:

.. code-block:: text

    click Next ─► POST /response ─► the server saves the answer, works out
                                    the next page and renders it ─► the
                                    browser swaps it in

At a barrier, the member who completes the group releases it in their own
request. The server then sends each waiting member a wake over their open
connection, and each waiting page makes a request of its own to move on.

**Redrawing a page.** In a live game, the page stays open, and its
connection to the game stays open too:

.. code-block:: text

    click ─► a message over the open connection ─► the game applies it to
             the state it holds ─► it sends each player their new view ─►
             each page redraws itself

Nothing is saved or rendered in between: the message is recorded alongside,
a few seconds behind the game.

Measured on one computer, so without any network delay, with two browsers
and the server deployments use (November 2026):

.. list-table::
   :header-rows: 1
   :widths: 52 16 16

   * - From a click to …
     - Median
     - 90th percentile
   * - the next page, for an ordinary page
     - 32 ms
     - 41 ms
   * - the next page for both members, at a group barrier that the click
       completes
     - 94 ms
     - 150 ms
   * - a live game's new view on both players' pages
     - 4 ms
     - 5 ms

Over the internet, each of these adds the network's round trip, typically
20–150 ms depending on where participants are: one round trip for a page or
a live message, and about two for a member waiting at a barrier, whose page
hears of the release and then asks for its next page. Live games can also
show a player's own move at once, before the server has answered (see
`Prediction and interpolation`_).

The bigger difference, though, isn't the speed of one step. With barriers, a
group moves in steps, each as slow as its slowest member: nothing reaches the
others until everyone has submitted a page. In a live game, nobody waits for
anyone: each move reaches the others as soon as it's made, so players can
react to each other while they act, such as an offer that a partner answers
within a second, or a player steering to follow another. That's what to
choose a live game for. A design in which each player makes a decision and
then sees everyone's is a round of trials, and needs no live game.

The network sets a limit that a live game can't remove. Players see each
other's moves a round trip late, and a player on a slower connection sees
them later than one on a faster one. So a live game can't keep players in
step more closely than their connections allow, which rules out tasks such as
tapping together in time. A rule that rewards being first, such as the first
to grab a coin, partly rewards the faster connection. And times measured on
the server include each player's network delay.

The ideas a live game is built from
-----------------------------------

**State.** The server keeps one state for each game: everything the game
needs to know, such as each player's position or the offers made so far. Only
the server changes it, so every player plays the same game, a participant
can't change the result by editing their page, and a page that reloads gets
the game as it stands.

**Messages.** A player acts by sending the game a message, such as "move to
this square". The message is a request: the game's rules either apply it to
the state or reject it, with a reason the page can show. Each kind of message
has its own rule, so a game's rules are its message types, one for each thing
a player can do.

**Views.** Each player's page is sent their view: the part of the state they
may see. Whatever isn't in a player's view never reaches their browser, so
the view is how a game keeps information private, such as a partner's
choice before it's revealed.

**The page updates itself.** A game page doesn't move from one page to the
next: it changes whenever the game as the player sees it changes, by
redrawing what it shows from the newest view.

**The clock.** Every time in a game is in seconds since the game started:
when each message arrived, when the game ends, when a crashed player comes
back. The server and the pages count on the same clock, so a page can show a
countdown or work out where a moving piece is.

**Ticks.** A game can also change by itself, on a clock, such as snakes that
keep moving whether anyone presses a key. It then *ticks* a number of times a
second, typically 8 to 20, and sends every player a new view after each tick.

Prediction and interpolation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A page that only drew the views the server sends would show the player's own
move a round trip late, and other players' movement in jumps, one per tick.
Two ideas hide this:

**Prediction.** The page knows what the player's own move will do, so it
shows the move at once, applied to the newest view, and keeps doing so until
the server's view with the move arrives. If the game rejects the move, the
prediction goes. The page has to work out the move as the game does, so a
prediction is a copy of a rule, and best kept to rules that are easy to
copy.

**Interpolation.** In a game that ticks, a page draws other players a little
in the past, about two ticks, moving smoothly between the views either side.
At 20 ticks a second, that's a tenth of a second behind, which players don't
notice, and much smoother than jumping from tick to tick.

What's recorded
---------------

A game's record is saved with the experiment's data:

**Outcome.** The game's result, worked out from the state when it ends, such
as each player's score. Each player's **answer** is their part of it, which
is what their game page saves, so that a trial played as a live game has an
answer like any other trial.

**Messages.** Every message a page sent, in order, with when it arrived and
whether the game accepted it. This is the complete record of what each player
did and when, but a fast game can send many messages a second, so a game can
leave out messages the analysis won't need, such as every movement.

**Moments.** Events the game records as they happen, such as each catch or
each deal, with when they happened. Moments are what an analysis of what
happened during a long game reads, rather than every message.

**Checkpoints.** Copies of the whole state, taken every few seconds and at the
end. They help to check what a game did, but when they're taken depends on
the game's traffic, so the analysis should rely on moments instead.

So decide what the analysis needs before running the experiment: the outcome
answers how a game ended, moments what happened along the way, and messages
exactly what each player did.

Around the game: the wait, the start and the end
------------------------------------------------

A game starts when a group reaches it, and that step is a group barrier like
any other: the group waits there until all its members arrive. So everything
:doc:`groups` says about waiting applies, and in particular the wait needs a
limit. Usually that's how long a member may keep the others waiting before
they're late and leave the group. A group that takes newcomers can't wait for
its slowest member, since it can't tell a slow member from one who hasn't
joined yet, so each member instead waits for a set time and then moves on.

Once the group is released, the game is created, but it starts only once every
player's page has opened, or after a minute: the **ready step**. Otherwise a
page that opened a moment late would miss the start of a timed game.

The game ends when its rules say so, when its time is up, or when too many
players have left for it to carry on. A player who closes the page or loses
their connection is **away**, and only counts as gone after a grace period,
long enough for a reload. Decide what happens then: the game ends for
everyone, carries on without them, or hands their part on.

When the game ends, each player's page stays until their result is saved, a
few seconds later, and then moves on. A barrier after the
game counts from then, not from when the game started.

Two kinds of game don't fit "start together, end together":

**Joining a running game.** A newcomer who reaches the game while their
group is playing joins the game, and the game makes room for them, such as a
new boat on the lake. This suits societies whose members change while they
play.

**Finishing before the others.** Each player's game can end in their own
time, such as after a set time on the lake, while the others play on. Their
result is worked out then, and they move on.

A game can also be played as a trial in each round of a group's trials: the
round's barrier is the game's, each player's answer is their trial's, and
what differs between games, such as the stake, is in the trial's definition.

Kinds of live game
------------------

Live games differ in three ways: what moves the game on (only the players'
messages, or a clock too), whether the group is fixed or changes while it
plays, and how the game ends. PsyNet's demos cover these:

.. list-table::
   :header-rows: 1
   :widths: 20 22 22 18 18

   * - Demo
     - What moves it on
     - The group
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
     - seeing others' contributions as they change
   * - `snake_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/snake_live>`__
     - ticks, 8 a second
     - a fixed group
     - after 60 seconds
     - a game that moves by itself, and fair rules for simultaneous moves
   * - `shared_canvas_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/shared_canvas_live>`__
     - ticks, 20 a second
     - a fixed group
     - a set time
     - smooth movement, with prediction and interpolation
   * - `microsociety_live <https://gitlab.com/PsyNetDev/PsyNet/-/tree/master/demos/experiments/microsociety_live>`__
     - ticks and catches every few seconds
     - a society that members join and leave while it plays
     - once nobody's left
     - joining a running game, finishing early, and moments

Other designs fit the same three questions. An auction in which bids rise
until nobody outbids moves on players' messages, with a deadline. A
coordination game in which players converge on a meeting point moves on a
clock. Collaborative drawing, with each stroke a message, is a fixed group
until the drawing is done.

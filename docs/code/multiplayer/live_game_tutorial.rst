.. _live_game_tutorial:

====================
Building a live game
====================

This tutorial shows how to build a game that a group of participants play
together in real time. It works through three demos in PsyNet's
``demos/experiments`` folder. Most of the code on this page is included
from the demos' files, so it's the code that runs. You
can run each demo, change it and see what happens.

``rock_paper_scissors_live``
    Two players play two games of rock, paper, scissors, of five and then
    three throws. This demo has every part that a live game needs, so the
    tutorial covers it in the most detail.

``snake_live``
    Each player steers a snake around a shared board. The game moves the
    snakes by itself, eight times a second.

``shared_canvas_live``
    Players move around a canvas collecting coins, and each page draws
    everyone's movement smoothly.

Read it once from start to end: each part builds on the one before. Read the
:doc:`live games design page </design/live_games>` first, which explains how a live game differs from
moving through pages, and the ideas this tutorial puts into code: state,
messages, views, prediction and the game's record. Before you start, you should know how
a PsyNet timeline is put together (:doc:`/code/writing_a_timeline`), how
trials work, and how participants are put into groups
(:doc:`synchronization`). The game pages are written in JavaScript, so it
helps if you have written a little of it.

:doc:`The reference <live_games>` is for looking things up once you're
building your own game. Most sections here end with a link to the matching
section there, which covers the cases this tutorial leaves out.

How a live game works
---------------------

You write the game as a Python class, a subclass of
:class:`~psynet.live_game.LiveGame`, with a
:class:`~psynet.live_game.LiveMessage` subclass for each kind of message a
page can send. Its methods say what the state is at the start, what each
message does, what each player sees, and when the game is over. PsyNet does
the rest: it connects the pages, applies the messages one at a time in the
order they arrive, sends the views, and saves the record.

Part 1: Rock, paper, scissors
-----------------------------

In ``rock_paper_scissors_live``, pairs of participants play two games, the
first of five throws and the second of three. Each player chooses rock, paper
or scissors, and once both have chosen, both see the result of the throw.
Each throw that a player wins pays them a reward, which is larger in the
second game. The demo calls the game's rounds "throws", because a PsyNet round is
something else, a step that a group takes together
(:ref:`rounds-cued-trials`).

To play it yourself, run the demo from a PsyNet source checkout:

.. code-block:: console

    cd demos/experiments/rock_paper_scissors_live
    psynet debug local

Then open the participant link in two browser windows, one for each player.

The rules
~~~~~~~~~

The demo's ``experiment.py`` starts with the rules of the game, written as
ordinary Python:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: Action = Literal
   :end-before: class Choose(LiveMessage):
   :dedent:

``Action`` is the type of a player's choice, which the message below uses for
its ``action`` field, and ``ACTIONS`` lists the three choices, for the page's
buttons and the bots. ``GAMES``, ``RESULT_SECONDS`` and ``LATE_AFTER`` are
used by the demo's trials and timeline, which "Playing it as trials" and
"When a partner leaves" below describe.

PsyNet numbers a game's players from 0, so the two players here are 0 and 1,
and ``1 - player`` is the other one. A throw's
choices are a list, in player order, such as ``["rock", "paper"]``.
``result_for`` says how a throw went for one player, ``throws_seen_by``
lists the throws played so far as one player sees them, and ``count`` counts
the throws that went one way, such as the player's wins. The view and each
player's answer, below, both use them, so the page and the answer show a
throw the same way.

The excerpts on this page leave out the file's imports, which are at the top
of the demo's ``experiment.py``.


The game and its state
~~~~~~~~~~~~~~~~~~~~~~

The game is the class ``RockPaperScissors``:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: class RockPaperScissors(LiveGame):
   :end-before: def initial_state(
   :dedent:

``name`` is a name for the game, which must differ from the name of every
other game in the experiment. ``messages`` lists the kinds of message that a
page can send, which the next section describes. ``min_players`` and
``max_players`` say that the game is for exactly two players. If a player
closes the game page and doesn't come back within 30 seconds, which allows
for a reload, ``away_timeout`` ends the game, so their partner isn't left
waiting. ``timeout`` ends it after five minutes even if both players stop
choosing. :ref:`live-games-time-limits` lists all of a game's time limits.

``initial_state`` returns the state at the start of the game. It receives the
players' numbers, ``[0, 1]``, and the game's settings:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.initial_state
   :dedent:

The state is a dictionary. It can hold dictionaries, lists, strings, numbers,
``True``, ``False`` and ``None``, the same kinds of data that JSON can hold.
Here, ``choices`` holds each player's choice in the current throw, ``None``
until they choose, and ``throws`` the choices of each throw played so far.

The settings are what differs from one play of the game to another. Here,
they say how many throws the game has and what a throw won pays, which
differ between the demo's two games, as "Playing it as trials" below shows. The game's other methods
receive the state but not the settings, so ``initial_state`` puts what they
need into the state. A game that is always played the same way can leave
``settings`` out of ``initial_state``.

Reference: :ref:`live-games-the-game` and :ref:`live-games-time-limits`.

The message
~~~~~~~~~~~

A player makes a choice by sending a ``Choose`` message, a subclass of
:class:`~psynet.live_game.LiveMessage`:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: Choose
   :dedent:

``type`` is the name that the page uses when it sends the message, and
``throw`` and ``action`` are the message's fields, each with its type. A page
sends the message like this:

.. code-block:: javascript

    psynet.liveGame.send("choose", {throw: 2, action: "rock"});

``apply`` is what the message does to the state. It receives the game, here
a ``RockPaperScissors``, for the rare message that needs it, such as one
that pays a reward; the state; the number of the player who sent the
message; and ``now``, the number of seconds since the game started. It
changes the state directly.
Here, it records the player's choice, and once both players have chosen, it
adds the throw's choices to the throws played and starts the next throw.
Each kind of message has its own ``apply``, so the game's rules are split
between its message types, one for each thing a player can do.

``raise Reject("...")`` turns a message down. The state stays as it was
before the message, and the player's page receives the reason. The throw
number in each message lets ``apply`` tell a click meant for this throw from
a late one meant for a throw that has already finished.

Before ``apply`` runs, PsyNet checks the message against its fields. A
message whose ``throw`` isn't a whole number, or whose ``action`` isn't one of
the three listed, is rejected without reaching ``apply``.

Reference: :ref:`live-games-messages`.

What each player sees
~~~~~~~~~~~~~~~~~~~~~

``view`` returns what one player's page shows:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.view
   :dedent:

The view says whether the partner has chosen in the current throw, but not
what they chose. The partner's choice appears in ``results`` only once the
throw is over. This is how a game keeps information private: whatever isn't
in a player's view never reaches their browser, so they can't find it by
looking at the page's code.

The end and the outcome
~~~~~~~~~~~~~~~~~~~~~~~

Three more methods say when the game ends, what its result is, and what each
player's answer is:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: def is_over(
   :end-before: def performance_reward(
   :dedent:

The game checks ``is_over`` after every change to the state, and ends the
game as soon as it returns ``True``.

``outcome`` is the game's result for the whole pair, which is saved with the
experiment's data: here, the choices of each throw. ``reason`` says why the
game ended. For example, it is :data:`~psynet.live_game.FINISHED`
(``"finished"``) when ``is_over`` ended the game, and
:data:`~psynet.live_game.TIMEOUT` (``"timeout"``) when the game's
``timeout`` did.

``answer`` turns the outcome into each player's answer on the game page:
their own throws, with both choices and the result for them, the throws each
of them won, and whether the game was played to the end, so that later pages
and your analysis can tell a finished game from one that ended early.
Without ``answer``, every player's answer would be the whole outcome, and
code reading it would need the player's number to find their part.

Reference: :ref:`live-games-the-game` and :ref:`live-games-answer`.

Bots
~~~~

``psynet test`` runs the experiment with bots, which don't run the page's
JavaScript. Instead, the game plays for them through its ``bot`` method:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.bot
   :dedent:

``bot`` receives the bot's view, its player number and ``now``, and returns
the message the bot sends next, or ``None`` when the bot has nothing to do.
Here, a bot that has already chosen this throw waits, and otherwise it
chooses at random. ``bot`` must return ``None`` once the bot has nothing to
do, or the bots would play forever.

Reference: :ref:`live-games-bots`.

The game page
~~~~~~~~~~~~~

The game page is a :class:`~psynet.live_game.LiveGamePage`. The demo
builds it in a function that takes the trial's definition, which the trial
in `Playing it as trials`_ below passes in:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: rock_paper_scissors_page

Its content holds the page's elements, each with an ``id`` so that the
JavaScript can find it. PsyNet hides it on a page without a game. The other
options change the page's texts: ``waiting_status`` is what the page says
until both pages have opened,
``player_left_message`` the notice while the partner is away, and
``no_game_message`` the notice on a page without a game.
``js_page_modules`` lists the page's JavaScript.

The JavaScript is in ``static/rock-paper-scissors.js``. It exports an
``activate`` function, which PsyNet runs when the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules). Through
``psynet.liveGame``, the function sends the player's messages and draws each
view that arrives.

It finds the page's elements and sets up the variables that the rest of the
page uses:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: export function activate
   :end-before: function enableButtons(
   :dedent:

A participant reaches the game page without a game when their partner was
late for it. ``psynet.liveGame`` does nothing on such a page, so the script
needs no check of its own, and the Next button lets them move on.

The page then registers what happens when the game changes, what the status
line says, and where to show the reason when the game rejects one of the
player's messages:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: psynet.liveGame.onChange(
   :end-before: for (let button of buttons) {
   :dedent:

``onChange`` runs ``render`` whenever the game as the player sees it
changes: each time a new view arrives, including the final view once the
game is over, and, because the page also has a ``predict`` callback, as soon
as the player chooses, with their choice already in the view. `Showing a
choice at once`_ below explains why. ``showStatus`` keeps the status line up to date:
it says the page's ``waiting_status``, here "Waiting for your partner to
open the game", until the game starts, then what its callback returns for
each view, and "The game is over." at the end. ``showRejections`` shows the
reason for a rejected message in the element it's given, until the page
sends its next message.

Each button sends a ``Choose`` message when it's clicked, through the page's
``choose`` function:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: for (let button of buttons) {
   :end-at: }
   :dedent:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: function choose(action) {
   :end-before: // render runs whenever
   :dedent:

``predictedView()`` returns the game as the page shows it now, so the
message is for the throw the page is on.

``render`` draws the page from a view:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: function render(view) {
   :end-before: function choose(action) {
   :dedent:

The view holds every throw played so far, so a page that reloads draws the
whole game again. ``describe``, defined above ``render`` in the file, puts a
throw's result into words, and ``enableButtons`` enables or disables the
three buttons. ``psynet.liveGame.playing`` says whether the game is being
played: it has started, which it does once both pages have opened, and
hasn't ended. The buttons are enabled only
while it is, and the player hasn't chosen yet.

Reference: :ref:`live-games-page`, :ref:`live-games-status` and
:ref:`live-games-cases`.

.. _live-game-tutorial-predict:

Showing a choice at once
~~~~~~~~~~~~~~~~~~~~~~~~

Only the server changes the state, so a player's own move shows on their
page only once the server has applied it and sent back a view: a round trip,
usually a tenth of a second or so, and more on a slow connection. In a fast
game, that lag is enough to feel. And a view caused by another player's move
can arrive in between, which doesn't have the player's move yet, so drawn as
it is, it would briefly undo the move.

The page avoids both by telling ``psynet.liveGame`` what each of its
messages will do to the view, with ``predict``. In a game on a board, where a ``move`` message
gives the player's new square, that would be:

.. code-block:: javascript

    psynet.liveGame.predict((view, type, message) => {
      if (type === "move") {
        view.positions[psynet.liveGame.player] = message.to;
      }
    });

The callback gets a copy of the newest view and changes it as the game will
once it applies the message. From then on, ``onChange``'s callback gets the
newest view with each of the page's messages that the game hasn't applied
yet applied this way, and runs again after each ``send``, so the player's
piece moves the moment they click. Once the game's own view
with the move arrives, the prediction is no longer needed, and if the game
rejects the move, the next view drops it.

Rock, paper, scissors has the same problem in a small way. When both players
choose at nearly the same moment, the view that the partner's choice caused
can arrive first, and it says the player hasn't chosen, so the page would
enable the buttons again for a moment. Its prediction marks the throw as
chosen, for a choice in the throw the view is on:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: psynet.liveGame.predict(
   :end-before: function describe(
   :dedent:

Many games don't need this. The snake demo below draws each view as it
arrives, since its snakes move only on the game's ticks anyway. Part 3 uses
``predict`` to move the player's own piece on a canvas.

Reference: :ref:`live-games-smooth-play`.

Adding the game to the timeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The simplest timeline that plays the game forms pairs, plays one game, and
then shows each player their score:

.. code-block:: python

    timeline = Timeline(
        SimpleGrouper(
            group_type="pair",
            initial_group_size=2,
            below_quorum="fail",
        ),
        PlayLiveGame(
            group_type="pair",
            game_class=RockPaperScissors,
            settings={"throws": 5, "reward_per_win": 0.05},
            page=LiveGamePage(
                "rock_paper_scissors",
                tags.div(...),  # the elements shown above
                js_page_modules=["/static/rock-paper-scissors.js"],
                time_estimate=60,
            ),
            late_after=20,
            late_action="fail",
        ),
        PageMaker(show_score, time_estimate=5),
    )


    def show_score(participant):
        answer = participant.live_games["rock_paper_scissors"].answer
        if answer is None:
            return InfoPage("Your pair couldn't play the game.", time_estimate=5)
        return InfoPage(f"You won {answer['wins']} throws.", time_estimate=5)

- The :class:`~psynet.sync.SimpleGrouper` puts participants into pairs.
- :class:`~psynet.live_game.PlayLiveGame` is the step where the pair plays
  the game. It waits for both players of the pair, starts a game of
  ``game_class`` for them, and shows them its ``page`` together. Its
  ``group_type`` is the grouper's. Its ``settings`` are what
  ``initial_state`` receives.
- ``late_after`` limits that wait. A partner who keeps the other player
  waiting more than 20 seconds is late, and ``late_action="fail"`` fails
  them. A game for two can't go on with one player, so the grouper's
  ``below_quorum="fail"`` fails the player who was on time too. Failing
  isn't a penalty: it ends a session that can no longer contribute, and
  players keep what they have earned. Every ``PlayLiveGame`` needs a limit
  like this.
- ``page`` is the game page, as in `The game page`_ above.
- On the next page, ``participant.live_games`` has the participant's record
  of the game, keyed by the game's ``name``. Its ``answer`` is what the
  game's ``answer`` returned for them, or ``None`` if the pair didn't start
  a game, for example because the experimenter removed the player from
  the pair on the dashboard.

Reference: :ref:`live-games-play`, including :ref:`the wait before the game
<live-games-wait>`, and :ref:`live-games-record`.

Playing it as trials
~~~~~~~~~~~~~~~~~~~~

The demo plays two games, of five throws and then three, and pays for each
throw won, more in the second game. So each game is a trial: the player's
answer on the game page is saved as the trial's answer, like any other
trial's, and what differs between the two games is in the trial's
definition. The trial starts a game for the pair, shows the game page, and
then scores the game:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissorsTrial
   :dedent:

- ``sync_group_type`` says that a group plays the trial, here the pair.
  Each player has a trial of their own, and the two trials share a
  definition.
- ``live_game_class`` names the game the trial plays, so that PsyNet can
  check the two together when the experiment loads.
- ``show_trial`` returns the ``PlayLiveGame``, with the number of throws and
  what a throw won pays from the trial's definition as its settings. Its barrier is the
  :class:`~psynet.sync.GroupBarrier` that a trial a group plays needs, so
  this trial needs no other.
- ``rock_paper_scissors_page``, from `The game page`_ above, builds the
  page from the trial's definition, so its first element says which game
  this is, how many throws it has and what a throw won pays.
- The game page's answer, from the game's ``answer``, becomes the trial's
  answer, and ``trial.live_game`` is the participant's record of the game,
  with the whole pair's outcome.
- ``score_answer`` returns the trial's score, here the number of throws the
  player won. A trial whose pair didn't start a game has no answer, and
  scores 0.
- The game page moves on by itself once the game's result is saved, a few
  seconds after the game ends, to the trial's ``show_feedback`` page, which
  ``gives_feedback`` leaves out for a trial without an answer.

The game pays for the throws each player won, in its
``performance_reward``, at the rate in its settings:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.performance_reward
   :dedent:

PsyNet pays it to both players when the game's result is saved, also to a
player who has closed the page for good, and records it on each player's
trial, so the experiment's data shows what each game paid. A trial could
pay through its own ``compute_performance_reward`` instead, but that runs
only when the player's own page submits (see :ref:`live-games-rewards`).
Paying in both would pay each player twice, so with ``live_game_class``
set, the experiment raises an error when it loads.

The timeline forms the pairs, and then gives each player their trials:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: class Exp(psynet.experiment.Experiment):
   :end-before: def test_check_bot(
   :dedent:

- The loop runs once for each game. ``RockPaperScissorsTrial.cue`` gives the
  participant a trial with the definition that it's passed, here the game's
  number, its throws and what a throw won pays. The loop value is also the
  ``round``, so the two players' trials for a game belong to the same round
  of the pair. :ref:`rounds-cued-trials` explains rounds.
- The :class:`~psynet.timeline.Module` gives the trials a ``module_id``, which
  you can find them by in the experiment's data.
- ``test_n_bots`` and ``test_mode`` set up ``psynet test``. A pair's bots have
  to reach the game together, so the bots run in parallel.

The trial's ``show_feedback`` passes the trial's answer, and the reward that
the game paid, as recorded on the trial, to ``show_result``:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: show_result
   :dedent:

A game can start and end without a throw being played, when a player is
away from the game page for its ``away_timeout`` before the first throw, or
the game reaches its ``timeout`` first, so ``show_result`` checks for that
first. A trial
whose game never started has no answer, and ``gives_feedback`` skips its
feedback.

Reference: :ref:`live-games-answer` and :ref:`live-games-rewards`.

When a partner leaves
~~~~~~~~~~~~~~~~~~~~~

The rest of the timeline deals with a partner who doesn't come back:

- The grouper's ``max_wait_time`` fails a participant who waits five minutes
  without a partner, and sends them to the end of the experiment. Keep
  this unless the design has a meaningful task for them alone, for which
  the advanced ``max_wait_action="continue_without_group"`` lets them carry
  on without a partner.
- Before the second game, the partner may still be reading the first game's
  result, so the result page has a ``time_limit`` of ``RESULT_SECONDS``.
  ``late_after`` counts from 10 seconds after it has run out, time for an
  answer sent at the deadline to arrive, so ``LATE_AFTER`` only has to
  cover the moments after that. A partner who closed their tab on the result
  page is late 30 + 10 + 20 = 60 seconds after it opened.
- A partner who is late is failed, and the grouper's
  ``below_quorum="fail"`` fails the player left behind, who has nobody to
  play the second game with. Both keep what they earned in the first game.
- ``stop_if`` ends the loop for a participant the experimenter has removed
  from their pair on the dashboard, the only way to be without a pair and
  still playing. PsyNet checks it before each game, never during one. The
  ``conditional`` after the loop then shows that participant a page that
  says they were removed:

  .. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
     :start-at: def removed_from_pair(participant):
     :end-before: class Exp(psynet.experiment.Experiment):
     :dedent:

Reference: :ref:`live-games-leaving` and :doc:`late_slow_and_leaving_players`.

Part 2: Snake
-------------

In ``snake_live``, each player in a group steers a snake around a shared board
for 60 seconds. ``GROUP_SIZE`` in the demo's ``experiment.py`` sets how many
play together, from 2 to 4, and it's 2 unless you change it. A snake grows
each time it eats a piece of food. If it hits a wall or any snake, it crashes
and comes back two seconds later somewhere else. Each piece of food eaten pays
a reward.

Rock, paper, scissors changes only when a player sends a message. In snake,
the snakes keep moving whether or not anyone presses a key, so the game has
to change the state by itself, on a clock.

Run it with ``--legacy``, which runs the web server that deployed
experiments use, so that views arrive on time (see :ref:`live-games-bots`):

.. code-block:: console

    cd demos/experiments/snake_live
    psynet debug local --legacy

Then open the participant link in a browser window for each player.

Ticks
~~~~~

The game class sets how often the game ticks:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :start-at: class Snake(LiveGame):
   :end-before: def initial_state(
   :dedent:

``tick_rate = 8`` makes the game **tick** eight times a second. On each tick,
the game's ``tick`` method runs, and then every player's page gets a new
view. ``send_views_on_messages = False`` stops the game from also sending the
player a view after each of their messages, since a turn doesn't change the
board until the next tick.

``tick`` gets the state and ``now``, the seconds since the game started, and
changes the state in place:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: Snake.tick
   :dedent:

It moves the snakes, brings back each crashed snake once ``now`` has passed
its ``back_at``, two seconds after it crashed, and tops up the food. Every
page then gets a view of the new board. Like a message's ``apply``, ``tick``
returns nothing: what it changes in the state is what the game remembers.

``duration = ROUND_SECONDS`` makes the game last 60 seconds, from when it
starts, once every player's page has opened (see :ref:`live-games-ready`).
The game's clock, ``now`` in its methods, starts at 0 then. At the end of the
duration, PsyNet
runs the game's ``tick`` one last time, ends the game with the reason
``"finished"``, and rejects messages that arrive later. A game with a
``duration`` doesn't need a ``timeout``.

A game with deadlines of its own, such as one for each move, keeps them in
the state, because everything about a game has to be there, and returns the
next one from ``next_deadline``. Don't keep them on ``self``: one game object
plays many games, and a game can move to another process. The
``microsociety_live`` demo does this for its catches.

Reference: :ref:`live-games-ready` and :ref:`live-games-time-limits`.

The message says what the player wants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A page doesn't move its snake. It only sends the direction the player wants
to go next:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: Turn
   :dedent:

``apply`` adds the turn to a list of up to two, and on each tick the snake
makes the oldest turn and moves a square, so two quick key presses make a
U-turn. ``apply`` rejects a turn back the way the snake is heading, a third
turn before the snake has made the first two, and any turn while the snake is
crashed.

Moving every snake fairly
~~~~~~~~~~~~~~~~~~~~~~~~~

``tick`` starts with ``move_snakes``:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: move_snakes
   :dedent:

It moves every snake before it works out any crashes. If it moved one snake
and checked it, then moved the next, the snakes moved first would get the
contested squares. :doc:`/design/live_games` says more about rules that the
order of players' messages could make unfair.

The reward
~~~~~~~~~~

Like rock, paper, scissors, snake pays the reward through its game's
``performance_reward`` method:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: Snake.performance_reward
   :dedent:

``performance_reward`` works out each player's reward from the game's
outcome, which is why the outcome lists how much food each snake ate, in
player order. PsyNet pays it once, when the game's result is saved.

Reference: :ref:`live-games-rewards`.

The snake page
~~~~~~~~~~~~~~

The page needs the size of the board and each player's color. Rather than
copy these into the JavaScript, the demo keeps them in one place:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :start-at: #: What the game page needs to draw the board.
   :end-at: RULES = {
   :dedent:

The game page passes it to the JavaScript with
``js_vars={"snake_rules": RULES}``, and ``activate`` reads it from ``vars``.
``live`` is short for ``psynet.liveGame``:

.. literalinclude:: ../../../demos/experiments/snake_live/static/snake.js
   :language: javascript
   :start-at: export function activate
   :end-before: psynet.addPageEventListener(window, "keydown"
   :dedent:

Each view shows the whole board, so the page draws each view as it arrives:

.. literalinclude:: ../../../demos/experiments/snake_live/static/snake.js
   :language: javascript
   :start-at: // The game moves every snake on its ticks
   :end-at: });
   :dedent:

The view lists the snakes in player order, and ``live.player`` is this
player's number, so their snake is ``view.snakes[live.player]``, and its
color is ``rules.colors[live.player]``.

The page sends a turn when the player presses an arrow key, or W, A, S or D.
It sends nothing before the game starts, after it ends or while the snake is
crashed, and it ignores a key that's held down:

.. literalinclude:: ../../../demos/experiments/snake_live/static/snake.js
   :language: javascript
   :start-at: psynet.addPageEventListener(window, "keydown"
   :end-before: function showScores(
   :dedent:

``psynet.addPageEventListener`` adds an ordinary event listener, which PsyNet
removes when the participant moves on to the next page.

The time left comes from ``live.onTimeLeft``, which calls the page back with
the seconds until the end of the game's ``duration`` with each view and a few
times a second.
A crashed snake's ``back_at`` is a time in seconds into the game, so the
status line compares it with ``live.gameTime()``, which counts the same
seconds as ``now`` on the server:

.. literalinclude:: ../../../demos/experiments/snake_live/static/snake.js
   :language: javascript
   :start-at: live.showStatus(status
   :end-before: // The game moves every snake on its ticks
   :dedent:

Reference: :ref:`live-games-time-limits`, for ``onTimeLeft`` and
``gameTime()``.

Part 3: Shared canvas
---------------------

In ``shared_canvas_live``, players move around a canvas with the arrow keys,
collecting coins. A player speeds up while a key is held and slows down once
it's released, so movement is smooth rather than a square at a time. Run it
with ``psynet debug local --legacy``, as for snake. Its ``GROUP_SIZE`` can be
from 2 to 8.

This demo is the most complicated of the three, and most games don't need
what it adds. Its README explains its design in detail. This section covers
three ideas that you may want in your own games.

Holding pages to the game's clock
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

While its player is moving, each page sends a move about 30 times a second,
saying which keys were held and for how long:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/experiment.py
   :pyobject: Move
   :dedent:

``Field`` limits each move to half a second (``SAVED_MOVEMENT``). A page
could still claim more time than has passed by sending many moves at once,
so ``apply`` charges each move against the game's clock. However many moves
a page sends, its player can't move faster than the rules allow.

Reference: :ref:`live-games-messages`.

Smooth movement on the page
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The game ticks 20 times a second, but the page draws about 60 times a
second. If it simply drew each view as it arrived, two things would look
wrong. The player's own piece would move only once their move had reached
the server and come back in a view, a fraction of a second after the key
press. And the other players would stand still between ticks, then jump.
The page fixes the first with **prediction** and the second with
**interpolation**, which it sets up when it opens:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/static/shared-canvas.js
   :language: javascript
   :start-at: live.predict((view, type, message) => {
   :end-at: live.interpolate(interpolate);
   :dedent:

The player's own piece is predicted, as in `Showing a choice at once`_, the
board example there in particular. Each move the page sends is applied to
the latest view at once, by ``advance``, which repeats the arithmetic of the
game's own ``advance`` in ``experiment.py``. The page also has movement it
hasn't sent yet, since it sends a move only about 30 times a second, and the
demo's ``shownView`` function adds that too. So the player's own piece is
drawn where they have just moved it.

The page can't predict the other players, since it learns where they are
only from each tick's view. Instead, it draws them a moment in the past,
where it has a view on either side, part of the way between the two. Each
time the page draws, ``interpolatedView()`` takes the time two tick
intervals ago, a tenth of a second here, finds the views of the ticks before
and after it, ``a`` and ``b``, and calls the page's callback with them and
``fraction``, from 0 at ``a`` to 1 at ``b``. It looks two intervals back,
not one, so that ``b`` has usually arrived even when a view comes a little
late. The callback returns the view to draw:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/static/shared-canvas.js
   :language: javascript
   :start-at: // Places each player between two tick views.
   :end-before: function drawCircle(
   :dedent:

It moves each player in a straight line from where they were in ``a`` to
where they are in ``b``, and copies everything else from ``b``. It builds new
objects with ``...``, JavaScript's spread, rather than changing ``a`` and
``b``, since the page keeps those views to interpolate between again.
Interpolate only what moves smoothly: something that changes in a step,
such as a score, is best taken from ``b`` as it is.

Each time it draws, the page puts the two together:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/static/shared-canvas.js
   :language: javascript
   :start-at: shown = shownView();
   :end-before: if (live.ended) {
   :dedent:

``draw`` takes the coins and the player's own piece from ``shown``, the
predicted view, and the other players from the interpolated view. The other
players are shown a tenth of a second behind, on top of the network delay,
but they move smoothly. The player's own piece is never behind.

Reference: :ref:`live-games-smooth-play`.

Saving fewer messages
~~~~~~~~~~~~~~~~~~~~~

By default, the game's record keeps every message. With 30 moves a second
from each moving player, that's a lot of data that the analysis may not
need. A message type's ``should_save`` decides which of its messages to
keep:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/experiment.py
   :pyobject: Move.should_save
   :dedent:

Here, the record keeps no moves. What the analysis needs, the coins each
player collected and when, is in the state's ``collected``, which the
outcome holds. PsyNet's own
messages, such as each player's ready message, are always saved. A message that
isn't saved can't be recovered later, so decide what your analysis needs
before you leave anything out.

Reference: :ref:`live-games-saved-messages`.

Testing your game
-----------------

Run ``psynet test local`` in a demo's folder to play the experiment with
bots. The bots play each game through the game's ``bot`` method, as
`Bots`_ in Part 1 showed: the game asks each bot for its next message after
every change in a game without ticks, such as rock, paper, scissors, and on
every tick in a game with ticks, such as snake, whose bots head for the
nearest food. A group's bots have to reach the game together, so the demos
run their bots at the same time, with ``test_mode = "parallel"``, and set
``test_n_bots`` to a multiple of the group size:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: test_n_bots = 2
   :end-at: test_mode = "parallel"
   :dedent:

Each demo checks each bot's result at the end of the test. Rock, paper,
scissors checks that its last game finished and is its last trial's game, that
each of the bot's games had the number of throws in its trial's definition,
and that each trial's score and reward match the throws the bot won:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: Exp.test_check_bot
   :dedent:

``bot.live_games`` gives, for each ``PlayLiveGame`` the participant reached,
keyed by its ``id_``, which is the game's ``name`` unless given, the record of their latest game there, here their
second game: its ``end_reason``, its outcome, the participant's answer
and the game's messages. Snake's result page reads its player's answer the same way.

To test a game's rules without starting the experiment, play it in Python
with :class:`~psynet.live_game.testing.LocalGame`, which calls the game's
methods as PsyNet does. The demos' rule tests, such as
``tests/isolated/test_rock_paper_scissors_live.py``, do this:

.. code-block:: python

    game = LocalGame(RockPaperScissors, players=2, settings={"throws": 3, "reward_per_win": 0.10})
    game.send(0, Choose(throw=1, action="rock"))
    assert game.view(1)["partner_chosen"]

Reference: :ref:`live-games-bots`, which shows more of what ``LocalGame``
can do.

Bots don't run the page's JavaScript, so also play the game yourself, in a
browser window for each player. Try reloading the page during the game,
closing one player's window, and pressing keys before the game starts.

Your data
---------

Each game's record, with its outcome and every message it saved, goes into
the experiment's exported data (see :doc:`/data/exporting_data`). In Python,
a participant's ``live_games`` and a trial's ``live_game`` read it back, and
:ref:`live-games-record` describes what they hold and where Dallinger keeps
it.

Next steps
----------

:doc:`The reference <live_games>` describes everything a game can do, including what
happens when a player leaves, reloads, or opens the game in two tabs. The
``bargaining_live``, ``public_goods_live`` and ``microsociety_live`` demos
show more: re-pairing players between games, results on the group's round,
and one continuous game that players join while it runs and each leave in
their own time. Each demo's README describes its design, and Dallinger's
guide to `real-time games
<https://dallinger.readthedocs.io/latest/realtime_games.html>`__ describes
the engine that runs the games.

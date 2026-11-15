.. _live_session_tutorial:

====================
Building a live game
====================

This tutorial shows how to build a game that a group of participants play
together in real time. It works through three demos in PsyNet's
``demos/experiments`` folder. Apart from one short example, the code on
this page is included from the demos' files, so it's the code that runs. You
can run each demo, change it and see what happens.

``rock_paper_scissors_live``
    Two players play two games of rock, paper, scissors, of five and then
    three rounds. This demo has every part that a live game needs, so the
    tutorial covers it in the most detail.

``snake_live``
    Each player steers a snake around a shared board. The game moves the
    snakes by itself, eight times a second.

``shared_canvas_live``
    Players move around a canvas collecting coins, and each page draws
    everyone's movement smoothly.

Before you start, you should know how a PsyNet timeline is put together
(:doc:`/code/writing_a_timeline`), how trials work, and how participants
are put into groups (:doc:`synchronization`). The game pages are written in
JavaScript, so it helps if you have written a little of it.
:doc:`live_sessions` is the reference for everything shown here, and it
covers cases that this tutorial leaves out.

How a live game works
---------------------

In most PsyNet experiments, each participant works through the pages alone
and submits an answer on each one. In a live game, the members of a group are
on the same page at the same time, and what one player does shows up on the
other players' screens within a fraction of a second. Each group's game is
called a **session**.

The server runs the game. It keeps the game's **state**, which is everything
the game needs to know. In rock, paper, scissors, that's each player's choice
in the current round, the rounds played so far, and how many rounds each
player has won. The players' pages never change the state themselves:

- When the player does something, such as clicking "Rock", their page sends
  the game a **message**. The game checks the message against its rules. It
  then either changes the state or rejects the message, with a reason that
  the page can show.
- Whenever the state changes, the game sends each player's page a **view**,
  which is the part of the state that the player is allowed to see. The page
  draws the game from its view.

Because only the server changes the state, all the players see the same game,
and a participant can't change the result by editing their page. A page that
reloads gets the game as it stands. The server also saves the messages, with
the time each one arrived, so you can analyze what each participant did and
when. A game can leave some messages out of the record, as Part 3 shows.

You write the game as a Python class, a subclass of
:class:`~psynet.live_session.LiveSession`. Its methods say what the state is
at the start, what each message does, what each player sees, and when the
game is over. PsyNet does the rest. It connects the pages, applies the
messages one at a time in the order they arrive, sends the views, and saves
the record.

Part 1: Rock, paper, scissors
-----------------------------

In ``rock_paper_scissors_live``, pairs of participants play two games, the
first of five rounds and the second of three. Each player chooses rock, paper
or scissors, and once both have chosen, both see the result of the round.
Each round that a player wins pays them a bonus, which is larger in the
second game.

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
   :start-at: # The group type of the pairs
   :end-before: class Choose(LiveMessage):
   :dedent:

Each player is known by an id, which is their participant id as a string,
such as ``"12"``. ``partner_of`` finds the other player in a pair. ``Action``
is the type of a player's choice, which the message below uses for its
``action`` field, and ``ACTIONS`` lists the three choices, for the page's
buttons and the bots. ``GROUP``, ``GAMES`` and ``PARTNER_WAIT_SECONDS`` are
used by the timeline, which "Adding the game to the timeline" below
describes. The excerpts on this page leave out the file's imports, which are
at the top of the demo's ``experiment.py``.

The game and its state
~~~~~~~~~~~~~~~~~~~~~~

The game is the class ``RockPaperScissors``:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: class RockPaperScissors(LiveSession):
   :end-before: def initial_state(
   :dedent:

``channel`` is a name for the game, which must differ from the name of every
other game in the experiment. ``messages`` lists the kinds of message that a
page can send, which the next section describes. ``max_duration`` is a time
limit in seconds for the whole game, so that a game ends even if a player
walks away from it.

``initial_state`` returns the state at the start of the game. It receives the
ids of the session's players and the session's settings:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.initial_state
   :dedent:

The state is a dictionary. It can hold dictionaries, lists, strings, numbers,
``True``, ``False`` and ``None``, the same kinds of data that JSON can hold.
Here, each player's choice is ``None`` until they choose.

The settings are what differs from one session of the game to another. Here,
they say how many rounds the game has, and they come from the trial, as
"Adding the game to the timeline" below shows. The game's other methods
receive the state but not the settings, so ``initial_state`` puts what they
need into the state. A game that is always played the same way can leave
``settings`` out of ``initial_state``.

The message
~~~~~~~~~~~

A player makes a choice by sending a ``Choose`` message, a subclass of
:class:`~psynet.live_session.LiveMessage`:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: Choose
   :dedent:

``type`` is the name that the page uses when it sends the message.
``round`` and ``action`` are the message's fields, each with its type. A page
sends the message like this:

.. code-block:: javascript

    psynet.liveSession.send("choose", {round: 2, action: "rock"});

PsyNet checks every message against its fields before the game sees it. A
message whose ``round`` isn't a whole number, or whose ``action`` isn't one of
the three listed, is rejected, and ``apply`` never runs.

``apply`` runs for each message that passes the check. It receives the game,
which is the ``RockPaperScissors`` object that the next sections describe,
the state, the id of the player who sent the message, and the session time
``now``, which is the number of seconds since the pair left the initializer.
This ``apply`` needs only the state and the player's id. It changes the
state directly. Here, it records the player's choice, and once both players
have chosen, it scores the round and starts the next one.

``raise Reject("...")`` turns a message down. The state stays as it was
before the message, and the player's page receives the reason. The round
number in each message lets ``apply`` tell a click meant for this round from
a late one meant for a round that has already finished.

What each player sees
~~~~~~~~~~~~~~~~~~~~~

``view`` returns what one player's page shows:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.view
   :dedent:

The view says whether the partner has chosen in the current round, but not
what they chose. The partner's choice appears in ``results`` only once the
round is over. This is how a game keeps information private: whatever isn't
in a player's view never reaches their browser, so they can't find it by
looking at the page's code.

The end and the outcome
~~~~~~~~~~~~~~~~~~~~~~~

Two more methods say when the game ends and what its result is:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: def is_over(
   :end-before: def bot(
   :dedent:

The game checks ``is_over`` after every change to the state, and ends the
session as soon as it returns ``True``.

``outcome`` is the game's result, which is saved with the experiment's data.
It's also the game page's answer, so every player in the session gets the
same answer. ``reason`` says why the game ended. For example, it is
``"finished"`` when ``is_over`` ended the game, and ``"max_duration"`` when
the time limit did. The outcome includes the reason, so that later pages and
your analysis can tell a finished game from one that ended early. It also
includes the rounds each player won, which the trial below pays them for.

Bots
~~~~

``psynet test`` runs the experiment with bots, which don't run the page's
JavaScript. Instead, the game plays for them through its ``bot`` method:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissors.bot
   :dedent:

``bot`` receives the bot's view, and returns the message the bot sends next,
or ``None`` when the bot has nothing to do. Here, a bot that has already
chosen this round waits, and otherwise it chooses at random. The game calls
``bot`` again after every message, including the other bot's, until it
accepts no bot's message, so a bot that always sends an acceptable message
ends the session with an error. (In a game with ticks, as in Part 2, ``bot``
is called once per tick instead.)

Adding the game to the timeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In this demo, each game is a trial. The game's outcome is saved as the
trial's answer, like any other trial's, and what differs between the two
games is in the trial's definition: which game it is, how many rounds it has
and what a round won pays. The trial starts a session for the pair, shows the
game page, and then scores and pays for the game:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: RockPaperScissorsTrial
   :dedent:

- ``sync_group_type`` says that a group plays the trial, here the pair that
  the grouper in the timeline below forms. It is the same ``GROUP`` that the
  grouper and the initializer use. Each player has a trial of their own, and
  the two trials share a definition.
- The :class:`~psynet.live_session.LiveSessionInitializer` starts a session
  for each pair that reaches it, and the pair then moves on together. Its
  ``group_type`` is the pair's, its ``game_type`` is the game, and its
  ``settings`` are the number of rounds from the trial's definition, which
  the game's ``initial_state`` receives.
- A player whose partner doesn't arrive at the initializer within
  ``max_wait_time`` seconds leaves the pair, and goes on to the game page
  without a session. The wait starts when the player arrives, and their
  partner may still be reading the last game's result, so
  ``PARTNER_WAIT_SECONDS`` is five minutes. A partner who arrives later than
  that is treated the same as one who never arrives.
- The game page is a :class:`~psynet.modular_page.ModularPage`. Its prompt
  holds the page's elements, each with an ``id`` so that the JavaScript can
  find it. The first element says which game this is, how many rounds it has
  and what a round won pays, all from the trial's definition. The
  :class:`~psynet.live_session.LiveSessionControl` connects the
  page to the session that the initializer started, so its first argument is
  the initializer's ``id_``. ``player_left_message`` is the notice that the
  page shows while the partner is away from the game page, and
  ``no_session_message`` is the notice on a game page without a session.
- ``js_page_modules`` lists the page's JavaScript file, which is in the demo's
  ``static`` folder.
- The game page's answer is the game's outcome, which becomes the trial's
  answer. Each player has a trial of their own, so the outcome is saved once
  for each player.
- ``score_answer`` returns the trial's score, here the number of rounds the
  player won, which it reads from the outcome. ``compute_performance_reward``
  turns the score into the player's bonus, at the rate in the trial's
  definition. PsyNet saves both on the trial, as its ``score`` and
  ``performance_reward``, so the experiment's data shows what each game paid.
  A trial whose game page had no session has no answer, and scores 0.
- The participant can leave the game page only once the game is over, and the
  page then moves on by itself, to the trial's ``show_feedback`` page.
  ``gives_feedback`` leaves that page out for a trial without an answer.

A trial that a group plays needs a :class:`~psynet.sync.GroupBarrier` in its
``show_trial``, where the group's members wait for each other. The
initializer is one, so this trial needs no other. A group barrier in such a
trial closes the group's round when it releases the group, and here that is
when the game starts, not when it ends. Each trial's ``sync_group_outcome``
therefore says whether the player was in the pair when the game started. To
tell a game that was played to the end from one that a player abandoned, read
the ``reason`` in the outcome.

A game can also pay bonuses itself, through its ``bonus`` method, as the
snake demo in Part 2 does, or with ``queue_bonus``. Those are added to the
participant's reward but not to a trial's ``performance_reward``, so a game
that a trial shows is better paid by the trial.

The experiment's timeline forms the pairs, and then gives each player their
trials:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :start-at: class Exp(psynet.experiment.Experiment):
   :end-before: def test_check_bot(
   :dedent:

- The :class:`~psynet.sync.SimpleGrouper` puts participants into pairs. A
  participant who waits five minutes without a partner fails, and goes to the
  end of the experiment. To let them carry on without a partner instead, give
  the grouper ``max_wait_action="continue_without_group"``.
  ``below_quorum="continue_without_group"`` lets a participant carry on with
  the experiment after their partner has left the pair.
- The loop runs once for each game. ``RockPaperScissorsTrial.cue`` gives the
  participant a trial with the definition that it's passed, here the game's
  number, its rounds and what a round won pays. The loop value is also the
  ``round``, so the two players' trials for a game belong to the same round
  of the pair. :ref:`rounds-cued-trials` explains rounds.
- ``stop_if`` ends the loop for a participant who is no longer in a pair,
  because their partner didn't come back or left the experiment. PsyNet checks
  it before each game, never during one. The ``conditional`` after the loop
  then shows that participant a page that says why there are no more games:

  .. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
     :start-at: def left_pair(participant):
     :end-before: class Exp(psynet.experiment.Experiment):
     :dedent:

- The :class:`~psynet.timeline.Module` gives the trials a ``module_id``, which
  you can find them by in the experiment's data.
- ``test_n_bots`` and ``test_mode`` set up ``psynet test``. A pair's bots have
  to reach the initializer together, so the bots run in parallel.

The initializer and the game page can also go straight in the timeline,
without a trial, as they do in the snake and shared canvas demos.

The trial's ``show_feedback`` passes the trial's answer, and the bonus that
the trial paid, to ``show_result``:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: show_result
   :dedent:

A game can end before any round is played, when neither player opens the game
page in time, so ``show_result`` checks for that first.

The game page
~~~~~~~~~~~~~

The page's JavaScript is in ``static/rock-paper-scissors.js``. It exports an
``activate`` function, which PsyNet runs when the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules). Through
``psynet.liveSession``, the function sends the player's messages and draws each
view that arrives.

It checks that the participant has a session, then finds the page's elements
and sets up the variables that the rest of the page uses:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: export function activate
   :end-before: function enableButtons(
   :dedent:

A participant reaches the game page without a session when their partner
didn't arrive at the initializer in time. PsyNet then shows them the
control's ``no_session_message`` in a notice. The page hides the game, which
can't be played, and does nothing more, and its Next button lets them move
on.

The page then registers what happens when a view arrives, and when the game
rejects one of the player's messages:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: psynet.liveSession.onView(
   :end-before: for (let button of buttons) {
   :dedent:

``onView`` runs its callback each time a new view arrives, including the
final view once the game is over. It draws ``predictedView()``, which
"Showing a choice at once" below explains. ``onRejected`` runs with the
reason for each rejected message. The page shows the reason in an element of
its own, which ``render`` clears when a new round starts. A rejection arrives
just before the view that follows it, and that view can be the next round's,
so the ``rejectedNow`` flag stops it from clearing the reason at once.

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
   :end-before: psynet.liveSession.onView(
   :dedent:

``send`` returns ``undefined`` if the page's connection has closed, so the
page clears the last rejection only for a message that was sent.

``render`` draws the page from a view:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: function render(view) {
   :end-before: function choose(action) {
   :dedent:

The view holds every round played so far, so a page that reloads draws the
whole game again. ``describe``, defined above ``render`` in the file, puts a
round's result into words, and ``enableButtons`` enables or disables the
three buttons. ``psynet.liveSession.started`` says whether the game has
started, which it does once both players have the page open, or after a
minute if one of them doesn't open it. ``psynet.liveSession.ended`` says
whether the game is over. The buttons are enabled only while the game is
running and the player hasn't chosen yet. If the game fails with an error,
the final view can be ``null``, so ``render`` checks for that first.

Showing a choice at once
~~~~~~~~~~~~~~~~~~~~~~~~

A view usually arrives within a fraction of a second of the player's click.
But sometimes a view that the partner's choice caused arrives first, and that
view doesn't include the player's own choice yet. Drawn as it is, it would
enable the buttons again for a moment. The page avoids this by telling
``psynet.liveSession`` what a ``Choose`` message will do to the view:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/static/rock-paper-scissors.js
   :language: javascript
   :start-at: psynet.liveSession.predict(
   :end-before: function describe(
   :dedent:

``predictedView()`` then returns the latest view with this change applied
for each of the page's messages that the game hasn't applied yet. That's why
``render`` is called with ``predictedView()`` rather than the view itself.
Many games don't need this. The snake demo below draws each view as it
arrives.

Part 2: Snake
-------------

In ``snake_live``, each player in a group steers a snake around a shared board
for 60 seconds. ``GROUP_SIZE`` in the demo's ``experiment.py`` sets how many
play together, from 2 to 4, and it's 2 unless you change it. A snake grows
each time it eats a piece of food. If it hits a wall or any snake, it crashes
and comes back two seconds later somewhere else. Each piece of food eaten pays
a bonus.

Rock, paper, scissors changes only when a player sends a message. In snake,
the snakes keep moving whether or not anyone presses a key, so the game has
to change the state by itself, on a clock.

Run it with ``--legacy``:

.. code-block:: console

    cd demos/experiments/snake_live
    psynet debug local --legacy

Then open the participant link in a browser window for each player.

``--legacy`` runs gunicorn, the web server that deployed experiments use. The
development server that ``psynet debug local`` runs by default sometimes
delivers views late, which makes the snakes pause.

Ticks
~~~~~

The game class sets how often the game ticks:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :start-at: class Snake(LiveSession):
   :end-before: def initial_state(
   :dedent:

``tick_rate = 8`` makes the game **tick** eight times a second. On each tick,
the game's ``tick`` method runs, and then every player's page gets a new
view. ``send_views_on_messages = False`` stops the game from also sending the
player a view after each of their messages, since a turn doesn't change the
board until the next tick.

``max_duration`` counts from when the group left the initializer. Before the
game starts, there's a **ready step**, while the players' pages open. The game
starts once every player's page is open, or after ``ready_timeout`` seconds
(60 unless the game sets it). So ``max_duration`` allows for the longest ready
step, the round itself, and 30 seconds to spare.

The game sets its deadline when it starts, and ends once the deadline has
passed:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :start-at: def on_start(
   :end-before: def view(
   :dedent:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: Snake.is_over
   :dedent:

``on_start`` runs once, when the game starts. ``now`` is the session time in
seconds, as in a message's ``apply``. The deadline goes in the state,
because everything about a session has to. Don't keep it on ``self``: one
game object plays many sessions, and a session can move to another process.

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

On each tick, ``tick`` calls ``move_snakes``:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: move_snakes
   :dedent:

It moves every snake before it works out any crashes. If it moved one snake
and checked it, then moved the next, the snakes moved first would get the
contested squares. When you design a game for an experiment, look for rules
like this, where the order in which the server deals with players could
favor some of them.

The bonus
~~~~~~~~~

Snake isn't played in a trial, so the game pays the bonus itself, through its
``bonus`` method:

.. literalinclude:: ../../../demos/experiments/snake_live/experiment.py
   :pyobject: Snake.bonus
   :dedent:

``bonus`` works out each player's bonus from the game's outcome, which is why
the outcome includes how much food each snake ate. PsyNet adds the bonus to
the player's performance reward when they leave the game page.

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
``live`` is short for ``psynet.liveSession``:

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

``view.me`` is the player's own id, so their snake is
``view.players[view.me]``.

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

The time left comes from the session time on the page,
``live.socket.sessionTime()``, which counts the same seconds as ``now`` on the
server:

.. literalinclude:: ../../../demos/experiments/snake_live/static/snake.js
   :language: javascript
   :start-at: function showStatus(view) {
   :end-before: // The game moves every snake on its ticks
   :dedent:

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
so ``apply`` charges each move against the session clock. However many moves
a page sends, its player can't move faster than the rules allow. The general
point is that a message is a request from the participant's browser, which
they control, so the game should check anything that matters to the result.

Smooth movement on the page
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The game ticks 20 times a second. Drawn as it arrives, each tick's view would
make the players jump a little at each tick, and the player's own piece would
lag a fraction of a second behind their key presses. The page avoids both:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/static/shared-canvas.js
   :language: javascript
   :start-at: live.predict((view, type, message) => {
   :end-at: live.interpolate(interpolate);
   :dedent:

``predict`` works as in rock, paper, scissors. Here, it moves the player's
own piece at once, using ``advance``, which repeats the arithmetic of the
game's own ``advance`` in ``experiment.py``. ``interpolate`` takes the views
of two ticks and returns a view part of the way between them:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/static/shared-canvas.js
   :language: javascript
   :start-at: // Places each player between two tick views.
   :end-before: function drawCircle(
   :dedent:

The page draws about 60 times a second. Each time, it draws the player's own
piece from ``live.predictedView()``, moved on by the movement that the page
hasn't sent yet, which the demo's ``shownView`` function adds. It draws the
other players from ``live.interpolatedView()``, which shows them a little in
the past, moving smoothly between two ticks.

Saving fewer messages
~~~~~~~~~~~~~~~~~~~~~

By default, the session's record keeps every message. With 30 moves a second
from each moving player, that's a lot of data that the analysis may not
need. The game's ``save_message`` decides which messages to keep:

.. literalinclude:: ../../../demos/experiments/shared_canvas_live/experiment.py
   :pyobject: SharedCanvas.save_message
   :dedent:

Here, the record keeps only the moves that collected a coin. A message that
isn't saved can't be recovered later, so decide what your analysis needs
before you leave anything out.

Testing your game
-----------------

Run ``psynet test local`` in a demo's folder to play the experiment with
bots. Each demo checks each bot's result at the end of the test. Rock, paper,
scissors checks that each of the bot's games had the number of rounds in its
trial's definition, and that each trial's score and bonus match the rounds
the bot won:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors_live/experiment.py
   :pyobject: Exp.test_check_bot
   :dedent:

:func:`~psynet.live_session.live_session_id` finds the session that a
participant last played at an initializer, here their second game, and
:func:`~psynet.live_session.live_session_result` says how it ended and what
its outcome was. To test a game's rules without starting the experiment, call
its methods directly, as the "Bots and testing" section of
:doc:`live_sessions` shows.

Bots don't run the page's JavaScript, so also play the game yourself, in a
browser window for each player. Try reloading the page during the game,
closing one player's window, and pressing keys before the game starts.

Your data
---------

Each session's record is saved with the experiment's data, in Dallinger's
``realtime_session`` and ``realtime_event`` tables. ``realtime_session`` holds
each session's outcome and final state. ``realtime_event`` holds the
session's events. Most are saved messages, from pages and bots, each with
the participant who sent it and whether the game accepted it. Its
``event_type`` column tells these apart from other events, such as the
session's end. For each message, the table records when it arrived, both as
a date and time and as a session time. It also records the time on the
participant's own computer when their page sent the message, and the session
time of the view the participant was looking at when they acted. The "Saved
messages" section of :doc:`live_sessions` shows how to read a session's
messages in Python.

Next steps
----------

:doc:`live_sessions` describes everything a game can do, including what
happens when a player leaves, reloads, or opens the game in two tabs. Each
demo's README describes its design, and Dallinger's guide to `real-time games
<https://dallinger.readthedocs.io/latest/realtime_games.html>`__ describes the
engine that runs the games.

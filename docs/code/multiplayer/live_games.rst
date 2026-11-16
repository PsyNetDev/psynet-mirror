.. _live_games:

==========
Live games
==========

A live game is one that a group of participants play together in real time,
such as a negotiation, a coordination game or a game on a shared board. The
server keeps one state for the whole group, applies each player's messages
to it in the order they arrive, and sends each player's page its own view of
the game. Each game a group plays, with its messages, is saved with the
experiment's data.

If you haven't built a live game before, start with the
:doc:`tutorial <live_game_tutorial>`, which works through three demo
games.

A live game has three pieces:

1. The game, a subclass of :class:`~psynet.live_game.LiveGame`, with a
   :class:`~psynet.live_game.LiveMessage` subclass for each kind of
   message a page can send.
2. The game page, a :class:`~psynet.modular_page.ModularPage` with a
   :class:`~psynet.live_game.LiveGameControl`, and a JavaScript file
   that plays the game through ``psynet.liveGame``.
3. A :class:`~psynet.live_game.PlayLiveGame` in the timeline, which
   makes each group that reaches it wait for its members, starts a game for
   the group, and then shows them the game page.

The game
--------

A game of rock, paper, scissors:

.. code-block:: python

    import random
    from typing import Literal

    from psynet.live_game import LiveGame, LiveMessage


    class Choose(LiveMessage):
        type = "choose"
        action: Literal["rock", "paper", "scissors"]

        def apply(self, game, state, player, now):
            state["choices"][player] = self.action


    class RockPaperScissors(LiveGame):
        channel = "rock_paper_scissors"
        messages = [Choose]
        min_players = max_players = 2

        def initial_state(self, players):
            return {"choices": [None, None]}

        def view(self, state, player):
            return {"chosen": state["choices"][player] is not None}

        def is_over(self, state):
            return None not in state["choices"]

        def bot(self, view, player, now):
            if view["chosen"]:
                return None
            return Choose(action=random.choice(["rock", "paper", "scissors"]))

``channel`` names the game, and ``messages`` lists the kinds of message its
pages can send. ``Choose`` is one: its ``type`` is the name a page sends it
under, its fields are the message's contents, and its ``apply`` says what the
message does to the state. Then the game's methods:

- ``initial_state`` returns the state at the start of the game, a dict.
- ``view`` returns what one player's page shows, also a dict. Whatever isn't
  in a player's view never reaches their browser, so the view is how a game
  keeps information private.
- ``is_over`` says when the game has ended.
- ``bot`` plays for bots, as in ``psynet test`` (see `Bots and testing`_).

The players are numbered from 0 in the order they signed up, which is
participant id order, and each method gets the player's number as
``player``. ``initial_state`` gets the list of numbers, such as ``[0, 1]``.
So the state keeps what each player has in a list, in player order, and in a
game for two, ``1 - player`` is the other player. Code outside the game
rarely needs the numbers: the game's ``answer`` gives each player their own
part of the outcome (see `The answer`_).

``now``, in ``apply``, ``bot`` and the game's other methods, is the time in
seconds since the game started.

A game can also have a clock that ticks, an outcome and more, which come
from Dallinger's :class:`~dallinger.realtime.RealtimeGame`. For a game that
lasts a fixed time, see `How long a game lasts`_. Dallinger's guide to
`real-time games <dallinger-realtime-games_>`_ explains them, and its `API
reference <dallinger-realtime-api_>`_ describes each method and setting that
comes from ``RealtimeGame``.

PsyNet adds each game to the experiment's ``realtime_games`` itself, so you
don't list it there. It adds every game that Python has loaded, whether or
not the timeline plays it. That includes a game in a module you import from
another experiment, so give every game a channel of its own.

Messages and the state
----------------------

PsyNet checks each message before its ``apply`` runs, and rejects one with a
field missing, an extra field, or a field of the wrong type. The sender's page
gets the reason. The check is strict: ``"1"`` isn't accepted as a number, nor
``1`` as text, and no number in the message can be ``NaN`` or infinite. A
message's ``apply`` can turn the message down too, by raising
:class:`~dallinger.realtime.Reject` with a reason, such as for a move that's
against the rules. The state then stays as it was, and the sender's page gets
the reason.

A field can have any type Pydantic reads from JSON, such as a ``tuple``, an
``Enum``, a ``datetime`` or another Pydantic model, and in ``apply`` it holds
a value of that type. The state, though, holds only plain data: dicts with
string keys, lists, strings, numbers, booleans and ``None``. PsyNet converts
anything else when ``initial_state`` returns, and after a message's ``apply``
or the game's ``tick``, ``on_join``, ``on_leave`` or ``on_start`` runs:

- a tuple becomes a list, and so does a set, in no fixed order, so store
  ``sorted(...)`` where the order matters
- an enum member becomes its value, and a Pydantic model a dict
- a date, time, datetime or timedelta becomes a string such as
  ``"2026-11-02T09:30:00"`` or ``"PT1M30S"``, and so does a ``Decimal`` or
  ``bytes`` value

A dict key has to be a string already: a state with a key such as ``3`` makes
the game fail, because after a save the key would read back as ``"3"`` and
``state["scores"][3]`` would fail. That's why the state keeps what each
player has in a list rather than in a dict keyed by player. A value PsyNet
can't convert, such as an object of a class of your own, also makes the game
fail. So does ``math.inf`` or ``NaN``, which JSON can't hold, so store
``None`` instead. Because a field stored in the state is converted, compare
like with like:

.. code-block:: python

    from dallinger.realtime import Reject


    class Move(LiveMessage):
        type = "move"
        to: tuple[int, int]

        def apply(self, game, state, player, now):
            # The state holds a list, and a list never equals a tuple.
            if state["positions"][player] == list(self.to):
                raise Reject("You're already there.")
            state["positions"][player] = self.to

In the same way, compare an enum field's ``.value`` with the state, and turn
a stored date back into a datetime with
``datetime.fromisoformat(state["deadline"])``. A game with a very large
state, such as a big grid, can save the time the conversion takes with
:attr:`~psynet.live_game.LiveGame.convert_state_to_json`.

Starting games and the game page
--------------------------------

Put a :class:`~psynet.live_game.PlayLiveGame` after the
:class:`~psynet.sync.Grouper` that forms the groups, and give it the game
page. It waits at a barrier, a :class:`~psynet.sync.GroupBarrier` for the
group's ``group_type``, until all of a group's members reach it, starts a
game, and then shows the group the game page:

.. code-block:: python

    timeline = Timeline(
        SimpleGrouper(group_type="pair", initial_group_size=2),
        PlayLiveGame(
            group_type="pair",
            game_class=RockPaperScissors,
            page=ModularPage(
                "rock_paper_scissors",
                Prompt(
                    tags.div(
                        tags.p(id="status"),
                        tags.p(id="rejection"),
                        tags.button("Rock", type="button", id="rock"),
                        tags.button("Paper", type="button", id="paper"),
                        tags.button("Scissors", type="button", id="scissors"),
                    )
                ),
                LiveGameControl(),
                js_page_modules=["/static/rock_paper_scissors.js"],
                time_estimate=30,
            ),
        ),
        ...
    )

The game page plays the game that this ``PlayLiveGame`` started, so give
each ``PlayLiveGame`` a page of its own. Its ``id_`` is the game's
``channel`` unless you give one. Steps with the same id share their wait,
like barriers with the same id, so a game that the timeline plays in two
places, such as a practice game and the main game, needs a different
``id_`` in each.

A game needs at least ``min_players`` players, 2 unless the game sets it. A
group that reaches the ``PlayLiveGame`` with fewer active members, for example
because the others left it while it waited, starts no game, and its members'
game pages show the no-game notice (see `Cases a game page should allow
for`_). Set ``min_players = 1`` for a game a player can play alone.

A game made for a fixed number of players, such as a game for two, or one
with something for each player that runs out, such as a color, sets
``max_players``. A larger group is a mistake in the experiment's design, so
it starts no game either, and PsyNet logs an error that says so. Make the
grouper's groups no larger than the game allows.

``PlayLiveGame`` takes the options of a :class:`~psynet.sync.GroupBarrier`,
such as ``max_wait_time``, for its barrier. Its ``on_release`` runs when the
wait ends and the group's game has been created, with the arguments a group
barrier's ``on_release`` takes and also ``live_game_id``, which is ``None``
if the group started no game. Use it for group bookkeeping at the start of a
round, such as choosing who leaves after it.

To play one game under different conditions, such as with a different
number of rounds, pass ``PlayLiveGame`` ``settings``: a dict, or any other
value that can be saved as JSON. The game's ``initial_state`` gets it as a
second argument, and keeps what the game's other methods need in the state,
since they get only the state. Here and below, ``rock_paper_scissors_page()``
returns a new game page like the one above:

.. code-block:: python

    PlayLiveGame(
        group_type="pair",
        game_class=RockPaperScissors,
        page=rock_paper_scissors_page(),
        settings={"rounds": 3},
    )


    class RockPaperScissors(LiveGame):
        def initial_state(self, players, settings):
            return {"n_rounds": settings["rounds"], "choices": [None, None], ...}

To vary the settings from trial to trial, return a ``PlayLiveGame`` from a
trial's ``show_trial``, and pass the trial's ``definition`` as the settings:

.. code-block:: python

    class RockPaperScissorsTrial(StaticTrial):
        sync_group_type = "pair"

        def show_trial(self, experiment, participant):
            return PlayLiveGame(
                group_type="pair",
                game_class=RockPaperScissors,
                page=rock_paper_scissors_page(),
                settings=self.definition,
            )

Every member of a group has to arrive with the same settings: a member
whose settings differ from those of the members already waiting gets an
error that says so. Trials that a group plays in one round share a
definition, so set ``sync_group_type`` on the trial class and cue one trial
per player (see :ref:`rounds-cued-trials`). The ``bargaining_live`` demo
draws each pair's stake this way, with a function as the definition that
``cue`` calls once for the pair.

A trial played in a group needs a :class:`~psynet.sync.GroupBarrier` in its
``show_trial``, and the barrier of the ``PlayLiveGame`` is one. The round's
:attr:`~psynet.sync.SyncGroupRound.live_game_id` then names the game the
group played in it, so ``trial.group_round`` leads from each trial to its
round's game, for example in an export.

The page's JavaScript goes in a file in the experiment's ``static`` folder,
listed in the page's ``js_page_modules``. It exports an ``activate``
function, which PsyNet runs each time the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules).
``static/rock_paper_scissors.js``:

.. code-block:: javascript

    export function activate({root, psynet}) {
        let status = root.querySelector("#status");
        if (!psynet.liveGame.hasGame) {
            return;
        }
        let buttons = ["rock", "paper", "scissors"].map(
            (action) => root.querySelector("#" + action)
        );
        psynet.liveGame.enableWhilePlaying(...buttons);
        psynet.liveGame.onView((view) => {
            if (psynet.liveGame.ended) {
                status.textContent = "The game is over.";
            } else if (!psynet.liveGame.started) {
                status.textContent = "Waiting for your partner to arrive";
            } else {
                status.textContent =
                    view.chosen ? "Waiting for your partner" : "Your turn";
            }
        });
        psynet.liveGame.onRejected((number, reason) => {
            root.querySelector("#rejection").textContent = reason;
        });
        for (let button of buttons) {
            button.addEventListener("click", () => {
                root.querySelector("#rejection").textContent = "";
                psynet.liveGame.send("choose", {action: button.id});
            });
        }
    }

``psynet.liveGame`` offers:

Whether there's a game to play:

- ``hasGame`` says whether the group started a game at the
  ``PlayLiveGame``. Without one, PsyNet shows the participant a notice, and
  the other methods throw an error. Check it first.
- ``started`` says whether the game has started, and ``ended`` whether it
  has ended. In ``onView``, both are already up to date for the view. On a
  page that opens after the end, ``started`` stays ``false``, so check
  ``ended`` first. ``playing`` says whether it has started and not ended,
  for a check such as before sending a key press.
- ``player`` is this player's number, as the game's methods see it, from
  the page's first view.

Time:

- ``gameTime()`` returns the seconds since the game started, the same clock
  as ``now`` in the game's methods, or ``null`` before the game starts.
  Compare it with a time the game put in the view, such as when a crashed
  player comes back.
- ``duration`` is the game's ``duration`` in seconds, and ``secondsLeft()``
  the seconds until it ends, 0 once the game has ended. Both are ``null``
  before the game starts or for a game without a ``duration`` (see `How long
  a game lasts`_).
- ``showResultFor`` is the control's ``show_result_for``, for a countdown
  while the page shows the result (see "The end" below).

Sending messages:

- ``send(type, message)`` sends the game a message, and returns its number,
  or ``undefined`` once the page's connection is closed or refused.
- ``onRejected(callback)`` calls ``callback`` with the number of each message
  the game rejected and the reason. The view that follows comes straight
  after, so show the reason somewhere ``onView`` doesn't overwrite, as the
  example does.
- ``enableWhilePlaying(...elements)`` enables the elements, such as
  buttons, only while the game is played: they are disabled until it
  starts, and again once it ends.

Views:

- ``onView(callback)`` calls ``callback`` with each new view, what the game's
  ``view`` returns for this player, ending with the final view. A page that
  opens after the game has ended gets just the final view.
- ``predict(callback)`` and ``predictedView()`` show the player's own
  messages at once. ``callback(view, type, message, sentAt)`` changes a view
  as the game will once it applies the message, and ``predictedView()``
  returns the newest view with the page's messages that the game hasn't
  applied yet applied by ``callback``. Draw from it in ``onView`` and after
  ``send``. ``sentAt`` is the game time when the page sent the message
  (``null`` if it wasn't known yet), and stays the same each time the
  callback runs again for a new view, so use it to predict when something
  happens, such as when a boat that is moving arrives.
  Without it, a view that arrives just after the player's move, such as one
  the partner's move caused, doesn't show that move yet.
- ``interpolate(callback)`` and ``interpolatedView()`` show other players
  moving smoothly, in a game whose ``tick_rate`` is above 0.
  ``callback(a, b, fraction)`` returns a new view part of the way between two
  tick views. Unlike ``predict``'s callback, it must leave ``a`` and ``b``
  unchanged, since they're the tick views the page keeps.
  ``interpolatedView()`` returns the game two tick intervals in the past,
  between the tick views either side of that time. Call it each time the page
  draws, and draw the player's own piece from ``predictedView()``. Without it,
  other players jump from one tick to the next.

Events in the game:

- ``onStarted(callback)`` calls ``callback`` with the first view once the
  game has started, or at once if it already has. A page that opens after
  the game has ended gets ``onEnded`` instead.
- ``onEnded(callback)`` calls ``callback`` once the game ends, with why it
  ended and the player's final view, which ``onView`` has already had.
- ``onPlayersAway(callback)`` calls ``callback`` with the numbers of the
  players who have left the game page and not come back (see "Joining and
  leaving" below).
- ``onResultSaved(callback)`` and ``onRefused(callback)`` call ``callback``
  once the game's result is saved, or with the close code and reason if
  the server refuses the page's connection. Either way, the page then moves
  on by itself (see "The end" below).

Anything else:

- ``socket`` is the page's Dallinger socket, such as for ``serverTime``.

The page leaves the game when the participant moves on, so ``activate``
doesn't need to return a cleanup function for it.

Cases a game page should allow for
----------------------------------

No game
    A participant can reach the page without one, for example when the
    ``max_wait_action="leave_group"`` of the ``PlayLiveGame`` took them out
    of a group whose other members were too slow to arrive, or when their
    group ended before they reached the ``PlayLiveGame``. PsyNet tells the
    participant with a notice at the top of the page, "Your group couldn't
    start the game.", which the control's ``no_game_message`` changes or
    turns off. The page's JavaScript should check
    ``psynet.liveGame.hasGame`` first, as above, and do nothing more
    without a game.

Joining in time
    The page joins the game when its JavaScript first uses
    ``psynet.liveGame``, so call ``onView`` in ``activate``. If none of the
    group has opened the page within the game's ``join_timeout`` of the wait
    ending, 60 seconds unless the game sets it, the game ends with the reason
    ``"not_joined"``.

Rejected messages
    A message is rejected when one of its fields is missing or of the wrong
    type, which is usually a mistake in the page's JavaScript, or when the
    message's ``apply`` raises ``Reject``, such as for a move out of turn. Show
    the participant the reason, or match the number ``send`` returned.

The end
    ``onView`` gets the final view with ``ended`` set, and ``onEnded`` runs,
    and the game ignores any message sent after that. If the game fails,
    the final view can be ``null``. The example reads the view only before
    the end, so it allows for that.

    The participant can leave the page only once the game's result is
    saved, a few seconds after the game ends, and the page then moves on by
    itself. Until then its Next button is hidden. A participant without a
    game still sees it, so they can move on. So does a participant whose
    page has been disconnected for ten seconds: if they click it, the page
    says the game isn't over yet and moves on once the result is saved. The
    page also moves on if the server refuses its connection, as it does when
    the participant reloads the page long after the game ended.

    To show the result on the game page first, pass the seconds to show it
    for as the control's ``show_result_for``, such as
    ``LiveGameControl(show_result_for=8)``, and draw the result in
    ``onResultSaved``. The page moves on once the seconds are up, and
    ``psynet.liveGame.showResultFor`` gives them to the page for a
    countdown. A later :class:`~psynet.sync.GroupBarrier`'s ``late_after``
    counts from the end of these seconds, so it needn't cover them.

    To move on from the page's JavaScript instead, pass ``auto_advance=False``
    to the control, and call ``psynet.nextPage()`` in both ``onResultSaved``
    and ``onRefused``. The Next button then stays, and if the participant
    clicks it before the result is saved, the page says the game isn't over
    yet and sends the response again every second until it's accepted. If you
    hide the Next button with ``show_next_button=False``, give a page without
    a game another way to move on, such as a button of its own that calls
    ``psynet.nextPage()``.

Joining and leaving
    The game's ``on_join`` runs when a player opens a page in the game while
    none of theirs is open, and ``on_leave`` runs when their last one closes,
    so a participant who closes the page during the game leaves it. The game
    carries on without them unless ``on_leave`` ends it. Before the game
    starts, both get ``None`` as ``now``.

    While a player is away for more than a few seconds, the other players'
    pages show a notice at the top that says "Another player has left the
    game." Change it with the control's ``player_left_message``, such as
    ``LiveGameControl(player_left_message="Your partner has left.")``. To
    show it your own way, set ``player_left_message=None`` and use
    ``onPlayersAway``, which gets the numbers of the players who are away,
    and an empty list once they're all back. The notice only says what
    happened: a game that should end when a player leaves still ends in its
    ``on_leave`` or ``is_over``.

Reloading and dropped connections
    The page reconnects by itself, rejoins and gets the game as it stands,
    and messages sent while it was down go then. A reload usually runs
    ``on_leave`` and then ``on_join``, so an ``on_leave`` that ends the
    game also ends it when a player reloads. A page reloaded within an
    hour of the game ending gets the ending at once. After that, the
    server refuses the connection.

Another tab
    The same page open in another tab plays as the same player. When the
    game's result is saved, both tabs try to move on. One of them does,
    and in the other PsyNet asks the participant to close their other tabs
    and refresh the page.

The ready step
--------------

Between the end of the wait and the start of the game, PsyNet waits a moment
for the players' pages, so that a page that opens a little after the others
doesn't miss the start. A game page says its player is ready by itself a
moment after it opens, and a bot is ready at once. The game starts once every
player is ready, or at the game's ``ready_timeout``, 60 seconds after the
wait ended unless the game sets it, and players who aren't ready then can
still join and play. A player whose page closes before the game starts isn't
ready any more, until the page reconnects.

Until the game starts, it rejects messages with the reason ``"The game
hasn't started yet."``, and its ``tick`` and ``bot`` don't run, so disable
the page's controls with ``enableWhilePlaying``, as above, check
``playing``, or wait for ``onStarted``. The game's clock, ``now`` in its
methods, starts at 0 when the game starts, and the game's ``on_start`` runs
then. The game's other methods can run before it starts: ``on_join``,
``on_leave``, ``view``, ``is_over``, and ``outcome`` if the game ends before
it starts.

The messages that say a player is ready are PsyNet's, so a message's
``apply`` never receives them. To show who is ready, read
``state["psynet"]["ready"]`` from the view (see `PsyNet's entry in the
state`_).

How long a game lasts
---------------------

A game that lasts a fixed time sets ``duration``, in seconds. PsyNet runs
the game's ``tick`` at the end, if it has one, and then ends the game with
the reason ``"finished"``, unless the game's ``is_over`` ended it earlier.
This version of the game gives the pair 10 seconds to choose:

.. code-block:: python

    class TimedRockPaperScissors(RockPaperScissors):
        channel = "timed_rock_paper_scissors"
        duration = 10

Messages that arrive from then on are rejected with the reason ``"The
game's time is up."``. The page shows the time left with
``psynet.liveGame.secondsLeft()``, which is 0 once the game has ended,
and ``psynet.liveGame.duration``:

.. code-block:: javascript

    setInterval(() => {
      let left = psynet.liveGame.secondsLeft();
      if (left !== null) {
        bar.style.width = `${(left / psynet.liveGame.duration) * 100}%`;
      }
    }, 250);

A game that ends by itself, through its ``is_over``, has a ``timeout``
instead, in case it doesn't end: participants can't leave the game page until
the game ends. A game still running ``timeout`` seconds after it started, 10
minutes unless the game sets it, ends with the reason ``"timeout"``, and
rejects messages from then on. ``timeout = None`` removes the limit, so set
it only if the game always ends by itself, even when players leave. A game
with a ``duration`` ends then, so its ``timeout`` doesn't apply.

For other deadlines, such as one for each move, a game returns the next one,
in seconds since the game started, from ``next_deadline``. Its ``tick`` runs
at each one, and at the end of its ``duration``. A tick that runs late gets
the end as ``now``, so a game that counts things on a schedule, such as
catches every few seconds, counts none after the end.

If a game is still running more than a minute after it should have ended,
for example because the worker that runs the experiment's games has stopped,
its game page stops waiting: the participant sees PsyNet's error page, and a
bot fails with an error that names the game.

The game page also stops a later :class:`~psynet.sync.GroupBarrier` from
counting a player who is still in the game as late. ``late_after`` counts from
the group's previous barrier, which is usually the barrier of a
``PlayLiveGame``, so it would otherwise include the whole game. Instead, as
for a page with a ``time_limit``, it counts from when the game page ends: at
first the latest the game could end, plus a minute, and once the game's
result is saved, when the game actually ended, plus the control's
``show_result_for``. So ``late_after`` needs to cover only the pages after the
game.

PsyNet's entry in the state
---------------------------

PsyNet keeps its own record of the game in ``state["psynet"]``, and adds
the same entry to each view. Don't use the name ``psynet`` for anything else
in the state or a view. The parts a game can use are:

- ``participant_ids``, each player's participant id, in player order
- ``ready``, the numbers of the players who are ready
- ``away``, the numbers of the players who have left the game page and not
  come back. A player who hasn't opened it yet isn't in it.
- in a view, ``you``, the number of the player it's for, which the page
  reads as ``psynet.liveGame.player``

The entry's other parts, such as ``started_at``, are PsyNet's timekeeping,
on Dallinger's clock rather than the game's. Use ``now`` and the page's
``gameTime()`` instead.

The answer
----------

The game page's answer comes from the game's outcome: what the game's
``outcome`` method returned when the game ended. PsyNet sets it on the
server and ignores what the page sends, and a participant without a game
gets ``None``. By default, every player's answer is the whole outcome. Define
``answer(outcome, reason, player)`` to give each player only their own
part, so that a trial holds only its player's data and code reading
``trial.answer`` needs no player numbers:

.. code-block:: python

    class RockPaperScissors(LiveGame):
        ...

        def outcome(self, state, reason):
            return {"choices": state["choices"]}

        def answer(self, outcome, reason, player):
            choices = outcome["choices"]
            return {"mine": choices[player], "theirs": choices[1 - player]}

Results that belong to the whole group, such as a team's total, stay in the
outcome. The ``rock_paper_scissors_live``, ``snake_live`` and
``shared_canvas_live`` demos each define an ``answer``.

When the game is played as a trial (see `Starting games and the game
page`_), PsyNet copies the outcome to the round the game was played in once
the game's result is saved, so later pages and the export read it as
``trial.group_round.live_game_outcome``, with no need for another barrier
after the game page to score the round:

.. code-block:: python

    pot = trial.group_round.live_game_outcome["pot"]

It is ``None`` until then, and ``answer`` isn't called, for a game that
failed without an outcome.

Rewards
-------

A game can add to each player's performance reward in two ways. Each amount
must be a number of 0 or more. For a reward based on the outcome, define
``performance_reward(outcome, reason, player)`` to return the player's
reward. PsyNet pays it to each player once, when the game's result is saved,
however the game ended, so a player who left the game page early is paid
too. This game pays 0.10 for a win:

.. code-block:: python

    BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


    class RockPaperScissors(LiveGame):
        ...

        def performance_reward(self, outcome, reason, player):
            choices = outcome["choices"]
            mine, theirs = choices[player], choices[1 - player]
            return 0.10 if mine is not None and BEATS[mine] == theirs else 0

``reason`` is ``"finished"`` when ``is_over`` ended the game or its
``duration`` ran out, and ``"timeout"`` when its ``timeout`` did.
Dallinger's `outcome <dallinger-outcome_>`_ lists the other reasons, such as
``"not_joined"``. If the game's code raised an error, ``reason`` is
``"failed"``, and ``outcome`` is the outcome of the state just before the
error.

For a reward earned during the game, such as for each coin a player collects,
call ``game.add_performance_reward(player, amount)`` in a message's
``apply`` or in another method that changes the state. PsyNet adds it to the
player's reward a few seconds later, so the player keeps it even if they
leave early.

When the game is played as a trial, PsyNet also records both kinds of
reward on the player's trial, adding them to its ``performance_reward``, so
each trial shows what its game paid. A trial can pay through its own
``score_answer`` and ``compute_performance_reward`` instead, as the
``rock_paper_scissors_live`` demo does, when what a game pays depends on the
trial's definition. The trial's reward is then added to the game's, so a
game whose trial pays defines no ``performance_reward``, or the player is
paid twice.

A game can fail without an outcome: its record couldn't be saved, or the
game's ``outcome`` raised an error as well. The answer is then ``None`` and
PsyNet doesn't call ``performance_reward``, but amounts from
``add_performance_reward`` saved before the problem are still paid. A game
that must pay players whatever happens can pay them as it goes.
:func:`~psynet.live_game.live_game_result` says how a game ended, and
whether its record is complete.

Saved messages
--------------

Each game's record is saved with the experiment's data, in Dallinger's
``realtime_session`` and ``realtime_event`` tables: the game's outcome and
final state, and each message a page sent, with whether the game accepted it.
To read a game's messages in Python, call ``saved_messages`` on the game,
for all of them, or on a message type, for that type's. On a later page:

.. code-block:: python

    game_id = live_game_id(participant, "rock_paper_scissors")
    if game_id is not None:
        for saved in Choose.saved_messages(game_id):
            if saved.message is not None:
                print(saved.player, saved.message.action, saved.time)

``live_game_id`` finds the game from the participant's latest visit to the
``PlayLiveGame`` with that ``id_``, or returns ``None`` if their group didn't
start one. In an analysis, use the round's record instead: for a game played
in a trial, each :class:`~psynet.sync.SyncGroupRound` keeps its game's
``live_game_id``. For other games, ``realtime_sessions_for(participant,
game_type)`` from ``dallinger.realtime`` returns all of a participant's games
of one kind, and each one's ``id`` is its game's id.

Each message is a :class:`~psynet.live_game.SavedMessage`, in the order the
game applied them, with the sender's ``player`` number and ``participant_id``,
and its ``time`` in seconds since the game started, negative for a message
that arrived before the start. Its ``message`` is ``None`` if what the page
sent can't be read as one of the game's message types, and its ``payload``
holds what the page sent. ``PlayerReady.saved_messages(game_id)`` says when
each player became ready.

The record is written a few seconds behind the game, so while a game is
still running, ``saved_messages`` returns only the messages written so far.
By the page after the game page, the whole record has been written, unless
``live_game_result(game_id).record_complete`` says that saving it failed.

A game saves every message by default. A game whose pages send many
messages, such as a move on every key press, can leave some out with the
message type's ``should_save``, which returns ``False`` for a message to
leave out. It runs after the game has accepted or rejected the message, on
the same message object that ``apply`` received, so ``apply`` can note what
the message did in a private attribute, one whose name starts with an
underscore. ``rejection`` is the :class:`~dallinger.realtime.Reject` that
``apply`` raised, or ``None``:

.. code-block:: python

    class Step(LiveMessage):
        type = "step"
        direction: Literal["up", "down", "left", "right"]
        _found_exit: bool = False

        def apply(self, game, state, player, now):
            ...
            self._found_exit = state["positions"][player] == state["exit"]

        def should_save(self, game, state, player, rejection):
            # Keep the steps into walls, which apply rejects, and the step
            # that found the exit.
            return rejection is not None or self._found_exit

PsyNet always saves its own messages, such as each player's
:class:`~psynet.live_game.PlayerReady`. A message the game couldn't read
is saved too, with ``message`` set to ``None``.

A message left out isn't in the exported data, so leave out only what the
analysis won't need. Dallinger's `save_message <dallinger-save-message_>`_
has the details.

Bots and testing
----------------

``psynet test`` runs an experiment with bots, which don't run a page's
JavaScript. When a group's members include bots, the game plays for them
through its ``bot`` method, as in ``RockPaperScissors`` above. It gets the
bot's view, the bot's player number and ``now``, and returns the bot's next
message, or ``None`` to send nothing. A message the game can't read makes
the game fail. A :class:`~psynet.live_game.PlayLiveGame` refuses a game
without ``bot``, since its bots would never move.

In a game without ticks, nothing happens between messages, so the game asks
the bots for their next moves straight after each change: once the game has
started, and again after every message (other bots' too), join and leave,
until no bot sends a message the game accepts. So ``bot`` must return
``None`` once the bot has nothing to do, or the bots would play forever and
the game fails. In a game with ticks, it runs once per tick. Dallinger's `bot
<dallinger-bot_>`_ has the details.

A group's bots have to reach the ``PlayLiveGame`` together, so set the
experiment's ``test_mode = "parallel"``, and ``test_n_bots`` to a multiple of
the group size. A bot's answer on the game page comes from the game's
``answer`` too, so the page doesn't need a ``bot_response``.

To test a game's rules in Python, without starting the experiment, play it
with :class:`~psynet.live_game.testing.LocalGame`. It starts the game, and
calls the game's methods as PsyNet does:

.. code-block:: python

    import pytest
    from dallinger.realtime import Reject
    from psynet.live_game.testing import LocalGame

    game = LocalGame(RockPaperScissors, players=2)
    game.send(0, Choose(action="rock"))
    assert game.view(0)["chosen"] and not game.is_over()
    assert game.bot(0) is None
    game.send(1, Choose(action="paper"))
    assert game.is_over()

``send`` raises ``Reject`` for a message the game rejects, so test a rule
with ``pytest.raises(Reject)``.

To play a game yourself, run ``psynet debug local`` and open the participant
link in a browser window for each player. For a game with ticks, run
``psynet debug local --legacy`` instead, which uses gunicorn, the web server a
deployed experiment uses. The development server that ``psynet debug local``
runs by default sometimes delivers the game's views late, in bursts, so other
players' movement stalls or jumps, which looks like a problem with the game
when it isn't. ``psynet debug local`` warns about this when it starts.

.. _dallinger-realtime-games: https://dallinger.readthedocs.io/latest/realtime_games.html
.. _dallinger-realtime-api: https://dallinger.readthedocs.io/latest/realtime_games.html#api-reference
.. _dallinger-outcome: https://dallinger.readthedocs.io/latest/realtime_games.html#dallinger.realtime.RealtimeGame.outcome
.. _dallinger-save-message: https://dallinger.readthedocs.io/latest/realtime_games.html#dallinger.realtime.RealtimeGame.save_message
.. _dallinger-bot: https://dallinger.readthedocs.io/latest/realtime_games.html#dallinger.realtime.RealtimeGame.bot

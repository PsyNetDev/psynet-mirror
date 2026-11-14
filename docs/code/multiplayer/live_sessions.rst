.. _live_sessions:

=============
Live sessions
=============

A live session is a game that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.
The server keeps one state for the whole group, applies each player's
messages to it in order, and sends each player's page its own view of the
game. Each session, with its messages, is saved with the experiment's data.

A live session has three pieces:

1. The game, a subclass of :class:`~psynet.live_session.LiveGame`, with a
   :class:`~psynet.live_session.LiveMessage` subclass for each kind of
   message a page can send.
2. The game page, a :class:`~psynet.modular_page.ModularPage` with a
   :class:`~psynet.live_session.LiveSessionControl`, and a JavaScript file
   that plays the game through ``psynet.liveSession``.
3. A :class:`~psynet.live_session.PlayLiveGame` in the timeline, which
   makes each group that reaches it wait for its members, starts a session
   for the group, and then shows them the game page.

The game
--------

A game of rock, paper, scissors:

.. code-block:: python

    import random
    from typing import Literal

    from psynet.live_session import LiveMessage, LiveGame


    class Choose(LiveMessage):
        type = "choose"
        action: Literal["rock", "paper", "scissors"]

        def apply(self, game, state, player_id, now):
            state["choices"][player_id] = self.action


    class RockPaperScissors(LiveGame):
        channel = "rock_paper_scissors"
        messages = [Choose]

        def initial_state(self, players):
            return {"choices": {player: None for player in players}}

        def view(self, state, player_id):
            return {"chosen": state["choices"][player_id] is not None}

        def is_over(self, state):
            return None not in state["choices"].values()

        def bot(self, view, player_id, now):
            if view["chosen"]:
                return None
            return Choose(action=random.choice(["rock", "paper", "scissors"]))

``initial_state`` sets up the state for the session's players, ``view`` says
what a player's page shows, ``is_over`` says when the game ends, and ``bot``
plays for bots (see `Bots and testing`_). The state and the views are dicts.
Each player's id is their participant id as a string, such as ``"12"``.
Ids are strings because the state is saved as JSON, whose dict keys are
strings, so they work as keys in the state's dicts. To list the players in
the order they joined, read ``state["live_session"]["players"]`` (see `The
ready step`_) rather than sorting the ids, which sorts ``"10"`` before
``"9"``. Code outside the game rarely needs the ids: the game's ``answer``
gives each player their own part of the outcome (see `The answer and
rewards`_).

A game can also have a time limit, a clock that ticks, an outcome and more,
which come from Dallinger's :class:`~dallinger.realtime.RealtimeGame`.
Dallinger's guide to `real-time games <dallinger-realtime-games_>`_ explains
them, and its `API reference <dallinger-realtime-api_>`_ describes each
method and setting that comes from ``RealtimeGame``.

Define each game, or import it, before the experiment class. PsyNet then adds
it to the experiment's ``realtime_games``, so you don't list it there. A game
defined after the experiment class stops the experiment at launch, with an
error that names it.

PsyNet adds every game with a ``channel`` that Python has loaded by then,
whether or not the timeline plays it. That includes a game in a module you
import from another experiment, so give every game a channel of its own.

Messages and the state
----------------------

PsyNet checks each message before its ``apply`` runs, and rejects one with a
field missing, an extra field, or a field of the wrong type. The sender's page
gets the reason. The check is strict: ``"1"`` isn't accepted as a number, nor
``1`` as text, and no number in the message can be ``NaN`` or infinite.

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

A dict key has to be a string already: a state with a key such as ``3``
makes the session fail, because after a save the key would read back as
``"3"`` and ``state["scores"][3]`` would fail. Player ids are already
strings. A value PsyNet can't convert, such as an object of a class of your
own, also makes the session fail. So does ``math.inf`` or ``NaN``, which JSON can't hold, so
store ``None`` instead. Because a field stored in the state is converted,
compare like with like:

.. code-block:: python

    from dallinger.realtime import Reject


    class Move(LiveMessage):
        type = "move"
        to: tuple[int, int]

        def apply(self, game, state, player_id, now):
            # The state holds a list, and a list never equals a tuple.
            if state["positions"][player_id] == list(self.to):
                raise Reject("You're already there.")
            state["positions"][player_id] = self.to

In the same way, compare an enum field's ``.value`` with the state, and turn
a stored date back into a datetime with
``datetime.fromisoformat(state["deadline"])``. A game with a very large
state, such as a big grid, can save the time the conversion takes with
:attr:`~psynet.live_session.LiveGame.convert_state_to_json`.

Starting sessions and the game page
-----------------------------------

Put a :class:`~psynet.live_session.PlayLiveGame` after the
:class:`~psynet.sync.Grouper` that forms the groups, and give it the game
page. It waits at a barrier, a :class:`~psynet.sync.GroupBarrier` for the
group's ``group_type``, until all of a group's members reach it, starts a
session, and then shows the group the game page:

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
                LiveSessionControl(),
                js_page_modules=["/static/rock_paper_scissors.js"],
                time_estimate=30,
            ),
        ),
        ...
    )

The game page plays the session that this ``PlayLiveGame`` started, so give
each ``PlayLiveGame`` a page of its own. Its ``id_`` is the game's
``channel`` unless you give one. Steps with the same id share their wait,
like barriers with the same id, so a game that the timeline plays in two
places, such as a practice game and the main game, needs a different
``id_`` in each.

A game needs at least ``min_players`` players, 2 unless the game sets it. A
group that reaches the ``PlayLiveGame`` with fewer active members, for example
because the others left it while it waited, starts no session, and its
members' game pages show the no-session notice (see `Cases a game page should
allow for`_). Set ``min_players = 1`` for a game a player can play alone.

``PlayLiveGame`` takes the options of a :class:`~psynet.sync.GroupBarrier`,
such as ``max_wait_time``, for its barrier. Its ``on_session_start`` runs
once the session has started, with the arguments a group barrier's
``on_release`` takes and also ``live_session_id``. Use it for group bookkeeping at the start
of a round, such as choosing who leaves after it.

To play one game under different conditions, such as with a different
number of rounds, pass ``PlayLiveGame`` ``settings``: a dict, or any other
value that can be saved as JSON. The game's ``initial_state`` gets it as a
second argument. Here and below, ``rock_paper_scissors_page()`` returns a new
game page like the one above:

.. code-block:: python

    PlayLiveGame(
        group_type="pair",
        game_class=RockPaperScissors,
        page=rock_paper_scissors_page(),
        settings={"rounds": 3},
    )


    class RockPaperScissors(LiveGame):
        def initial_state(self, players, settings):
            return {"rounds": settings["rounds"], "choices": {}, ...}

The game's other methods get only the state, so ``initial_state`` keeps what
they need in it. To vary the settings from trial to trial, return a
``PlayLiveGame`` from a trial's ``show_trial``, and pass the trial's
``definition`` as the settings:

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
``cue`` calls once for the pair. Such a trial needs a
:class:`~psynet.sync.GroupBarrier` in its ``show_trial``, and the barrier of
the ``PlayLiveGame`` is one. The round's
:attr:`~psynet.sync.SyncGroupRound.live_session_id` then names the session
the group played in it, so ``trial.group_round`` leads from each trial to its
round's game, for example in an export.

The page's JavaScript goes in a file in the experiment's ``static`` folder,
listed in the page's ``js_page_modules``. It exports an ``activate``
function, which PsyNet runs each time the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules).
``static/rock_paper_scissors.js``:

.. code-block:: javascript

    export function activate({root, psynet}) {
        let status = root.querySelector("#status");
        if (!psynet.liveSession.hasSession) {
            return;
        }
        let buttons = ["rock", "paper", "scissors"].map(
            (action) => root.querySelector("#" + action)
        );
        psynet.liveSession.enableWhilePlaying(...buttons);
        psynet.liveSession.onView((view) => {
            if (psynet.liveSession.ended) {
                status.textContent = "The game is over.";
            } else if (!psynet.liveSession.started) {
                status.textContent = "Waiting for your partner to arrive";
            } else {
                status.textContent =
                    view.chosen ? "Waiting for your partner" : "Your turn";
            }
        });
        psynet.liveSession.onRejected((number, reason) => {
            root.querySelector("#rejection").textContent = reason;
        });
        for (let button of buttons) {
            button.addEventListener("click", () => {
                root.querySelector("#rejection").textContent = "";
                psynet.liveSession.send("choose", {action: button.id});
            });
        }
    }

``psynet.liveSession`` offers:

- ``send(type, message)`` sends the game a message, and returns its number,
  or ``undefined`` once the page's connection is closed or refused.
- ``onView(callback)`` calls ``callback`` with each new view, what the game's
  ``view`` returns for this player, ending with the final view. A page that
  opens after the session has ended gets just the final view.
- ``onRejected(callback)`` calls ``callback`` with the number of each message
  the game rejected and the reason. The view that follows comes straight
  after, so show the reason somewhere ``onView`` doesn't overwrite, as the
  example does.
- ``onStarted(callback)`` calls ``callback`` with the first view once the
  session has started, or at once if it already has. A page that opens after
  the session has ended gets ``onEnded`` instead.
- ``enableWhilePlaying(...elements)`` enables the elements, such as
  buttons, only while the session is played: they are disabled until it
  starts, and again once it ends.
- ``started`` says whether the session has started, and ``ended`` whether it
  has ended. In ``onView``, both are already up to date for the view. On a
  page that opens after the end, ``started`` stays ``false``, so check
  ``ended`` first.
- ``onEnded(callback)`` calls ``callback`` once the session ends, with why it
  ended and the player's final view, which ``onView`` has already had.
- ``onPlayersAway(callback)`` calls ``callback`` with the ids of the players
  who have left the game page and not come back (see "Joining and leaving"
  below).
- ``predict(callback)`` and ``predictedView()`` show the player's own
  messages at once. ``callback(view, type, message, sentAt)`` changes a view
  as the game will once it applies the message, and ``predictedView()``
  returns the newest view with the page's messages that the game hasn't
  applied yet applied by ``callback``. Draw from it in ``onView`` and after
  ``send``. ``sentAt`` is the session time when the page sent the message
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
- ``onResultSaved(callback)`` and ``onRefused(callback)`` call ``callback``
  once the session's result is saved, or with the close code and reason if
  the server refuses the page's connection. Either way, the page then moves
  on by itself (see "The end" below).
- ``hasSession`` says whether the group started a session at the ``PlayLiveGame``.
  Without one, PsyNet shows the participant a notice, and the other methods
  throw an error.
- ``socket`` is the page's Dallinger socket, for anything else, such as
  ``serverTime``.

The page leaves the session when the participant moves on, so ``activate``
doesn't need to return a cleanup function for it.

Cases a game page should allow for
----------------------------------

No session
    A participant can reach the page without one, for example when the
    ``max_wait_action="leave_group"`` of the ``PlayLiveGame`` took them out
    of a group whose other members were too slow to arrive, or when their
    group ended before they reached the ``PlayLiveGame``. PsyNet tells the
    participant with a notice at the top of the page, "Your group couldn't
    start the game.", which the control's ``no_session_message`` changes or
    turns off. The page's JavaScript should check
    ``psynet.liveSession.hasSession`` first, as above, and do nothing more
    without a session.

Joining in time
    The page joins the session when its JavaScript first uses
    ``psynet.liveSession``, so call ``onView`` in ``activate``. The session's
    clock starts when the group's wait at the ``PlayLiveGame`` ends, and if
    none of the group has opened the page by the game's ``join_timeout``, 60
    seconds unless the game sets it, the session ends.

Rejected messages
    A message is rejected when one of its fields is missing or of the wrong
    type, which is usually a mistake in the page's JavaScript, or when the
    game's ``apply`` raises ``Reject``, such as for a move out of turn. Show
    the participant the reason, or match the number ``send`` returned.

The end
    ``onView`` gets the final view with ``ended`` set, and ``onEnded`` runs,
    and the game ignores any message sent after that. If the session fails,
    the final view can be ``null``. The example reads the view only before
    the end, so it allows for that.

    The participant can leave the page only once the session's result is
    saved, a few seconds after the game ends, and the page then moves on by
    itself. Until then its Next button is hidden. A participant without a
    session still sees it, so they can move on. So does a participant whose
    page has been disconnected for ten seconds: if they click it, the page
    says the game isn't over yet and moves on once the result is saved. The
    page also moves on if the server refuses its connection, as it does when
    the participant reloads the page long after the session ended.

    To show the result on the game page first, pass the seconds to show it
    for as the control's ``show_result_for``, such as
    ``LiveSessionControl(show_result_for=8)``, and draw the result
    in ``onResultSaved``. The page moves on once the seconds are up, and
    ``psynet.liveSession.showResultFor`` gives them to the page for a
    countdown. A later :class:`~psynet.sync.GroupBarrier`'s ``late_after``
    counts from the end of these seconds, so it needn't cover them.

    To move on from the page's JavaScript instead, pass
    ``auto_advance=False`` to the control, and call ``psynet.nextPage()`` in
    both ``onResultSaved`` and ``onRefused``. The Next button then stays, and if the participant clicks
    it before the result is saved, the page says the game isn't over yet and
    sends the response again every second until it's accepted. If you hide
    the Next button with ``show_next_button=False``, give a page without a
    session another way to move on, such as a button of its own that calls
    ``psynet.nextPage()``.

Joining and leaving
    The game's ``on_join`` runs when a player opens a page in the session
    while none of theirs is open, and ``on_leave`` runs when their last one
    closes, so a participant who closes the page during the game leaves the
    session. The game carries on without them unless ``on_leave`` ends it.

    While a player is away for more than a few seconds, the other players'
    pages show a notice at the top that says "Another player has left the
    game." Change it with the control's ``player_left_message``, such as
    ``LiveSessionControl(player_left_message="Your partner has
    left.")``. To show it your own way, set
    ``player_left_message=None`` and use ``onPlayersAway``, which gets the ids
    of the players who are away, and an empty list once they're all back.
    The notice only says what happened: a game that should end when a player
    leaves still ends in its ``on_leave`` or ``is_over``.

Reloading and dropped connections
    The page reconnects by itself, rejoins and gets the game as it stands,
    and messages sent while it was down go then. A reload usually runs
    ``on_leave`` and then ``on_join``, so an ``on_leave`` that ends the
    session also ends it when a player reloads. A page reloaded within an
    hour of the session ending gets the ending at once. After that, the
    server refuses the connection.

Another tab
    The same page open in another tab plays as the same player. When the
    session's result is saved, both tabs try to move on. One of them does,
    and in the other PsyNet asks the participant to close their other tabs
    and refresh the page.

The ready step
--------------

A session starts once every player is ready. A game page says so by itself a
moment after it opens, and a bot is ready at once, or at the first tick in a
game with ticks. A player whose page closes before the start isn't ready any
more, until the page reconnects. If some players aren't ready by the game's
``ready_timeout``, 60 seconds unless the game sets it, the session starts
without them, and they can still join and play. With ``ready_timeout = None``
the session waits for every player, so if someone never reaches the game
page, it waits until the game's ``max_duration``.

Until the start, the game rejects messages with the reason ``"The game hasn't
started yet."``, and its ``tick`` and ``bot`` don't run, so disable the page's
controls with ``enableWhilePlaying``, as above, or wait for ``onStarted``.
The game's other methods run before the start: ``on_join``, ``on_leave``,
``view``, ``is_over``, and ``outcome`` if the session ends before it starts.

PsyNet keeps track of the ready step in ``state["live_session"]``, and adds
the same entry to each view. Don't use the name ``live_session`` for anything
else in the state or a view. It holds:

- ``players``, the ids of the session's players
- ``ready``, the ids of the players who are ready
- ``started_at``, the session time at which the session started, or ``None``
  before the start
- ``ends_at``, the session time at which a game with a ``duration`` ends, or
  ``None`` before the start or without a ``duration``
- ``time_up``, whether a game with a ``duration`` has reached ``ends_at``
- ``away``, the ids of the players who have left the game page and not come
  back. A player who hasn't opened it yet isn't in it.

The messages that say a player is ready are PsyNet's, so the game's ``apply``
never receives them, even if the game defines its own. To show who is ready,
read ``ready`` from the view.

The session time, and ``max_duration``, count from when the group's wait at
the ``PlayLiveGame`` ended, not from the start. ``self.elapsed(state, now)`` gives the
seconds since the start, or ``None`` before it, for example to record how
long a group took to agree.

A game that lasts a fixed time sets ``duration``, in seconds from the start.
PsyNet runs the game's ``tick`` at the end, if it has one, and then ends the
session with the reason ``"finished"``, unless the game's ``is_over`` ended
it earlier. This version of the game gives the pair 10 seconds to choose:

.. code-block:: python

    class TimedRockPaperScissors(RockPaperScissors):
        channel = "timed_rock_paper_scissors"
        duration = 10

Messages that arrive from then on are rejected with the reason ``"The
game's time is up."``. The page shows the time left with
``psynet.liveSession.secondsLeft()``, which is 0 once the session has ended,
and ``psynet.liveSession.duration``:

.. code-block:: javascript

    setInterval(() => {
      let left = psynet.liveSession.secondsLeft();
      if (left !== null) {
        bar.style.width = `${(left / psynet.liveSession.duration) * 100}%`;
      }
    }, 250);

For other deadlines, such as one for each move, a game sets them in
``on_start``, which runs at the start even if some players aren't ready, and
returns the next one from ``next_deadline``. Its ``tick`` runs at each one,
and at the end of its ``duration``. A tick that runs late gets the end as
``now``, so a game that counts things on a schedule, such as catches every
few seconds, counts none after the end.

The answer and rewards
----------------------

The game page's answer comes from the session's outcome: what the game's
``outcome`` method returned when the session ended. PsyNet sets it on the
server and ignores what the page sends, and a participant without a session
gets ``None``. By default, every player's answer is the whole outcome. Define
``answer(outcome, reason, player_id)`` to give each player only their own
part, so that a trial holds only its player's data and code reading
``trial.answer`` needs no player ids:

.. code-block:: python

    class RockPaperScissors(LiveGame):
        ...

        def answer(self, outcome, reason, player_id):
            mine = outcome[player_id]
            (theirs,) = [c for p, c in outcome.items() if p != player_id]
            return {"mine": mine, "theirs": theirs, "reason": reason}

Results that belong to the whole group, such as a team's total, stay in the
outcome. When the game is played as a trial (see `Starting sessions and the
game page`_), PsyNet copies the outcome to the round the session was played
in once the session's ending is saved, so later pages and the export read it
as ``trial.group_round.live_session_outcome``, with no need for another
barrier after the game page to score the round:

.. code-block:: python

    pot = trial.group_round.live_session_outcome["pot"]

It is ``None`` until then, and ``answer`` isn't called, for a session that
failed without an outcome.

Because participants can't leave the game page until their session ends,
every session needs a time limit. A session still running at the game's
``max_duration``, 10 minutes unless the game sets it, ends with the reason
``"max_duration"``. ``max_duration = None`` removes the limit, so set it only
if the game always ends by itself, even when players leave. A game with a
``duration`` doesn't need to set it: PsyNet sets it to the ``ready_timeout``
plus the ``duration`` plus 30 seconds, so that a session that starts at the
ready timeout still ends on its own.

The limit also tells PsyNet when a session can no longer end, for example
because the worker that runs the experiment's sessions has stopped. If a
session is still running more than a minute after its ``max_duration``, its
game page stops waiting: the participant sees PsyNet's error page, and a bot
fails with an error that names the session. Without a ``max_duration``, the
page waits as long as the session runs.

The game page also stops a later :class:`~psynet.sync.GroupBarrier` from
counting a player who is still in the game as late. ``late_after`` counts from
the group's previous barrier, which is usually the barrier of a ``PlayLiveGame``, so it would
otherwise include the whole game. Instead, as for a page with a
``time_limit``, it counts from when the game page ends: at first the game's
``max_duration`` plus a minute, and once the session's ending is saved, when
the game actually ended, plus the control's ``show_result_for``. So
``late_after`` needs to cover only the pages after the game.

A game can add to each player's performance reward in two ways. Each amount
must be a number of 0 or more. For a reward based on the outcome, define
``performance_reward(outcome, reason, player_id)`` to return the player's
reward. PsyNet pays it to each player once, when the session's ending is
saved, however the session ended, so a player who left the game page early
is paid too. This game pays 0.10 for a win:

.. code-block:: python

    BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


    class RockPaperScissors(LiveGame):
        ...

        def outcome(self, state, reason):
            return state["choices"]

        def performance_reward(self, outcome, reason, player_id):
            mine = outcome[player_id]
            (theirs,) = [
                choice for player, choice in outcome.items() if player != player_id
            ]
            return 0.10 if mine is not None and BEATS[mine] == theirs else 0

``reason`` is ``"finished"`` when ``is_over`` ended the game, and Dallinger's
`outcome <dallinger-outcome_>`_ lists the other reasons. If the game's code
raised an error, ``reason`` is ``"failed"``, and ``outcome`` is the outcome of
the state just before the error.

For a reward earned during the game, such as for each coin a player collects,
call ``game.add_performance_reward(player_id, amount)`` in a message's
``apply`` or in another method that changes the state. PsyNet adds it to the
player's reward a few seconds later, so the player keeps it even if they
leave early.

A session can fail without an outcome: its record couldn't be saved, or the
game's ``outcome`` raised an error as well. The answer is then ``None`` and
PsyNet doesn't call ``performance_reward``, but amounts from
``add_performance_reward`` saved before the problem are still paid. A game that must pay players whatever happens can
pay them as it goes. :func:`~psynet.live_session.live_session_result` says
how a session ended, and whether its record is complete.

Saved messages
--------------

Each session's record is saved with the experiment's data, in Dallinger's
``realtime_session`` and ``realtime_event`` tables: the session's outcome and
final state, and each message a page sent, with whether the game accepted it.
To read a session's messages in Python, call ``saved_messages`` on the game,
for all of them, or on a message type, for that type's. On a later page:

.. code-block:: python

    session_id = live_session_id(participant, "rock_paper_scissors")
    if session_id is not None:
        for saved in Choose.saved_messages(session_id):
            if saved.message is not None:
                print(saved.player_id, saved.message.action, saved.session_time)

``live_session_id`` finds the session from the participant's latest visit to
the ``PlayLiveGame`` with that ``id_``, or returns ``None`` if their group didn't start one. In an
analysis, ``realtime_sessions_for(participant, game_type)`` from
``dallinger.realtime`` returns all of a participant's sessions of a game, and
each one's ``id`` is its session id.

Each message is a :class:`~psynet.live_session.SavedMessage`, in the order the
game applied them. Its ``message`` is ``None`` if what the page sent can't be
read as one of the game's message types, and its ``payload`` holds what the
page sent. ``PlayerReady.saved_messages(session_id)`` says when each player became
ready.

The record is written a few seconds behind the game, so while a session is
still running, ``saved_messages`` returns only the messages written so far.
By the page after the game page, the whole record has been written, unless
``live_session_result(session_id).record_complete`` says that saving it
failed.

A game saves every message by default. A game whose pages send many messages,
such as a move on every key press, can leave some out by defining
``save_message`` to return ``False`` for them. It runs after the game has
accepted or rejected the message, and ``rejection`` is the
:class:`~dallinger.realtime.Reject` the game raised, or ``None``:

.. code-block:: python

    class Maze(LiveGame):
        ...

        def save_message(self, state, player_id, message, rejection):
            # Leave out moves into a wall, which apply rejects.
            return rejection is None or rejection.reason != "That's a wall."

A message left out isn't in the exported data, so leave out only what the
analysis won't need. Dallinger's `save_message <dallinger-save-message_>`_
has the details.

Bots and testing
----------------

``psynet test`` runs an experiment with bots, which don't run a page's
JavaScript. When a group's members include bots, the game plays for them
through its ``bot`` method, as in ``RockPaperScissors`` above. It gets the
bot's view, the bot's player id and the session time, and returns the bot's
next message, or ``None`` to send nothing. A message the game can't read
makes the session fail. A :class:`~psynet.live_session.PlayLiveGame`
refuses a game without ``bot``, since its bots would never move.

In a game without ticks, ``bot`` runs once the session has started, and again
after every message (other bots' too), join and leave, until no bot sends a
message the game accepts. So it must return ``None`` once the bot has nothing
to do. In a game with ticks, it runs once per tick. Dallinger's
`bot <dallinger-bot_>`_ has the details.

A group's bots have to reach the ``PlayLiveGame`` together, so set the experiment's
``test_mode = "parallel"``, and ``test_n_bots`` to a multiple of the group
size. A bot's answer on the game page is the outcome too, so the page doesn't
need a ``bot_response``.

To test a game's methods in Python, start the session with
:func:`~psynet.live_session.testing.start_session` first, since the game
rejects messages and ``bot`` sends nothing until the start. Then pass a
message to the game as a page would, with ``Sent`` from ``dallinger.realtime``,
or give ``bot`` a view the game made:

.. code-block:: python

    from dallinger.realtime import Sent
    from psynet.live_session.testing import start_session

    game = RockPaperScissors()
    state = game.initial_state(["1", "2"])
    start_session(game, state)
    message = {"type": "choose", "message": {"action": "rock"}}
    game.apply(state, "1", message, 0, Sent())
    assert state["choices"]["1"] == "rock"
    assert game.bot(game.view(state, "1"), "1", 0) is None

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

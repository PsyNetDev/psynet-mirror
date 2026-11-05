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

1. The game, a subclass of :class:`~psynet.live_session.LiveSession`, with a
   :class:`~psynet.live_session.LiveMessage` subclass for each kind of
   message a page can send.
2. A :class:`~psynet.live_session.LiveSessionInitializer` in the timeline,
   which starts a session for each group that reaches it.
3. The game page, a :class:`~psynet.modular_page.ModularPage` with a
   :class:`~psynet.live_session.LiveSessionControl`, and a JavaScript file
   that plays the game through ``psynet.liveSession``.

The game
--------

A game of rock, paper, scissors:

.. code-block:: python

    import random
    from typing import Literal

    from psynet.live_session import LiveMessage, LiveSession


    class Choose(LiveMessage):
        type = "choose"
        action: Literal["rock", "paper", "scissors"]

        def apply(self, game, state, player_id, now):
            state["choices"][player_id] = self.action


    class RockPaperScissors(LiveSession):
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
plays for bots (see `Bots`_). The state and the views are dicts. A game can
also have a time limit, a clock that ticks, an outcome and more, which come
from Dallinger's :class:`~dallinger.realtime.RealtimeGame`. The game starts
once every player's page is ready (see `The ready step`_).

Define each game, or import it, before the experiment class. PsyNet then adds
it to the experiment's ``realtime_games``, so you don't list it there.

Messages and the state
----------------------

PsyNet checks each message before its ``apply`` runs, and rejects one with a
field missing, an extra field, or a field of the wrong type. The sender's page
gets the reason. The check is strict: ``"1"`` isn't accepted as a number, nor
``1`` as text, and no number in the message can be ``NaN`` or infinite.

A field can have any type Pydantic reads from JSON, such as a ``tuple``, an
``Enum``, a ``datetime`` or another Pydantic model, and in ``apply`` it holds
a value of that type. The state holds only plain data: what JSON can hold,
which is dicts with string keys, lists, strings, numbers, booleans and
``None``. PsyNet converts anything else when ``initial_state`` returns, and
after a message's ``apply`` or the game's ``tick``, ``on_join``,
``on_leave`` or ``on_start`` runs:

- a tuple becomes a list, and a set a list in no fixed order, so store
  ``sorted(...)`` where the order matters
- an enum member becomes its value
- a date, time or datetime becomes a string such as
  ``"2026-11-02T09:30:00"``, and a timedelta one such as ``"PT1M30S"``
- a Pydantic model becomes a dict
- a ``Decimal`` or ``bytes`` value becomes a string
- a dict key becomes a string, so ``{1: "a"}`` becomes ``{"1": "a"}`` and
  ``{(1, 2): "a"}`` becomes ``{"1,2": "a"}``. Player ids are already strings.

A value PsyNet can't convert, such as an object of a class of your own, makes
the session fail. So does ``math.inf`` or ``NaN``, which JSON can't hold:
store ``None`` instead.

A field stored in the state is converted, so compare like with like:

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
``datetime.fromisoformat(state["deadline"])``. Until ``apply`` returns, a
value it has just stored is unchanged.

The conversion takes time in proportion to the size of the whole state. A game
with a very large state, such as a big grid, can turn it off with
``convert_state_to_json = False``. It then stores only plain data itself, such
as ``list(...)`` of a tuple field and an enum field's ``.value``. Anything
else changes only when Dallinger next saves the state or rejects a message,
which restores the state from plain data: a tuple then becomes a list and
``{1: "a"}`` becomes ``{"1": "a"}``.

To test a message, pass it to the game as a page would, with ``Sent`` from
``dallinger.realtime``:

.. code-block:: python

    from dallinger.realtime import Sent

    game = RockPaperScissors()
    state = game.initial_state(["1", "2"])
    # As when every player is ready, since the game rejects messages before.
    game.start_session(state, 0)
    message = {"type": "choose", "message": {"action": "rock"}}
    game.apply(state, "1", message, 0, Sent())
    assert state["choices"]["1"] == "rock"

Starting sessions and the game page
-----------------------------------

Put the initializer after the :class:`~psynet.sync.Grouper` that forms the
groups. When all of a group's members reach it, it starts a session, and the
group moves on together. The game page comes after it, and its
:class:`~psynet.live_session.LiveSessionControl` names the initializer:

.. code-block:: python

    timeline = Timeline(
        SimpleGrouper(group_type="pair", initial_group_size=2),
        LiveSessionInitializer(
            id_="rock_paper_scissors",
            group_type="pair",
            game_type=RockPaperScissors,
        ),
        ModularPage(
            "rock_paper_scissors",
            Prompt(
                tags.div(
                    tags.p(id="status"),
                    tags.button("Rock", type="button", id="rock"),
                    tags.button("Paper", type="button", id="paper"),
                    tags.button("Scissors", type="button", id="scissors"),
                )
            ),
            LiveSessionControl("rock_paper_scissors"),
            js_page_modules=["/static/rock_paper_scissors.js"],
            time_estimate=30,
        ),
        ...
    )

The page's JavaScript goes in a file in the experiment's ``static`` folder,
listed in the page's ``js_page_modules``. It exports an ``activate``
function, which PsyNet runs each time the page opens
(:doc:`/code/pages/custom_front_ends` explains page modules).
``static/rock_paper_scissors.js``:

.. code-block:: javascript

    export function activate({root, psynet}) {
        let status = root.querySelector("#status");
        if (!psynet.liveSession.hasSession) {
            status.textContent = "Your group couldn't start the game.";
            return;
        }
        let buttons = ["rock", "paper", "scissors"].map(
            (action) => root.querySelector("#" + action)
        );
        psynet.liveSession.disableUntilStarted(...buttons);
        psynet.liveSession.onView((view) => {
            if (view === null) {
                return;
            }
            if (!psynet.liveSession.started) {
                status.textContent = "Waiting for your partner to arrive";
            } else {
                status.textContent =
                    view.chosen ? "Waiting for your partner" : "Your turn";
            }
        });
        psynet.liveSession.onRejected((number, reason) => {
            status.textContent = reason;
        });
        psynet.liveSession.onEnded(() => {
            status.textContent = "The game is over. Click Next.";
        });
        for (let button of buttons) {
            button.addEventListener("click", () => {
                psynet.liveSession.send("choose", {action: button.id});
            });
        }
    }

``psynet.liveSession`` offers:

- ``send(type, message)`` sends the game the message with that ``type``, and
  returns its number, or ``undefined`` once the page's connection is closed or
  refused.
- ``onStarted(callback)`` calls ``callback`` once the session has started,
  with the first view after the start, or at once if it already has. A page
  that opens after the session has ended gets ``onEnded`` instead.
- ``disableUntilStarted(...elements)`` disables the elements, such as
  buttons, until the session starts.
- ``started`` says whether the session has started. In ``onView``, it's
  already up to date for the view.
- ``onView(callback)`` calls ``callback`` with each new view, what the game's
  ``view`` returns for this player.
- ``onRejected(callback)`` calls ``callback`` with the number of each message
  the game rejected and the reason.
- ``onEnded(callback)`` calls ``callback`` once the session ends, with why it
  ended and the player's final view.
- ``onResultSaved(callback)`` calls ``callback`` once the session's result has
  been saved.
- ``onRefused(callback)`` calls ``callback`` with the close code and reason if
  the server refuses the page's connection.
- ``hasSession`` says whether the group started a session at the initializer.
  Without one, the other methods throw an error.
- ``socket`` is the page's Dallinger socket, for anything else, such as
  ``serverTime``.

The page leaves the session when the participant moves on, so ``activate``
doesn't need to return a cleanup function for it.

Cases a game page should allow for
----------------------------------

No session
    A participant can reach the page without one, for example when the
    initializer's ``max_wait_action="kick"`` removed them from a group that
    took too long to arrive. ``psynet.liveSession.hasSession`` is then
    ``false``, and the other methods throw an error. Check it first, as
    above, and tell the participant.

Joining in time
    The page joins the session when its JavaScript first uses
    ``psynet.liveSession``, so call ``onView`` in ``activate``, and the page
    joins as it opens. The session's clock starts when the group leaves the
    initializer, and if none of the group has opened the page by the game's
    ``join_timeout``, 60 seconds unless the game sets it, the session ends.
    Pages between the initializer and the game page count against it, and
    against the game's ``ready_timeout``, so raise both to allow for them.

Rejected messages
    A message is rejected when one of its fields is missing or of the wrong
    type, which is usually a mistake in the page's JavaScript, or when the
    game's ``apply`` raises ``Reject``, such as for a move out of turn. Show
    the participant the reason, or match the number ``send`` returned.

The end
    ``onEnded`` says the game is over. The game ignores messages sent after
    it, though ``send`` still returns a number. A session that fails can end
    with a view of ``null``, as in the example above. The page doesn't move on by
    itself. To keep the participant on the page until the game is over, pass
    ``show_next_button=False`` to the control and call ``psynet.nextPage()``
    in ``onResultSaved``. The page then needs other ways on: in
    ``onRefused``, since a refused page gets no ``onResultSaved``, and, with
    no session, its own button that calls ``psynet.nextPage()``.

Joining and leaving
    The game's ``on_join`` runs when a player opens their first page in the
    session, and ``on_leave`` when their last one closes. With a Next button,
    a participant can move on during the game. Their page leaves the session,
    ``on_leave`` runs unless the page is still open in another tab, and the
    game carries on without them unless ``on_leave`` ends it.

Reloading and dropped connections
    The page reconnects by itself and rejoins, and gets the game as it
    stands. A reload usually runs ``on_leave`` and then ``on_join``, but runs
    neither if the new page joins before the old one has left. So an
    ``on_leave`` that ends the session also ends it when a player reloads. A
    message sent while the connection is down goes once it reconnects. A page
    reloaded within an hour of the session ending gets the ending at once.
    After that, the server has forgotten the session and refuses the
    connection.

Another tab
    The same page left open in another tab can go on playing until its
    connection drops, or the session ends: then it can't connect again.

The ready step
--------------

A session starts once every player is ready. A game page says so by itself,
once it has measured its clock against the server's, which takes a moment
after the page opens. A bot is ready at once, or, in a game with ticks, at
the first tick. A player whose page closes before the start isn't ready any
more, until the page reconnects or reloads.

Until the start, the game rejects messages with the reason ``"The game hasn't
started yet."``, and its ``tick`` and ``bot`` don't run. So a page disables
its controls until the start with ``disableUntilStarted``, as in the example
above, or waits for ``onStarted`` to set up anything else. The game's other
methods do run before the start: ``on_join`` and ``on_leave`` as players
arrive and leave, ``view`` for each page that joins, ``is_over`` after each
change, and ``outcome`` if the session ends before it starts.

If some players aren't ready by the game's ``ready_timeout``, 30 seconds
unless the game sets it, the session starts without them, and they can still
join and play. Like ``join_timeout``, it counts from when the group leaves
the initializer. ``ready_timeout = None`` waits for every player, so a group
in which someone never reaches the game page waits until the game's
``max_duration``, or for ever if it has none.

PsyNet keeps track of the ready step in ``state["live_session"]``, and adds
the same entry to each view: ``players``, the ids of the session's players,
``ready``, those who are ready, and ``started_at``, the session time the
session started, or ``None``. So don't use the name ``live_session`` in the
state or a view.

The session time counts from when the group left the initializer, not from
the start, and so does ``max_duration``. A game whose rounds have a time
limit sets its deadlines in ``on_start``, and its ``tick`` runs at each one:

.. code-block:: python

    class TimedRockPaperScissors(RockPaperScissors):
        channel = "timed_rock_paper_scissors"

        def initial_state(self, players):
            state = super().initial_state(players)
            return {**state, "deadline": None, "late": False}

        def on_start(self, state, now):
            state["deadline"] = now + 10

        def next_deadline(self, state):
            return state["deadline"]

        def tick(self, state, now):
            if state["deadline"] is not None and now >= state["deadline"]:
                state["late"] = True

        def is_over(self, state):
            return state["late"] or super().is_over(state)

The deadline starts as ``None`` in ``initial_state``, since ``view`` and
``is_over`` can read the state before ``on_start`` runs. ``on_start`` runs at
the start, even when some players aren't ready. A game that needs every
player can end the session there, by noting it in the state for ``is_over``.
After the start, a player who leaves the game page doesn't end the session:
the game carries on without them, unless its ``on_leave`` ends it.

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

``live_session_id`` returns ``None`` if the participant's group didn't start a
session, and only finds the session from the participant's latest visit to the
initializer. In an analysis, ``realtime_sessions_for(participant, game_type)``
from ``dallinger.realtime`` returns all of a participant's sessions of a game,
oldest first, and each one's ``id`` is its session id.

Each message is a :class:`~psynet.live_session.SavedMessage`, in the order the
game applied them, with its ``status``: ``accepted``, ``rejected`` or
``failed``. Its ``message`` is ``None`` if what the page sent can't be read as
one of the game's message types, as for a message rejected for its fields, or
one saved before its message type changed, and its ``payload`` holds what the
page sent.

The record also holds each player's
:class:`~psynet.live_session.Ready` message, so
``Ready.saved_messages(session_id)`` says when each player became ready, at
their first. A page sends another each time it reconnects or reloads.

The record is written a few seconds behind the game, so for a session that's
still being played, ``saved_messages`` returns the messages written so far.
The record is complete once the session's ending is saved, as it is on any
page the participant reaches after the game page's ``onResultSaved``. The
session's ``status`` in Dallinger's ``realtime_session`` table is then
``ended`` or ``failed``. A session can also fail because its record couldn't
be saved. It then keeps only the messages saved before that, and its
``error`` says why.

A game saves every message by default. A game whose pages send many messages,
such as a move on every key press, can leave some out by defining
``save_message``, which returns ``True`` to save a message or ``False`` to
leave it out. It runs after the game has accepted or rejected the message, and
``rejection`` is the :class:`~dallinger.realtime.Reject` the game raised, or
``None``:

.. code-block:: python

    class Maze(LiveSession):
        ...

        def save_message(self, state, player_id, message, rejection):
            # Leave out moves into a wall, which apply rejects.
            return rejection is None or rejection.reason != "That's a wall."

A message left out isn't in ``saved_messages`` or the exported data, so leave
out only what the analysis won't need. Dallinger's
:meth:`~dallinger.realtime.RealtimeGame.save_message` has the details.

Bots
----

``psynet test`` runs an experiment with bots, which don't run a page's
JavaScript. When a group's members include bots, the game plays for them
through its ``bot`` method, as in ``RockPaperScissors`` above. It gets the
bot's view, the bot's player id and the session time, and returns the bot's
next message, or ``None`` to send nothing. A bot is ready at once, and
``bot`` runs once the session has started. A
:class:`~psynet.live_session.LiveSessionInitializer` refuses a game without
``bot``, since its bots would never move.

The game applies and saves a bot's message as it would a page's. If ``bot``
returns a :class:`~psynet.live_session.LiveMessage` the game can't read, such
as one whose type isn't in the game's ``messages``, the session fails. The
error, in the server's log and the session's ``error`` in Dallinger's
``realtime_session`` table, says why.

In a game without ticks, ``bot`` runs once the session has started, and again
after every message (other bots' too), join and leave, until no bot sends a message
the game accepts. So it must return ``None`` once the bot has nothing to do.
In a game with ticks, it runs once per tick. Dallinger's
:meth:`~dallinger.realtime.RealtimeGame.bot` has the details.

To test ``bot``, give it a view the game made after the start, such as
``game.view(state, player_id)`` after ``game.start_session(state, 0)``.

A group's bots have to reach the initializer together, so set the experiment's
``test_mode = "parallel"``, and ``test_n_bots`` to a multiple of the group
size. A bot moves on from the game page at once, without waiting for the game
to end.

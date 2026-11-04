"""Live sessions: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

You write a game as a subclass of :class:`LiveSession`. The game keeps a
*state*, everything it needs to remember, such as each player's choice. The
server holds one state for the whole group, so every player sees the same
game. Each kind of message a player's page can send, such as a choice or a
move, is a subclass of :class:`LiveMessage`, which lists what the message
holds and says how it changes the state. Each session, with its messages, is
saved with the experiment's data.

A game of rock, paper, scissors:

::

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

``initial_state`` sets up the state for the session's players, ``view`` says
what a player's page shows, and ``is_over`` says when the game ends. A game
can also have a time limit, a clock that ticks, an outcome and more:
:class:`LiveSession` is a Dallinger :class:`~dallinger.realtime.RealtimeGame`,
and Dallinger's "Real-Time Games" documentation explains them.

To have groups play the game, put a :class:`LiveSessionInitializer` in the
timeline after the :class:`~psynet.sync.Grouper` that forms the groups. When
all of a group's members reach it, it starts a session, and the group moves
on together. The page where they play is a
:class:`~psynet.modular_page.ModularPage` with a :class:`LiveSessionControl`,
and its JavaScript plays the game through ``psynet.liveSession``.

::

    timeline = Timeline(
        SimpleGrouper(group_type="pair", initial_group_size=2),
        LiveSessionInitializer(
            id_="rock_paper_scissors",
            group_type="pair",
            game_type=RockPaperScissors,
        ),
        ModularPage(
            "rock_paper_scissors",
            "Choose rock, paper or scissors.",
            LiveSessionControl("rock_paper_scissors"),
            js_page_modules=["/static/rock_paper_scissors.js"],
            time_estimate=30,
        ),
        ...
    )

:doc:`/code/multiplayer/live_sessions` walks through a whole game, its
page's JavaScript, and the cases a game page should allow for.

Define each game, or import it, before the experiment class. PsyNet then
adds it to the experiment's ``realtime_games``, so you don't list it there.
"""

import contextvars
import dataclasses
import datetime
import functools
import json
from typing import ClassVar

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession
from dallinger.realtime import RealtimeGame, Reject, create_realtime_session
from pydantic import (
    BaseModel,
    ConfigDict,
    PydanticInvalidForJsonSchema,
    ValidationError,
)
from pydantic_core import to_jsonable_python
from sqlalchemy import String, cast

from .modular_page import NullControl
from .sync import GroupBarrier
from .utils import NoArgumentProvided, get_logger

logger = get_logger()


class LiveMessage(BaseModel):
    """One kind of message a game's pages send, such as a choice or a move.

    Set :attr:`type` to the message's name, declare its fields with type
    annotations, as in a `Pydantic <https://docs.pydantic.dev/>`_ model, and
    define :meth:`apply` to change the state. A page sends the message as
    ``{"type": "choose", "message": {"action": "rock"}}``.

    PsyNet checks each message before :meth:`apply` runs, and rejects one
    with a field missing, an extra field, or a field of the wrong type. The
    sender's page gets the reason. The check is strict: ``"1"`` isn't
    accepted as a number, nor ``1`` as text, and a number field of the
    message itself can't be ``NaN`` or infinite.

    A field can have any type Pydantic reads from JSON, such as a ``tuple``,
    an ``Enum``, a ``datetime`` or another Pydantic model, and in
    :meth:`apply` it holds a value of that type. The state holds only plain
    data, so a field stored there is converted when :meth:`apply` returns
    (:class:`LiveSession` lists the conversions), and a comparison with the
    state compares like with like:

    ::

        from dallinger.realtime import Reject


        class Move(LiveMessage):
            type = "move"
            to: tuple[int, int]

            def apply(self, game, state, player_id, now):
                # The state holds a list, and a list never equals a tuple.
                if state["positions"][player_id] == list(self.to):
                    raise Reject("You're already there.")
                state["positions"][player_id] = self.to

    In the same way, compare an enum field's ``.value`` with the state, and
    turn a stored date back into a datetime with
    ``datetime.fromisoformat(state["deadline"])``. Until :meth:`apply`
    returns, a value it has just stored is unchanged.

    To test a message, pass it to the game as a page would, with ``Sent``
    from ``dallinger.realtime``, as in
    ``game.apply(state, "1", {"type": "choose", "message": {"action": "rock"}},
    0, Sent())``.
    """

    model_config = ConfigDict(allow_inf_nan=False)

    #: The name pages send this kind of message under, such as ``"choose"``.
    #: Each message type in a game needs its own.
    type: ClassVar[str | None] = None

    def apply(self, game, state, player_id, now):
        """Change the game's state for this message.

        Change ``state`` in place. To refuse the message, such as a move
        that's against the rules, raise :class:`~dallinger.realtime.Reject`
        with a reason. The sender's page gets the reason, and the state stays
        as it was.

        Parameters
        ----------

        game
            The game, for its settings or to call
            :meth:`~LiveSession.queue_effect`.

        state
            The session's state.

        player_id
            The sender's player id.

        now
            When the message arrived, in seconds since the session started.
        """
        raise NotImplementedError

    @classmethod
    def saved_messages(cls, session_id):
        """Return the messages of this type saved for a session, in the order
        the game applied them, as :class:`SavedMessage` objects.

        A message sent with this :attr:`type` whose fields can't be read,
        such as one the game rejected for them, is included with ``message``
        ``None``. :meth:`LiveSession.saved_messages` returns all of a
        session's messages, and says when a session's record is complete.

        Parameters
        ----------

        session_id
            The session's id, as :func:`live_session_id` returns it.

        Raises
        ------

        KeyError
            If there is no session ``session_id``.

        ValueError
            If the session's game doesn't list this message type in its
            :attr:`~LiveSession.messages`, or the game isn't defined because
            the module that defines it hasn't been imported.
        """
        channel = _session_channel(session_id)
        game_type = _live_session_types.get(channel)
        if game_type is None:
            raise ValueError(
                f"Session {session_id} is a session of {channel!r}, and no "
                "LiveSession with that channel is defined. Import the module "
                "that defines the game first."
            )
        listed = game_type._message_types.get(cls.type)
        # By name: Dallinger's tests run experiment.py again, which defines
        # the message type again.
        if not listed or _name(listed) != _name(cls):
            raise ValueError(
                f"Session {session_id} is a session of {channel!r}, which "
                f"doesn't list {cls.__name__} in its messages."
            )
        return _saved_messages(session_id, {cls.type: cls}, only_type=cls.type)


# The game methods that can change the state, which is converted after each.
_STATE_METHODS = ("apply", "tick", "on_join", "on_leave")

# Set while a state method runs, so one that calls another, as through
# super() or from initial_state, converts once, after the outermost call.
# Converting rebuilds every dict and list in the state, which would cut off
# references the outer call still holds.
_changing_state = contextvars.ContextVar("_changing_state", default=False)


def _run_outermost(method, *args, **kwargs):
    # In a copy of the context, so nothing has to unset the flag, even when
    # Dallinger's time limit interrupts the call.
    def run():
        _changing_state.set(True)
        return method(*args, **kwargs)

    return contextvars.copy_context().run(run)


def _stores_json(method):
    @functools.wraps(method)
    def convert_state(self, state, *args, **kwargs):
        if _changing_state.get():
            method(self, state, *args, **kwargs)
            return
        _run_outermost(method, self, state, *args, **kwargs)
        if not self.convert_state_to_json:
            return
        converted = _to_json(state, f"{type(self).__name__}.{method.__name__}")
        # Changed in place, since Dallinger keeps the state object.
        if isinstance(state, dict):
            state.clear()
            state.update(converted)
        elif isinstance(state, list):
            state[:] = converted

    convert_state.converts_state = True
    return convert_state


def _returns_json(method):
    @functools.wraps(method)
    def convert_state(self, *args, **kwargs):
        if _changing_state.get():
            return method(self, *args, **kwargs)
        state = _run_outermost(method, self, *args, **kwargs)
        if not self.convert_state_to_json:
            return state
        return _to_json(state, f"{type(self).__name__}.{method.__name__}")

    convert_state.converts_state = True
    return convert_state


def _to_json(state, what):
    try:
        return to_jsonable_python(state)
    except (ValueError, TypeError) as error:
        raise ValueError(
            f"After {what}, the state holds a value PsyNet can't convert to "
            f"JSON. {error}."
        ) from None


class LiveSession(RealtimeGame):
    """A game that a group plays in a live session.

    Set ``channel`` to a name for the game, list its message types in
    :attr:`messages`, and define ``initial_state`` and ``view``. Other
    methods, such as ``is_over`` and ``tick``, are optional, and Dallinger's
    :class:`~dallinger.realtime.RealtimeGame` documents them. A subclass of a
    game needs a ``channel`` of its own.

    **The state holds plain data**: what JSON can hold, which is dicts with
    string keys, lists, strings, numbers, booleans and ``None``. PsyNet
    converts anything else when ``initial_state`` returns, and after a
    message's :meth:`~LiveMessage.apply` or the game's ``tick``, ``on_join``
    or ``on_leave`` runs:

    - a tuple becomes a list, and a set a list in no fixed order, so store
      ``sorted(...)`` where the order matters
    - an enum member becomes its value
    - a date, time or datetime becomes a string such as
      ``"2026-11-02T09:30:00"``, and a timedelta one such as ``"PT1M30S"``
    - a Pydantic model becomes a dict
    - a ``Decimal`` or ``bytes`` value becomes a string
    - a dict key becomes a string, so ``{1: "a"}`` becomes ``{"1": "a"}`` and
      ``{(1, 2): "a"}`` becomes ``{"1,2": "a"}``. Player ids are already
      strings.

    A value PsyNet can't convert, such as an object of a class of your own,
    makes the session fail. So does ``math.inf`` or ``NaN``, which JSON can't
    hold: store ``None`` instead. :class:`LiveMessage` shows how to compare a
    message's fields with the converted state. A game with a very large
    state can turn the conversion off with :attr:`convert_state_to_json`.
    """

    #: The game's message types, each a :class:`LiveMessage` subclass with
    #: its own :attr:`~LiveMessage.type`.
    messages = []

    #: Whether PsyNet converts the state to plain data after each method that
    #: changes it. The conversion takes time in proportion to the size of the
    #: whole state, so a game with a very large state, such as a big grid,
    #: can set this to ``False``. It then stores only plain data itself, such
    #: as ``list(...)`` of a message's tuple field and an enum field's
    #: ``.value``. Anything else changes only when Dallinger next saves the
    #: state or rejects a message, which restores the state from plain data:
    #: a tuple then becomes a list and ``{1: "a"}`` becomes ``{"1": "a"}``.
    convert_state_to_json = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Resolved through the MRO, so methods from a mixin are wrapped too.
        for name, wrap in [
            *((name, _stores_json) for name in _STATE_METHODS),
            ("initial_state", _returns_json),
        ]:
            method = getattr(cls, name)
            if method is not getattr(RealtimeGame, name) and not getattr(
                method, "converts_state", False
            ):
                setattr(cls, name, wrap(method))
        cls._message_types = _index_message_types(cls)
        if cls.channel is not None:
            _register_live_session(cls)

    # Wrapped here, so __init_subclass__ doesn't copy a wrapper onto each
    # subclass, which would hide a later base's apply.
    @_stores_json
    def apply(self, state, player_id, message, now, sent):
        """Apply a page's message with its message type's
        :meth:`LiveMessage.apply`.

        Most games don't override this. A game that needs ``sent``, what the
        page reported about the message, such as when it sent it, can
        override it, read the message with :meth:`read_message`, and apply it
        itself.
        """
        self.read_message(message).apply(self, state, player_id, now)

    def queue_effect(self, name, payload):
        """Queue an effect, as
        :meth:`~dallinger.realtime.RealtimeGame.queue_effect` does, with the
        payload converted to plain data in the same way as the state. A
        message's fields can go in the payload as they are.
        """
        try:
            payload = to_jsonable_python(payload)
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"The {name!r} effect's payload holds a value PsyNet can't "
                f"convert to JSON. {error}."
            ) from None
        super().queue_effect(name, payload)

    def read_message(self, message):
        """Check a page's message and return it as a :class:`LiveMessage`.

        Avoid overriding this method, since :meth:`saved_messages` doesn't
        call it. A game that reads messages its own way, such as to accept an
        older shape of a message, plays by its own reading, but a message
        only that reading accepts comes back from :meth:`saved_messages` with
        ``message`` ``None``.

        Parameters
        ----------

        message
            What the page sent, such as
            ``{"type": "choose", "message": {"action": "rock"}}``.

        Raises
        ------

        ~dallinger.realtime.Reject
            If the ``type`` isn't one of :attr:`messages`, or the fields don't
            match it.
        """
        return _parse_message(self._message_types, message)

    @classmethod
    def saved_messages(cls, session_id):
        """Return the messages saved for a session of this game, in the order
        the game applied them, as :class:`SavedMessage` objects.

        The session's record is written a few seconds behind the game, so for
        a session that's still being played, this returns the messages
        written so far. The record is complete once the session's ending is
        saved, as it is on any page the participant reaches after the game
        page's ``onResultSaved``. The session's ``status`` in Dallinger's
        ``realtime_session`` table is then ``ended`` or ``failed``. A session
        can also fail because its record couldn't be saved. It then keeps
        only the messages saved before that, and its ``error`` says why. A
        game can leave some messages out of the record with
        :meth:`~dallinger.realtime.RealtimeGame.save_message`.

        Parameters
        ----------

        session_id
            The session's id, as :func:`live_session_id` returns it.

        Raises
        ------

        KeyError
            If there is no session ``session_id``.

        ValueError
            If the session is of another game.
        """
        channel = _session_channel(session_id)
        if channel != cls.channel:
            raise ValueError(
                f"Session {session_id} is a session of {channel!r}, "
                f"not {cls.channel!r}."
            )
        return _saved_messages(session_id, cls._message_types)


def _parse_message(message_types, message):
    if (
        not isinstance(message, dict)
        or not isinstance(message.get("type"), str)
        or not set(message) <= {"type", "message"}
    ):
        raise Reject('A message is an object with a "type" and a "message".')
    message_type = message_types.get(message["type"])
    if message_type is None:
        raise Reject(f"Unknown message type {message['type'][:50]!r}.")
    # JSON mode, as for what pages send: a list is accepted for a tuple.
    # Given here, strict and extra also reach fields that are models.
    try:
        return message_type.model_validate_json(
            json.dumps(message.get("message", {})), strict=True, extra="forbid"
        )
    except ValidationError as error:
        raise Reject(
            f"Invalid {message_type.type!r} message: {_problems(error)}."
        ) from None


@dataclasses.dataclass(frozen=True)
class SavedMessage:
    """A message that a player's page sent in a live session, as the
    session's record saved it. :meth:`LiveSession.saved_messages` and
    :meth:`LiveMessage.saved_messages` return them.
    """

    #: The message, as an instance of its :class:`LiveMessage` subclass, or
    #: ``None`` if what the page sent doesn't match any of the game's message
    #: types, as for a message rejected for its fields, or one saved before
    #: its message type changed. It's also ``None`` if the message type's own
    #: code, such as a validator, raises an error reading it, and PsyNet then
    #: logs a warning.
    message: LiveMessage | None

    #: What the page sent, such as
    #: ``{"type": "choose", "message": {"action": "rock"}}``.
    payload: object

    #: The sender's player id, which is their participant id as a string, as
    #: the game's methods receive it.
    player_id: str

    #: ``"accepted"``, ``"rejected"`` if the game raised
    #: :class:`~dallinger.realtime.Reject`, or ``"failed"`` if the game's code
    #: raised an error while handling it, or a message handled at the same
    #: time, which made the session fail.
    status: str

    #: The reason the game rejected the message, or ``None``.
    reason: object

    #: When the message arrived, in seconds since the session started. It's
    #: the ``now`` that :meth:`LiveMessage.apply` received.
    session_time: float

    #: When the message arrived, as a date and time in the server's local
    #: time, like a participant's ``creation_time``.
    receive_time: datetime.datetime

    #: The number the page gave the message. A page counts its messages up
    #: by one, from 1 when it loads.
    number: int | None

    #: The browser's clock when the page sent the message, in seconds since
    #: 1970.
    browser_time: float | None

    #: The session time of the view the page was showing when it sent the
    #: message.
    view_time: float | None


def _game_channel(session_id):
    # game_type isn't nullable, so None means there's no such row.
    return db.session.query(RealtimeSession.game_type).filter_by(id=session_id).scalar()


def _session_channel(session_id):
    channel = _game_channel(session_id)
    if channel is None:
        raise KeyError(session_id)
    return channel


# Labelled as SavedMessage's fields.
_SAVED_MESSAGE_COLUMNS = [
    RealtimeEvent.payload,
    cast(RealtimeEvent.participant_id, String).label("player_id"),
    RealtimeEvent.status,
    RealtimeEvent.reason,
    RealtimeEvent.session_time,
    RealtimeEvent.receive_time,
    RealtimeEvent.number,
    RealtimeEvent.browser_time,
    RealtimeEvent.view_time,
]


def _saved_messages(session_id, message_types, only_type=None):
    query = db.session.query(*_SAVED_MESSAGE_COLUMNS).filter_by(
        session_id=session_id, event_type="message"
    )
    if only_type is not None:
        query = query.filter(RealtimeEvent.payload["type"].astext == only_type)
    saved = []
    errors = []
    for row in query.order_by(RealtimeEvent.sequence):
        try:
            message = _parse_message(message_types, row.payload)
        except Reject:
            message = None
        # Pydantic passes on a validator's errors other than ValueError and
        # AssertionError. One would stop the whole read, so it's logged.
        except Exception as error:
            message = None
            errors.append(error)
        saved.append(SavedMessage(message=message, **row._asdict()))
    if errors:
        logger.warning(
            "%d of session %s's saved messages came back with message None, "
            "because their message type raised an error reading them. The "
            "first error:",
            len(errors),
            session_id,
            exc_info=errors[0],
        )
    return saved


_MAX_PROBLEMS = 5


def _problems(error):
    errors = error.errors(include_url=False)
    problems = []
    for item in errors[:_MAX_PROBLEMS]:
        where = ".".join(str(part) for part in item["loc"])
        problems.append(f"{where}: {item['msg']}" if where else item["msg"])
    if len(errors) > _MAX_PROBLEMS:
        problems.append(f"and {len(errors) - _MAX_PROBLEMS} more")
    return "; ".join(problems)


def _index_message_types(game_type):
    by_type = {}
    for message_type in game_type.messages:
        if not (
            isinstance(message_type, type) and issubclass(message_type, LiveMessage)
        ):
            raise TypeError(
                f"{game_type.__name__}.messages lists {message_type!r}, "
                "which isn't a LiveMessage subclass."
            )
        if "type" in message_type.model_fields:
            raise TypeError(
                f"{message_type.__name__}.type has an annotation, which makes it "
                'a field. Set it without one, as in type = "choose".'
            )
        name = message_type.type
        if not isinstance(name, str) or not name:
            raise TypeError(f"{message_type.__name__}.type must be a non-empty string.")
        if message_type.apply is LiveMessage.apply:
            raise TypeError(f"{message_type.__name__} must define apply.")
        try:
            message_type.model_json_schema()
        except PydanticInvalidForJsonSchema as error:
            raise TypeError(
                f"{message_type.__name__} has a field of a type Pydantic can't "
                f"read from JSON. {str(error).splitlines()[0]}"
            ) from None
        if name in by_type:
            raise ValueError(
                f"{by_type[name].__name__} and {message_type.__name__} "
                f"both have the type {name!r}."
            )
        by_type[name] = message_type
    return by_type


# Every LiveSession subclass that sets a channel, by channel.
_live_session_types = {}


def _register_live_session(game_type):
    channel = game_type.channel
    existing = _live_session_types.get(channel)
    # Dallinger's tests run experiment.py again, and its verification imports
    # a copy of it under the same module name.
    if existing is not None and _name(existing) != _name(game_type):
        if existing.__qualname__ == game_type.__qualname__:
            raise ValueError(
                f"{game_type.__qualname__} is defined in both {existing.__module__} "
                f"and {game_type.__module__}, with the channel {channel!r}. If "
                "that is one file imported under two names, import it one way."
            )
        raise ValueError(
            f"{existing.__name__} and {game_type.__name__} both use the channel "
            f"{channel!r}. A subclass of a game needs a channel of its own."
        )
    _live_session_types[channel] = game_type


def _name(game_type):
    return game_type.__module__, game_type.__qualname__


class LiveSessionInitializer(GroupBarrier):
    """Starts a live session for each group that reaches this point in the
    timeline.

    Like a :class:`~psynet.sync.GroupBarrier`, it waits for every member of
    the participant's group to arrive. It then starts a session of
    ``game_type`` with the members as its players, and the group moves on
    together. A later page finds the session with :func:`live_session_id`. A
    group that arrives again, for example in a loop, plays a new session.

    Parameters
    ----------

    id_
        A name for this initializer, which pages pass to
        :func:`live_session_id` to find the group's session.

    group_type
        The ``group_type`` of the :class:`~psynet.sync.Grouper` whose groups
        play the game.

    game_type
        The game the group plays, a :class:`LiveSession` subclass. Define it
        at the top level of a file, such as ``experiment.py``, not inside a
        function or another class.

    **kwargs
        Any other parameter of :class:`~psynet.sync.GroupBarrier`, such as
        ``max_wait_time``, except ``on_release``, which the initializer uses
        to start the session.
    """

    def __init__(self, id_: str, group_type: str, game_type, **kwargs):
        if not (isinstance(game_type, type) and issubclass(game_type, LiveSession)):
            raise TypeError(
                f"game_type must be a LiveSession subclass, not {game_type!r}."
            )
        if game_type.channel is None:
            raise TypeError(
                f"{game_type.__name__} has no channel, so it can't be played. "
                "Set its channel to a name for the game."
            )
        super().__init__(
            id_=id_, group_type=group_type, on_release=_start_live_session, **kwargs
        )
        self.game_type = game_type

    def receive_participant(self, participant):
        # So that a group that dissolves here leaves no earlier visit's session.
        if participant.live_sessions:
            participant.live_sessions.pop(self.id, None)
        super().receive_participant(participant)


def _start_live_session(participants, barrier):
    session_id = create_realtime_session(
        barrier.game_type, [member.id for member in participants]
    )
    for member in participants:
        member.live_sessions = {**(member.live_sessions or {}), barrier.id: session_id}


class LiveSessionControl(NullControl):
    """The part of a page where the participant plays the session their
    group started at a :class:`LiveSessionInitializer`.

    Give it the initializer's id, and give the page a JavaScript file that
    plays the game, listed in its ``js_page_modules``:

    ::

        ModularPage(
            "rock_paper_scissors",
            Prompt(tags.div(tags.p(id="status"), ...)),
            LiveSessionControl("rock_paper_scissors"),
            js_page_modules=["/static/rock_paper_scissors.js"],
            time_estimate=30,
        )

    The JavaScript plays through ``psynet.liveSession``:

    - ``send(type, message)`` sends the game the :class:`LiveMessage` with
      that ``type``, and returns its number, or ``undefined`` once the
      page's connection is closed or refused.
    - ``onView(callback)`` calls ``callback`` with each new view, what the
      game's ``view`` returns for this player.
    - ``onRejected(callback)`` calls ``callback`` with the number of each
      message the game rejected and the reason.
    - ``onEnded(callback)`` calls ``callback`` once the session ends, with
      why it ended and the player's final view.
    - ``onResultSaved(callback)`` calls ``callback`` once the session's
      result has been saved.
    - ``onRefused(callback)`` calls ``callback`` with the close code and
      reason if the server refuses the page's connection.
    - ``hasSession`` says whether the group started a session at the
      initializer. Without one, the other methods throw an error.
    - ``socket`` is the page's Dallinger socket, for anything else, such as
      ``serverTime``.

    :doc:`/code/multiplayer/live_sessions` has a full example, and the cases
    a game page should allow for, such as a participant with no session or
    a reload.

    Parameters
    ----------

    initializer_id
        The ``id_`` of the :class:`LiveSessionInitializer` that started the
        session.

    bot_response
        What a bot answers on the page, as for any control.

    buttons
        Any extra buttons, as for any control.

    show_next_button
        Whether the page has a Next button.
    """

    def __init__(
        self,
        initializer_id,
        *,
        bot_response=NoArgumentProvided,
        buttons=None,
        show_next_button=True,
    ):
        super().__init__(
            bot_response=bot_response,
            buttons=buttons,
            show_next_button=show_next_button,
        )
        self.initializer_id = initializer_id

    def get_render_js_vars(self, experiment, participant):
        session_id = live_session_id(participant, self.initializer_id)
        return {
            "liveSession": {
                "initializerId": self.initializer_id,
                "sessionId": session_id,
                "gameChannel": (
                    None if session_id is None else _game_channel(session_id)
                ),
            }
        }


def live_session_id(participant, initializer_id):
    """Return the id of the session that ``participant``'s group started at
    the :class:`LiveSessionInitializer` with the id ``initializer_id``.

    Returns ``None`` if the group hasn't started one there since the
    participant last arrived, for example because the group broke up while
    it waited.
    """
    return (participant.live_sessions or {}).get(initializer_id)

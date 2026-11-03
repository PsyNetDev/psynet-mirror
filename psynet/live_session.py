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
on together. A page after it finds the session with :func:`live_session_id`.

::

    timeline = Timeline(
        SimpleGrouper(group_type="pair", initial_group_size=2),
        LiveSessionInitializer(
            id_="rock_paper_scissors",
            group_type="pair",
            game_type=RockPaperScissors,
        ),
        ...
    )

Define each game, or import it, before the experiment class. PsyNet then
adds it to the experiment's ``realtime_games``, so you don't list it there.
"""

import functools
import json
from typing import ClassVar

from dallinger.realtime import RealtimeGame, Reject, create_realtime_session
from pydantic import (
    BaseModel,
    ConfigDict,
    PydanticInvalidForJsonSchema,
    ValidationError,
)
from pydantic_core import PydanticSerializationError, to_jsonable_python

from .sync import GroupBarrier


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

        :param game: the game, for its settings or to call
            :meth:`~dallinger.realtime.RealtimeGame.queue_effect`
        :param state: the session's state
        :param player_id: the sender's player id
        :param now: when the message arrived, in seconds since the session
            started
        """
        raise NotImplementedError


# The game methods that can change the state, which is converted after each.
_STATE_METHODS = ("apply", "tick", "on_join", "on_leave")


def _stores_json(method):
    @functools.wraps(method)
    def convert_state(self, state, *args, **kwargs):
        method(self, state, *args, **kwargs)
        if not self.convert_state_to_json:
            return
        converted = _to_json(state, f"{type(self).__name__}.{method.__name__}")
        # Changed in place, since Dallinger keeps the state object.
        if isinstance(state, dict):
            state.clear()
            state.update(converted)
        elif isinstance(state, list):
            state[:] = converted

    return convert_state


def _returns_json(method):
    @functools.wraps(method)
    def convert_state(self, *args, **kwargs):
        state = method(self, *args, **kwargs)
        if not self.convert_state_to_json:
            return state
        return _to_json(state, f"{type(self).__name__}.{method.__name__}")

    return convert_state


def _to_json(state, what):
    try:
        return to_jsonable_python(state)
    except PydanticSerializationError as error:
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

    - a tuple or a set becomes a list
    - an enum member becomes its value
    - a date, time or datetime becomes a string such as
      ``"2026-11-02T09:30:00"``, and a timedelta one such as ``"PT1M30S"``
    - a Pydantic model becomes a dict
    - a dict key becomes a string, so ``{1: "a"}`` becomes ``{"1": "a"}``.
      Player ids are already strings.

    A value PsyNet can't convert, such as an object of a class of your own,
    makes the session fail. :class:`LiveMessage` shows how to compare a
    message's fields with the converted state. A game with a very large
    state can turn the conversion off with :attr:`convert_state_to_json`.
    """

    #: The game's message types, each a :class:`LiveMessage` subclass with
    #: its own :attr:`~LiveMessage.type`.
    messages = []

    #: Whether PsyNet converts the state to plain data after each method that
    #: changes it. The conversion takes time in proportion to the size of the
    #: whole state, which for a very large state, such as a big grid, is tens
    #: of milliseconds each time. Such a game can set this to ``False``, and
    #: then must store only plain data itself: ``list(self.to)``, not
    #: ``self.to``, and ``self.colour.value``, not ``self.colour``. A tuple
    #: it stores comes back as a list only after Dallinger next saves the
    #: state, so a game that stores one can behave differently before and
    #: after a save.
    convert_state_to_json = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name in _STATE_METHODS:
            if name in cls.__dict__:
                setattr(cls, name, _stores_json(cls.__dict__[name]))
        if "initial_state" in cls.__dict__:
            cls.initial_state = _returns_json(cls.__dict__["initial_state"])
        cls._message_types = _index_message_types(cls)
        if cls.channel is not None:
            _register_live_session(cls)

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

    def read_message(self, message):
        """Check a page's message and return it as a :class:`LiveMessage`.

        :param message: what the page sent, such as
            ``{"type": "choose", "message": {"action": "rock"}}``
        :raises ~dallinger.realtime.Reject: if the ``type`` isn't one of
            :attr:`messages`, or the fields don't match it
        """
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("type"), str)
            or not set(message) <= {"type", "message"}
        ):
            raise Reject('A message is an object with a "type" and a "message".')
        message_type = self._message_types.get(message["type"])
        if message_type is None:
            raise Reject(f"Unknown message type {message['type']!r}.")
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


def _problems(error):
    problems = []
    for item in error.errors(include_url=False):
        where = ".".join(str(part) for part in item["loc"])
        problems.append(f"{where}: {item['msg']}" if where else item["msg"])
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


def live_session_id(participant, initializer_id):
    """Return the id of the session that ``participant``'s group started at
    the :class:`LiveSessionInitializer` with the id ``initializer_id``.

    Returns ``None`` if the group hasn't started one there since the
    participant last arrived, for example because the group broke up while
    it waited.
    """
    return (participant.live_sessions or {}).get(initializer_id)

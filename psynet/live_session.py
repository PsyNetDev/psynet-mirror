"""Live sessions: games that a group of participants play together in real
time, such as a negotiation, a coordination game or a game on a shared board.

A game is a :class:`LiveSession` subclass, with a :class:`LiveMessage`
subclass for each kind of message its pages send. A
:class:`LiveSessionInitializer` in the timeline starts a session for each
group that reaches it, and a page with a :class:`LiveSessionControl` plays
it. :doc:`/code/multiplayer/live_sessions` walks through a whole game.
"""

import contextvars
import dataclasses
import datetime
import functools
import json
from typing import ClassVar, Literal

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

from .bot import Bot
from .modular_page import NullControl
from .sync import GroupBarrier
from .utils import get_logger

logger = get_logger()


class LiveMessage(BaseModel):
    """One kind of message a game's pages send, such as a choice or a move.

    Set :attr:`type` to the message's name, declare its fields with type
    annotations, as in a `Pydantic <https://docs.pydantic.dev/>`_ model, and
    define :meth:`apply` to change the state. A page sends the message as
    ``{"type": "choose", "message": {"action": "rock"}}``.

    PsyNet checks each message strictly before :meth:`apply` runs, and
    rejects one whose fields don't match. A field can have any type Pydantic
    reads from JSON, such as a tuple, an enum or a datetime.
    :doc:`/code/multiplayer/live_sessions` shows how to compare a field with
    the state, which holds only plain data, and how to test a message.
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
        ``None``.

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
        if not listed or not _same_definition(listed, cls):
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


def _converts_outermost_call(method, convert):
    """Wrap a state method so that ``convert(self, result, args)`` runs after
    the outermost call only."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if _changing_state.get():
            return method(self, *args, **kwargs)

        # In a copy of the context, so nothing has to unset the flag, even
        # when Dallinger's time limit interrupts the call.
        def run():
            _changing_state.set(True)
            return method(self, *args, **kwargs)

        result = contextvars.copy_context().run(run)
        if not self.convert_state_to_json:
            return result
        return convert(self, result, args)

    wrapper._psynet_wrapper = True
    return wrapper


def _stores_json(method):
    def convert_in_place(self, result, args):
        state = args[0]
        converted = _to_json(state, f"{type(self).__name__}.{method.__name__}")
        # Changed in place, since Dallinger keeps the state object.
        if isinstance(state, dict):
            state.clear()
            state.update(converted)
        elif isinstance(state, list):
            state[:] = converted

    return _converts_outermost_call(method, convert_in_place)


def _returns_json(method):
    def convert_returned(self, state, args):
        return _to_json(state, f"{type(self).__name__}.{method.__name__}")

    return _converts_outermost_call(method, convert_returned)


def _sends_message(method):
    @functools.wraps(method)
    def send(self, *args, **kwargs):
        message = method(self, *args, **kwargs)
        # A bot calling super().bot() reaches its parent's wrapper, which
        # leaves the message for the outermost one.
        if type(self).bot is not send or not isinstance(message, LiveMessage):
            return message
        sent = {
            "type": message.type,
            "message": message.model_dump(mode="json", by_alias=True),
        }
        # No page sees a bot's rejections, so a message the game can't read
        # fails the session here.
        try:
            read = self.read_message(sent)
        except Reject as rejection:
            problem = rejection.reason
        else:
            if read == message:
                return sent
            problem = f"It reads back as {read!r}."
        raise TypeError(
            f"{type(self).__name__}.bot returned {message!r}, which the game "
            f"can't read as it is. {problem} A bot can also return what a page "
            "sends, as a dict."
        )

    send._psynet_wrapper = True
    return send


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
    :attr:`messages`, and define ``initial_state``, ``view`` and ``bot``,
    which plays for bots, as in ``psynet test``. Dallinger's
    :class:`~dallinger.realtime.RealtimeGame` documents these and the
    optional methods, such as ``is_over`` and ``tick``. A subclass of a game
    needs a ``channel`` of its own.

    The state holds only plain data, what JSON can hold. PsyNet converts
    anything else, such as a tuple or an enum member, after each method that
    changes the state, and a value it can't convert, or ``NaN``, makes the
    session fail. :doc:`/code/multiplayer/live_sessions` lists the
    conversions.
    """

    #: The game's message types, each a :class:`LiveMessage` subclass with
    #: its own :attr:`~LiveMessage.type`.
    messages = []

    #: Whether PsyNet converts the state to plain data after each method that
    #: changes it. A game with a very large state can set it to ``False`` to
    #: save the time the conversion takes. It then has to store only plain
    #: data itself.
    convert_state_to_json = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Resolved through the MRO, so methods from a mixin are wrapped too.
        for name, wrap in [
            *((name, _stores_json) for name in _STATE_METHODS),
            ("initial_state", _returns_json),
            ("bot", _sends_message),
        ]:
            method = getattr(cls, name)
            if method is not getattr(RealtimeGame, name) and not getattr(
                method, "_psynet_wrapper", False
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

        The record is written a few seconds behind the game, so for a
        session that's still being played, this returns the messages written
        so far. :doc:`/code/multiplayer/live_sessions` says when the record
        is complete.

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
    """A message that a player's page, or a bot, sent in a live session, as
    the session's record saved it. :meth:`LiveSession.saved_messages` and
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
    status: Literal["accepted", "rejected", "failed"]

    #: The reason the game rejected the message, or ``None``.
    reason: object

    #: When the message arrived, in seconds since the session started. It's
    #: the ``now`` that :meth:`LiveMessage.apply` received.
    session_time: float

    #: When the message arrived, as a date and time in the server's local
    #: time, like a participant's ``creation_time``.
    receive_time: datetime.datetime

    #: The number the page gave the message. A page counts its messages up
    #: by one, from 1 when it loads, and a bot from 1 when the session starts.
    number: int | None

    #: The browser's clock when the page sent the message, in seconds since
    #: 1970. For a bot's message, it's the server's clock.
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


def live_session_game_types():
    """Return every :class:`LiveSession` subclass that has a ``channel``,
    which PsyNet adds to the experiment's ``realtime_games``."""
    return list(_live_session_types.values())


def _register_live_session(game_type):
    channel = game_type.channel
    existing = _live_session_types.get(channel)
    if existing is not None and not _same_definition(existing, game_type):
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


def _same_definition(first, second):
    # Dallinger's tests run experiment.py again, and its verification imports
    # a copy of it under the same module name, defining its classes again.
    return (first.__module__, first.__qualname__) == (
        second.__module__,
        second.__qualname__,
    )


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
        The game the group plays, a :class:`LiveSession` subclass with a
        ``bot`` method. Define it at the top level of a file, such as
        ``experiment.py``, not inside a function or another class.

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
        if game_type.bot is RealtimeGame.bot:
            raise TypeError(
                f"{game_type.__name__} has no bot method, so its bots, such as "
                "those of psynet test, would never move. Define bot to return "
                "a bot's next message."
            )
        super().__init__(
            id_=id_,
            group_type=group_type,
            on_release=LiveSessionInitializer._release,
            **kwargs,
        )
        self.game_type = game_type

    def receive_participant(self, participant):
        # So that a group that dissolves here leaves no earlier visit's session.
        _set_live_session_id(participant, self.id, None)
        super().receive_participant(participant)

    # on_release has to be importable by name, and gets the barrier rebuilt
    # from its saved settings.
    @staticmethod
    def _release(participants, barrier):
        barrier._start_session(participants)

    def _start_session(self, participants):
        session_id = create_realtime_session(
            self.game_type,
            [member.id for member in participants],
            bots=[member.id for member in participants if isinstance(member, Bot)],
        )
        for member in participants:
            _set_live_session_id(member, self.id, session_id)


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

    The JavaScript plays through ``psynet.liveSession``, which
    :doc:`/code/multiplayer/live_sessions` describes, with the cases a game
    page should allow for.

    Parameters
    ----------

    initializer_id
        The ``id_`` of the :class:`LiveSessionInitializer` that started the
        session.

    **kwargs
        Any other parameter of :class:`~psynet.modular_page.Control`, such as
        ``show_next_button``.
    """

    def __init__(self, initializer_id, **kwargs):
        super().__init__(**kwargs)
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
    return _live_session_ids(participant).get(initializer_id)


def _live_session_ids(participant):
    return participant.live_sessions or {}


def _set_live_session_id(participant, initializer_id, session_id):
    session_ids = {
        key: value
        for key, value in _live_session_ids(participant).items()
        if key != initializer_id
    }
    if session_id is not None:
        session_ids[initializer_id] = session_id
    participant.live_sessions = session_ids

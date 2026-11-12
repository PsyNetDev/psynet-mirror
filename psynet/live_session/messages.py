"""Message types, how PsyNet reads a page's message, and the messages a
session's record saved."""

import dataclasses
import datetime
import json
from typing import ClassVar, Literal

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession
from dallinger.realtime import Reject
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import String, cast

from ..utils import get_logger
from .registry import _live_session_type, _same_definition

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
            When the message arrived, in seconds on the session's clock,
            which starts when the group leaves the initializer.
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
        game_type = _session_game_type(session_id)
        listed = game_type._message_types.get(cls.type)
        if not listed or not _same_definition(listed, cls):
            raise ValueError(
                f"Session {session_id} is a session of {game_type.channel!r}, "
                f"which doesn't list {cls.__name__} in its messages."
            )
        return _saved_messages(session_id, {cls.type: cls}, only_type=cls.type)


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

    #: When the message arrived, in seconds on the session's clock, which
    #: starts when the group leaves the initializer. It's the ``now`` that
    #: :meth:`LiveMessage.apply` received.
    session_time: float

    #: When the message arrived, as a date and time in the server's local
    #: time, like a participant's ``creation_time``.
    receive_time: datetime.datetime

    #: The number the page gave the message. A page counts its messages up
    #: by one, from 1 when it loads, and a bot from 1.
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


def _session_game_type(session_id):
    channel = _session_channel(session_id)
    game_type = _live_session_type(channel)
    if game_type is None:
        raise ValueError(
            f"Session {session_id} is a session of {channel!r}, and no "
            "LiveSession with that channel is defined. Import the module "
            "that defines the game first."
        )
    return game_type


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

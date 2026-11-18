"""Message types, how PsyNet reads a page's message, and the messages a
game's record saved."""

import dataclasses
import datetime
import json
from typing import ClassVar, Literal

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession
from dallinger.realtime import Reject
from pydantic import BaseModel, ConfigDict, ValidationError

from ..utils import get_logger
from .registry import _live_game_class

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
    :doc:`/code/multiplayer/live_games` shows how to compare a field with
    the state, which holds only plain data, and how to test a message.
    """

    model_config = ConfigDict(allow_inf_nan=False)

    #: The name pages send this kind of message under, such as ``"choose"``.
    #: Each message type in a game needs its own.
    type: ClassVar[str | None] = None

    def apply(self, game, state, player, now):
        """Change the game's state for this message.

        Change ``state`` in place. To refuse the message, such as a move
        that's against the rules, raise :class:`~psynet.live_game.Reject`
        with a reason. The sender's page gets the reason, and the state stays
        as it was.

        Parameters
        ----------

        game
            The game, for example to call
            :meth:`~LiveGame.add_performance_reward`.

        state
            The game's state.

        player
            The sender's player number: 0 for the first player, 1 for the
            next, and so on.

        now
            When the message arrived, in seconds since the game started.
        """
        raise NotImplementedError

    def should_save(self, game, state, player, rejection):
        """Return whether to save this message in the game's record. By
        default, every message is saved.

        A game whose pages send many messages, such as a move many times a
        second, can leave out the ones its analysis won't need. Keep what
        the analysis needs, such as the coins a move collected, in the state
        or the outcome: ``should_save`` only decides whether the message
        itself is kept too. It runs after :meth:`apply`, on a new copy of
        the message.

        Parameters
        ----------

        game
            The game.

        state
            The state after :meth:`apply`, or, for a message the game
            rejected, the state as it was before.

        player
            The sender's player number.

        rejection
            The :class:`~psynet.live_game.Reject` that :meth:`apply`
            raised, or ``None`` if the game accepted the message.

        Returns
        -------

        ``True`` to save the message, or ``False`` to leave it out.
        """
        return True


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
    """A message that a player's page, or a bot, sent in a live game, as
    the game's record saved it. A game record's
    :attr:`~LiveGameRecord.messages` returns them.
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

    #: The sender's player number, as the game's methods receive it: 0 for
    #: the first player, 1 for the next, and so on.
    player: int

    #: The sender's participant id.
    participant_id: int

    #: ``"accepted"``, ``"rejected"`` if the game raised
    #: :class:`~psynet.live_game.Reject`, or ``"failed"`` if the game's code
    #: raised an error while handling it, or a message handled at the same
    #: time, which made the game fail.
    status: Literal["accepted", "rejected", "failed"]

    #: The reason the game rejected the message, or ``None``.
    reason: object

    #: When the message arrived, in seconds since the game started: the
    #: ``now`` that :meth:`LiveMessage.apply` received. It's negative for a
    #: message that arrived before the game started, such as a
    #: :class:`PlayerReady`, and ``None`` if the game never started.
    time: float | None

    #: When the message arrived, as a date and time in the server's local
    #: time, like a participant's ``creation_time``.
    receive_time: datetime.datetime

    #: The number the page gave the message. A page counts its messages up
    #: by one, from 1 when it loads, and a bot from 1.
    number: int | None

    #: The browser's clock when the page sent the message, in seconds since
    #: 1970. For a bot's message, it's the server's clock.
    browser_time: float | None

    #: The time of the view the page was showing when it sent the message,
    #: in seconds since the game started, like :attr:`time`.
    view_time: float | None

    @property
    def type(self) -> str | None:
        """The message's type, as the page sent it, such as ``"choose"``,
        including for a message whose :attr:`message` is ``None``. Pick out
        one type of message with it::

            choices = [m for m in game.messages if m.type == "choose"]
        """
        payload = self.payload
        return payload.get("type") if isinstance(payload, dict) else None


def _game_channel(session_id):
    # The game_type column isn't nullable, so None means there's no such row.
    return db.session.query(RealtimeSession.game_type).filter_by(id=session_id).scalar()


def _session_channel(session_id):
    channel = _game_channel(session_id)
    if channel is None:
        raise KeyError(session_id)
    return channel


def _session_game_class(session_id):
    channel = _session_channel(session_id)
    game_class = _live_game_class(channel)
    if game_class is None:
        raise ValueError(
            f"Game {session_id} is a game of {channel!r}, and no "
            "LiveGame with that name is defined. Import the module "
            "that defines the game first."
        )
    return game_class


# The effect PsyNet queues when the game starts, which records the start's
# Dallinger session time with the game's events.
_STARTED_EFFECT = "psynet_game_started"


def _session_participant_ids(session_id):
    """Return the participant ids of a game's players, in player order."""
    members = (
        db.session.query(RealtimeSession.members).filter_by(id=session_id).scalar()
    )
    if members is None:
        raise KeyError(session_id)
    return [int(member) for member in members]


def _game_started_at(session_id):
    """Return the Dallinger session time at which a game started, or None if
    it hasn't."""
    return (
        db.session.query(RealtimeEvent.session_time)
        .filter_by(session_id=session_id, event_type="effect", name=_STARTED_EFFECT)
        .scalar()
    )


# Labelled as SavedMessage's fields.
_SAVED_MESSAGE_COLUMNS = [
    RealtimeEvent.payload,
    RealtimeEvent.participant_id,
    RealtimeEvent.status,
    RealtimeEvent.reason,
    RealtimeEvent.session_time.label("time"),
    RealtimeEvent.receive_time,
    RealtimeEvent.number,
    RealtimeEvent.browser_time,
    RealtimeEvent.view_time,
]


def _saved_messages(session_id, message_types):
    query = db.session.query(*_SAVED_MESSAGE_COLUMNS).filter_by(
        session_id=session_id, event_type="message"
    )
    started_at = _game_started_at(session_id)
    participant_ids = _session_participant_ids(session_id)

    def game_time(session_time):
        if started_at is None or session_time is None:
            return None
        return session_time - started_at

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
        fields = row._asdict()
        fields["player"] = participant_ids.index(fields["participant_id"])
        fields["time"] = game_time(fields["time"])
        fields["view_time"] = game_time(fields["view_time"])
        saved.append(SavedMessage(message=message, **fields))
    if errors:
        logger.warning(
            "%d of game %s's saved messages came back with message None, "
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

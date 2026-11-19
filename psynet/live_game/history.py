"""A live game's history, read from the events Dallinger saves for it: the
moments the game recorded with LiveGame.record, and copies of its state.

A moment is an effect with PsyNet's own name, so Dallinger saves it, in
order and with its time, with the game's other events, and nothing else
writes it. Checkpoints are Dallinger's own, which it saves at the game's
``checkpoint_interval``, and the state at the end.
"""

from dataclasses import dataclass
from typing import Any, Optional

from dallinger import db
from dallinger.models import RealtimeEvent

from .messages import _game_started_at

# The name of the effect LiveGame.record queues.
_MOMENT_EFFECT = "psynet_moment"


@dataclass(frozen=True)
class LiveGameMoment:
    """A moment that a game recorded with :meth:`LiveGame.record`, as a game
    record's :attr:`~LiveGameRecord.moments` returns it.

    Attributes
    ----------

    name
        The moment's name.

    data
        What the game recorded about it.

    time
        When it happened, in seconds since the game started. It's negative
        for a moment before the game started, such as a player added during
        the ready step, and ``None`` if the game never started.
    """

    name: str
    data: Any
    time: Optional[float]


@dataclass(frozen=True)
class LiveGameCheckpoint:
    """A copy of a game's state, as a game record's
    :attr:`~LiveGameRecord.checkpoints` returns it.

    Attributes
    ----------

    state
        The state, without PsyNet's ``psynet`` entry.

    time
        When it was saved, in seconds since the game started. It's negative
        for a state saved before the game started, and ``None`` if the game
        never started.
    """

    state: Any
    time: Optional[float]


def _game_time_from(session_id):
    started_at = _game_started_at(session_id)

    def game_time(session_time):
        if started_at is None or session_time is None:
            return None
        return session_time - started_at

    return game_time


def _moments(session_id):
    query = db.session.query(
        RealtimeEvent.payload, RealtimeEvent.session_time
    ).filter_by(session_id=session_id, event_type="effect", name=_MOMENT_EFFECT)
    game_time = _game_time_from(session_id)
    return [
        LiveGameMoment(
            row.payload["name"], row.payload["data"], game_time(row.session_time)
        )
        for row in query.order_by(RealtimeEvent.sequence)
    ]


def _checkpoints(session_id):
    query = db.session.query(RealtimeEvent.state, RealtimeEvent.session_time).filter(
        RealtimeEvent.session_id == session_id,
        RealtimeEvent.event_type.in_(("checkpoint", "end")),
        RealtimeEvent.state.isnot(None),
    )
    game_time = _game_time_from(session_id)
    return [
        LiveGameCheckpoint(
            {key: value for key, value in row.state.items() if key != "psynet"},
            game_time(row.session_time),
        )
        for row in query.order_by(RealtimeEvent.sequence)
        if row.state is not None
    ]

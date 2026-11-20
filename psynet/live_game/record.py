"""A record of one live game, read from Dallinger's ``realtime_session`` row
and the events it saved for the game, and the queries the other modules use
to read them: the session's columns, the game's clock, and the moments and
checkpoints in its history.

A moment is an effect with PsyNet's own name, so Dallinger saves it, in
order and with its time, with the game's other events, and nothing else
writes it. Checkpoints are Dallinger's own, which it saves at the game's
``checkpoint_interval``, and the state at the end.
"""

import functools
from dataclasses import dataclass
from typing import Any, List, Optional

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession

from .registry import _live_game_class

# The effects PsyNet queues itself: when the game starts, which records the
# start's Dallinger session time with the game's events, for
# add_performance_reward, and for LiveGame.record.
_STARTED_EFFECT = "psynet_game_started"
_REWARD_EFFECT = "psynet_performance_reward"
_MOMENT_EFFECT = "psynet_moment"
_PSYNET_EFFECTS = (_STARTED_EFFECT, _REWARD_EFFECT, _MOMENT_EFFECT)


class LiveGameRecord:
    """One play of a live game, as the participant's
    :attr:`~psynet.participant.Participant.live_games` and
    :attr:`~psynet.participant.Participant.live_game_history`, a trial's
    :attr:`~psynet.trial.main.Trial.live_game` and a group's
    :attr:`~psynet.sync.SyncGroup.running_live_games` give it.

    ::

        game = participant.live_games["rock_paper_scissors"]
        if game.finished:
            game.answer       # this participant's answer
            game.outcome      # what the game's outcome returned
            game.messages     # every message, in order

    A record from a participant or a trial is that participant's, so it has
    their :attr:`answer` and :attr:`player` number. A group's record is the
    whole group's, and has only :attr:`answers`, each player's.

    Each attribute reads the database when you use it, so it's up to date
    while the game is played: read it again rather than keep its value.
    The game's record is saved a few seconds behind the game, and its
    result a few seconds after it ends, when the game page's
    ``onResultSaved`` runs.
    """

    # The realtime_session row the job writing the game's record holds, set
    # by _record_from_row, so the columns come from it without a query.
    _loaded_row = None

    def __init__(self, game_id: Optional[int], participant=None):
        self._id = game_id
        self._participant = participant

    def __repr__(self):
        return f"<LiveGameRecord {self._id}>"

    def __eq__(self, other):
        return isinstance(other, LiveGameRecord) and (
            other._id,
            other._participant_id(),
        ) == (self._id, self._participant_id())

    def __hash__(self):
        return hash((self._id, self._participant_id()))

    @property
    def id(self) -> Optional[int]:
        """The game's id, which is the id of Dallinger's ``realtime_session``
        row, and the ``session_id`` of its events, or ``None`` if no game
        started."""
        return self._id

    @property
    def game_class(self):
        """The :class:`~psynet.live_game.LiveGame` subclass that was played,
        or ``None`` if no game started."""
        return None if self._id is None else _session_game_class(self._id)

    @property
    def status(self) -> str:
        """``"not_started"`` if the participant's group didn't start a game,
        for example because it broke up while it waited; ``"running"`` until
        the game's result is saved; then ``"ended"``, or ``"failed"`` if the
        game's code raised an error, or its record couldn't be saved."""
        return "not_started" if self._id is None else self._row().status

    @property
    def finished(self) -> bool:
        """Whether the game ended with the reason ``"finished"``: through an
        ``is_over`` that returned ``True``, or at the end of its
        ``duration``. It's ``False`` for a game that ended early, such as
        because players left or it reached its ``timeout``, and for one
        whose ``end_reason`` gave a reason of its own, such as ``"deal"``."""
        row = self._row()
        return (
            row is not None and row.status == "ended" and row.end_reason == "finished"
        )

    @property
    def end_reason(self) -> Optional[str]:
        """Why the game ended: the ``reason`` that the game's ``outcome``
        received, such as ``"finished"``, ``"timeout"`` or ``"failed"``.
        It's ``None`` until the game has ended, or if its record couldn't be
        saved."""
        row = self._row()
        return None if row is None else row.end_reason

    @property
    def outcome(self) -> Any:
        """What the game's ``outcome`` returned. It's ``None`` until the
        game has ended, if its record couldn't be saved, or if the game
        failed and its ``outcome`` raised an error too."""
        row = self._row()
        return None if row is None else row.outcome

    @property
    def error(self) -> Optional[str]:
        """If the game failed, the error that made it fail, as Python prints
        it, with where in the code it happened. Otherwise ``None``."""
        row = self._row()
        return None if row is None else row.error

    @property
    def participant_ids(self) -> List[int]:
        """The participant ids of the game's players, in player order."""
        row = self._row()
        return [] if row is None else _player_ids(row.members)

    @property
    def record_complete(self) -> bool:
        """Whether the game's whole record was saved. It's ``False`` until
        the game has ended, and if saving the record failed, when the record
        keeps only the messages saved before the problem. A game that failed
        because of an error in the game's code still has a complete record,
        so check :attr:`status` to see whether the game failed."""
        row = self._row()
        return (
            row is not None and row.status != "running" and row.end_reason is not None
        )

    @property
    def player(self) -> Optional[int]:
        """The participant's player number in the game, as the game's
        methods see it, or ``None`` if no game started."""
        participant_id = self._own_participant_id("player")
        ids = self.participant_ids
        return ids.index(participant_id) if participant_id in ids else None

    @property
    def answer(self) -> Any:
        """The participant's answer on the game page, as the game's
        ``answer`` gave it. It's ``None`` until the page has saved it, or if
        no game started."""
        participant_id = self._own_participant_id("answer")
        return None if self._id is None else _stored_answer(participant_id, self._id)

    @property
    def answers(self) -> List[Any]:
        """Each player's answer, in player order, ``None`` for a player
        whose page hasn't saved one."""
        return [_stored_answer(pid, self._id) for pid in self.participant_ids]

    @property
    def messages(self):
        """The messages saved for the game, in the order the game applied
        them, as :class:`~psynet.live_game.SavedMessage` objects. They
        include each player's :class:`~psynet.live_game.PlayerReady`
        message, and the messages the game rejected, such as those sent
        before it started. Pick out one type of message by its ``type``::

            choices = [m for m in game.messages if m.type == "choose"]
        """
        from .messages import _saved_messages

        if self._id is None:
            return []
        return _saved_messages(self._id, self.game_class._message_types)

    @property
    def moments(self):
        """The moments the game recorded with
        :meth:`~psynet.live_game.LiveGame.record`, in order, as
        :class:`~psynet.live_game.LiveGameMoment` objects. Pick out one
        name with ``[m for m in game.moments if m.name == "catch"]``."""
        return [] if self._id is None else _moments(self._id)

    @property
    def checkpoints(self):
        """Copies of the game's state, as
        :class:`~psynet.live_game.LiveGameCheckpoint` objects, in order:
        those Dallinger saved while the game was played, at most every
        ``checkpoint_interval`` seconds (5 by default), and the state when
        the game ended. Each state is as the game's code sees it, without
        PsyNet's ``psynet`` entry. Use it to look back at a game, for example
        to check its code, and :meth:`~psynet.live_game.LiveGame.record` for
        what an analysis needs."""
        return [] if self._id is None else _checkpoints(self._id)

    def _participant_id(self):
        return None if self._participant is None else self._participant.id

    def _own_participant(self, attribute):
        if self._participant is None:
            raise AttributeError(
                f"A group's game record has no single {attribute}. "
                f"game.answers has each player's answer, in player order, and "
                f"a member's own record, from participant.live_games, has "
                f"their {attribute}."
            )
        return self._participant

    def _own_participant_id(self, attribute):
        return self._own_participant(attribute).id

    def _row(self):
        if self._id is None:
            return None
        if self._loaded_row is not None:
            return self._loaded_row
        return _session_columns(
            self._id, "status", "end_reason", "outcome", "error", "members"
        )


def _record_from_row(row):
    """Return the record of the game whose ``realtime_session`` row the job
    writing its record holds, which reads the columns from the row, with
    the job's changes, rather than from the database."""
    record = LiveGameRecord(row.id)
    record._loaded_row = row
    return record


def _stored_answer(participant_id, game_id):
    """Return the answer the participant's game page saved for the game
    ``game_id``, or None."""
    from ..participant import Participant

    # Read from the database, as _session_columns does, not from a copy of the
    # participant that the caller's database session already loaded.
    stored = (
        db.session.query(Participant.live_game_data)
        .filter_by(id=participant_id)
        .scalar()
    )
    for data in (stored or {}).values():
        for game in data.get("history", []):
            if game["id"] == game_id:
                return game["answer"]
    return None


class LiveGameFailed(RuntimeError):
    """Raised on a game page whose game failed, because the game's code
    raised an error, or its record couldn't be saved. PsyNet then handles it
    as any other error in the experiment: it records the error, with the
    game's own, and fails the participant with an error-recovery exit."""

    def __init__(self, game):
        self.game_id = game.id
        error = game.error or "Its record couldn't be saved."
        # The game's name, since a game can fail because its class is gone.
        super().__init__(
            f"Live game {game.id} ({_session_channel(game.id)}) failed, so its "
            f"players can't go on with it. The game's error:\n\n{error}"
        )


def _has_outcome(status, outcome):
    # A failed game has no outcome if its record couldn't be saved, or if
    # Dallinger couldn't get one from the game's outcome method.
    return status != "failed" or outcome is not None


def _player_ending(session_id, participant_id):
    """Return the reason and the outcome of a player's game that ended
    before the game did, as saved, or None."""
    return (
        db.session.query(RealtimeEvent.reason, RealtimeEvent.outcome)
        .filter_by(
            session_id=session_id,
            event_type="player_end",
            participant_id=participant_id,
        )
        .one_or_none()
    )


def _players_ended_early(session_id):
    """Return the participant ids of the players whose game ended before
    the game did."""
    return {
        participant_id
        for (participant_id,) in db.session.query(
            RealtimeEvent.participant_id
        ).filter_by(session_id=session_id, event_type="player_end")
    }


def _session_columns(session_id, *columns):
    """Return the named ``columns`` of a game's ``realtime_session`` row.

    Raises ``KeyError`` if there's no such row.
    """
    # Querying columns reads the row from the database, not a copy the
    # caller's database session already loaded.
    row = (
        db.session.query(*(getattr(RealtimeSession, column) for column in columns))
        .filter_by(id=session_id)
        .one_or_none()
    )
    if row is None:
        raise KeyError(session_id)
    return row


def _player_ids(members):
    """Return a session row's ``members`` as participant ids, in player
    order."""
    return [int(member) for member in members]


def _session_participant_ids(session_id):
    """Return the participant ids of a game's players, in player order."""
    return _player_ids(_session_columns(session_id, "members").members)


def _session_channel(session_id):
    return _session_columns(session_id, "game_type").game_type


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


def _game_started_at(session_id):
    """Return the Dallinger session time at which a game started, or None if
    it hasn't."""
    return (
        db.session.query(RealtimeEvent.session_time)
        .filter_by(session_id=session_id, event_type="effect", name=_STARTED_EFFECT)
        .scalar()
    )


def _game_time(started_at, session_time):
    """Return a Dallinger session time as the game's time, the seconds since
    the game started at ``started_at``, or None before it starts."""
    if started_at is None or session_time is None:
        return None
    return session_time - started_at


def _game_time_from(session_id):
    """Return a function that gives a session time of the game
    ``session_id`` as the game's time."""
    return functools.partial(_game_time, _game_started_at(session_id))


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

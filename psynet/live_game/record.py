"""A record of one live game, read from Dallinger's ``realtime_session`` row
and the events it saved for the game."""

from typing import Any, List, Optional

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession


class LiveGameRecord:
    """One play of a live game, as the participant's
    :attr:`~psynet.participant.Participant.live_games` and
    :attr:`~psynet.participant.Participant.live_game_history`, a group's
    :attr:`~psynet.sync.SyncGroup.running_live_games` and a round's
    :attr:`~psynet.sync.SyncGroupRound.live_game` give it.

    ::

        game = participant.live_games["rock_paper_scissors"]
        if game is not None and game.status == "ended":
            game.answer       # this participant's answer
            game.outcome      # what the game's outcome returned
            game.messages     # every message, in order

    Each attribute reads the database when you use it, so it's up to date
    while the game is played: read it again rather than keep its value.
    The game's record is saved a few seconds behind the game, and its
    result a few seconds after it ends, when the game page's
    ``onResultSaved`` runs.
    """

    def __init__(self, game_id: int, answer: Any = None):
        self._id = game_id
        self._answer = answer

    def __repr__(self):
        return f"<LiveGameRecord {self._id}>"

    def __eq__(self, other):
        return isinstance(other, LiveGameRecord) and other._id == self._id

    def __hash__(self):
        return hash(self._id)

    @property
    def id(self) -> int:
        """The game's id, which is the id of Dallinger's ``realtime_session``
        row, and the ``session_id`` of its events."""
        return self._id

    @property
    def game_class(self):
        """The :class:`~psynet.live_game.LiveGame` subclass that was played."""
        from .messages import _session_game_class

        return _session_game_class(self._id)

    @property
    def status(self) -> str:
        """``"running"`` until the game's result is saved, then ``"ended"``,
        or ``"failed"`` if the game's code raised an error, or the game
        couldn't be started or its record saved."""
        return self._row().status

    @property
    def end_reason(self) -> Optional[str]:
        """Why the game ended: the ``reason`` that the game's ``outcome``
        received, such as ``"finished"``, ``"timeout"`` or ``"failed"``.
        It's ``None`` while the game is running, or if its record couldn't
        be saved."""
        return self._row().end_reason

    @property
    def outcome(self) -> Any:
        """What the game's ``outcome`` returned. It's ``None`` while the game
        is running, if its record couldn't be saved, or if the game failed and
        its ``outcome`` raised an error too."""
        return self._row().outcome

    @property
    def error(self) -> Optional[str]:
        """If the game failed, the error that made it fail, as Python prints
        it, with where in the code it happened. Otherwise ``None``."""
        return self._row().error

    @property
    def participant_ids(self) -> List[int]:
        """The participant ids of the game's players, in player order, so
        ``participant_ids.index(participant.id)`` is a participant's player
        number."""
        return [int(member) for member in self._row().members]

    @property
    def record_complete(self) -> bool:
        """Whether the game's whole record was saved. It's ``False`` while
        the game is running, and if saving the record failed, when the record
        keeps only the messages saved before the problem. A game that failed
        because of an error in the game's code still has a complete record,
        so check :attr:`status` to see whether the game failed."""
        row = self._row()
        return row.status != "running" and row.end_reason is not None

    @property
    def answer(self) -> Any:
        """The participant's answer on the game page, as the game's
        ``answer`` gave it, or ``None`` before the page saved it. Only a
        record from the participant, such as
        :attr:`~psynet.participant.Participant.live_games`, has one; a record
        from a group or a round has ``None``."""
        return self._answer

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

        return _saved_messages(self._id, self.game_class._message_types)

    @property
    def moments(self):
        """The moments the game recorded with
        :meth:`~psynet.live_game.LiveGame.record`, in order, as
        :class:`~psynet.live_game.LiveGameMoment` objects. Pick out one
        name with ``[m for m in game.moments if m.name == "catch"]``."""
        from .history import _moments

        return _moments(self._id)

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
        from .history import _checkpoints

        return _checkpoints(self._id)

    def _row(self):
        # Querying columns reads the row from the database, not a copy the
        # caller's database session already loaded.
        row = (
            db.session.query(
                RealtimeSession.status,
                RealtimeSession.end_reason,
                RealtimeSession.outcome,
                RealtimeSession.error,
                RealtimeSession.members,
            )
            .filter_by(id=self._id)
            .one_or_none()
        )
        if row is None:
            raise KeyError(self._id)
        return row


def _game_ended(game_id):
    """Whether the game's result has been saved."""
    status = db.session.query(RealtimeSession.status).filter_by(id=game_id).scalar()
    if status is None:
        raise KeyError(game_id)
    return status != "running"


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

"""A record of one live game, read from Dallinger's ``realtime_session`` row
and the events it saved for the game."""

from typing import Any, List, Optional

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession


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
        from .messages import _session_game_class

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
        """Whether the game ended normally, through its ``is_over`` or at the
        end of its ``duration``, rather than early, such as because players
        left or it reached its ``timeout``."""
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
        return [] if row is None else [int(member) for member in row.members]

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
        participant = self._own_participant("answer")
        return None if self._id is None else _stored_answer(participant, self._id)

    @property
    def answers(self) -> List[Any]:
        """Each player's answer, in player order, ``None`` for a player
        whose page hasn't saved one."""
        from ..participant import Participant

        answers = []
        for participant_id in self.participant_ids:
            participant = db.session.get(Participant, participant_id)
            answers.append(_stored_answer(participant, self._id))
        return answers

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
        from .history import _moments

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
        from .history import _checkpoints

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


def _stored_answer(participant, game_id):
    """Return the answer the participant's game page saved for the game
    ``game_id``, or None."""
    from .play import _live_game_data

    if participant is None:
        return None
    for data in _live_game_data(participant).values():
        for game in data.get("history", []):
            if game["id"] == game_id:
                return game["answer"]
    return None


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

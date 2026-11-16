"""How a game ended, read from Dallinger's ``realtime_session`` row."""

from dataclasses import dataclass
from typing import Any, Literal, Optional

from dallinger import db
from dallinger.models import RealtimeSession


@dataclass(frozen=True)
class LiveGameResult:
    """How a live game ended, as :func:`live_game_result` returns it.

    Attributes
    ----------

    status
        ``"ended"``, or ``"failed"`` if the game's code raised an error, or
        the game couldn't be started or its record saved.

    end_reason
        Why the game ended. It's the ``reason`` that the game's
        ``outcome`` received, such as ``"finished"`` or ``"failed"``, or
        ``None`` if the game's record couldn't be saved.

    outcome
        The value that the game's ``outcome`` returned. It's ``None`` if the
        game's record couldn't be saved, or if the game failed and its
        ``outcome`` raised an error too.

    error
        If the game failed, the error that made it fail, as Python prints
        it, with where in the code it happened. Otherwise ``None``.

    participant_ids
        The participant ids of the game's players, in player order, so
        ``participant_ids.index(participant.id)`` is a participant's player
        number.
    """

    status: Literal["ended", "failed"]
    end_reason: Optional[str]
    outcome: Any
    error: Optional[str] = None
    participant_ids: tuple = ()

    @property
    def record_complete(self):
        """Whether the game's whole record was saved. It's ``False`` only
        if saving the record failed, and then the record keeps only the
        messages saved before the problem. A game that failed because of an
        error in the game's code still has a complete record, so check
        :attr:`status` to see whether the game failed.
        """
        return self.end_reason is not None


def live_game_result(game_id):
    """Return how the game ``game_id`` ended, as a
    :class:`LiveGameResult`, or ``None`` if it's still running.

    A game counts as running until its result is saved, a few seconds after
    the game ends. That's when the game page's ``onResultSaved`` runs.

    Raises
    ------

    KeyError
        If there is no game ``game_id``.
    """
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
        .filter_by(id=game_id)
        .one_or_none()
    )
    if row is None:
        raise KeyError(game_id)
    if row.status == "running":
        return None
    return LiveGameResult(
        row.status,
        row.end_reason,
        row.outcome,
        row.error,
        tuple(int(member) for member in row.members),
    )


def _has_outcome(status, outcome):
    # A failed game has no outcome if its record couldn't be saved, or if
    # Dallinger couldn't get one from the game's outcome method.
    return status != "failed" or outcome is not None

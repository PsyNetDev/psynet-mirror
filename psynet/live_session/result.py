"""How a session ended, read from Dallinger's ``realtime_session`` row."""

from dataclasses import dataclass
from typing import Any, Literal, Optional

from dallinger import db
from dallinger.models import RealtimeSession


@dataclass(frozen=True)
class LiveSessionResult:
    """How a live session ended, as :func:`live_session_result` returns it.

    Attributes
    ----------

    status
        ``"ended"``, or ``"failed"`` if the game's code raised an error, or
        the session couldn't be started or its record saved.

    end_reason
        Why the session ended. It's the ``reason`` that the game's
        ``outcome`` received, such as ``"finished"`` or ``"failed"``, or
        ``None`` if the session's record couldn't be saved.

    outcome
        The value that the game's ``outcome`` returned. It's ``None`` if the
        session's record couldn't be saved, or if the session failed and its
        ``outcome`` raised an error too.

    error
        If the session failed, the error that made it fail, as Python prints
        it, with where in the code it happened. Otherwise ``None``.
    """

    status: Literal["ended", "failed"]
    end_reason: Optional[str]
    outcome: Any
    error: Optional[str] = None

    @property
    def record_complete(self):
        """Whether the session's whole record was saved. It's ``False`` only
        if saving the record failed, and then the record keeps only the
        messages saved before the problem. A session that failed because of an
        error in the game's code still has a complete record, so check
        :attr:`status` to see whether the game failed.
        """
        return self.end_reason is not None


def live_session_result(session_id):
    """Return how the session ``session_id`` ended, as a
    :class:`LiveSessionResult`, or ``None`` if it's still running.

    A session counts as running until its ending is saved, a few seconds after
    the game ends. That's when the game page's ``onResultSaved`` runs.

    Raises
    ------

    KeyError
        If there is no session ``session_id``.
    """
    # Querying columns reads the row from the database, not a copy the
    # caller's database session already loaded.
    row = (
        db.session.query(
            RealtimeSession.status,
            RealtimeSession.end_reason,
            RealtimeSession.outcome,
            RealtimeSession.error,
        )
        .filter_by(id=session_id)
        .one_or_none()
    )
    if row is None:
        raise KeyError(session_id)
    if row.status == "running":
        return None
    return LiveSessionResult(row.status, row.end_reason, row.outcome, row.error)

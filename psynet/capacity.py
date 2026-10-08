"""Limit how many people take an open-link study at once.

Citizen-science studies shared through a public link (the ``generic`` and
``hotair`` recruiters) can attract more simultaneous visitors than the server
can serve. Past capacity every participant's pages slow down, including those
of people who are already halfway through. Setting the experiment variable
``max_concurrent_participants`` caps the number of active participants:
newcomers over the cap wait on the start page, which retries until a place
frees up. Returning participants are never refused, and nobody already in the
study is removed.

Design constraints:

* The decision belongs to :meth:`psynet.experiment.Experiment.accepts_new_participants`,
  which experiments may override with their own logic (for example a time
  window or a queue length). The cap is an experiment variable rather than a
  config option so that it can change while the study runs.
* The check runs only when a new participant would be created
  (``POST /participant``), before any database row exists, so a waiting
  visitor costs one cheap request per retry and leaves no trace in the data.
* A participant is *active* while they are working, have not failed, and have
  either joined or submitted a page within ``max_concurrent_participants_idle_s``.
  People who close the tab stop counting once that timeout passes, so no
  cleanup job is needed. Pages that run longer than the timeout without a
  submission (for example long videos or timeline holds) briefly stop counting.
* While the study is full, each web process remembers that for
  ``_FULL_CACHE_S`` seconds, so a crowd of retries does not query the database
  each time. Admissions are always re-checked, so the cache cannot admit extra
  people; simultaneous admissions can still overshoot the cap by a few
  participants.

Recruiters opt in through ``supports_max_concurrent_participants``; recruiters
that send paid participants (Prolific, Lucid) should limit concurrency through
their own places or quotas instead, because turning away someone who accepted
a paid place is unfair to them.
"""

import time
from datetime import datetime, timedelta

from dallinger import db
from flask import jsonify

STUDY_FULL_ERROR_CODE = "study_full"
_FULL_CACHE_S = 2.0
_RETRY_AFTER_S = 30

_full_until = 0.0


def count_active_participants(idle_timeout_s):
    """Count participants who are working and joined or submitted a page recently.

    Parameters
    ----------
    idle_timeout_s : float
        Participants with no page submission for this many seconds, and who
        joined longer ago than that, do not count.

    Returns
    -------
    int
        The number of active participants.
    """
    from sqlalchemy import exists, or_

    from .participant import Participant
    from .timeline import Response

    cutoff = datetime.now() - timedelta(seconds=idle_timeout_s)
    recent_response = exists().where(
        Response.participant_id == Participant.id,
        Response.creation_time > cutoff,
    )
    return (
        db.session.query(Participant.id)
        .filter(
            Participant.status == "working",
            Participant.failed.is_(False),
            or_(Participant.creation_time > cutoff, recent_response),
        )
        .count()
    )


def refuse_new_participant_if_full():
    """Return a 503 "study full" response if the study is at capacity, else ``None``.

    Called before ``POST /participant`` creates a participant; the decision
    comes from :meth:`~psynet.experiment.Experiment.accepts_new_participants`.
    """
    global _full_until

    from .experiment import get_experiment

    now = time.monotonic()
    if now >= _full_until:
        if get_experiment().accepts_new_participants():
            return None
        _full_until = now + _FULL_CACHE_S

    response = jsonify(
        status="error",
        error_code=STUDY_FULL_ERROR_CODE,
        message="The study is at capacity; please try again shortly.",
    )
    response.status_code = 503
    response.headers["Retry-After"] = str(_RETRY_AFTER_S)
    return response

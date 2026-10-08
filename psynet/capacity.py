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

* The decision belongs to :meth:`psynet.experiment.Experiment.is_at_capacity`,
  which experiments may override to measure load differently. It is only for
  load: newcomers are told the study is busy and retried automatically, which
  would mislead them if the study were closed instead. The cap is an
  experiment variable rather than a config option so that it can change while
  the study runs.
* The check runs only when a new participant would be created
  (``POST /participant`` and its path-style variant), before any database
  row exists, so a waiting visitor costs one cheap request per retry and
  leaves no trace in the data.
* A participant is *active* while they are working, have not failed, and have
  either joined or submitted a page in the last ``DEFAULT_IDLE_TIMEOUT_S`` seconds.
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
from flask import jsonify, request

STUDY_FULL_ERROR_CODE = "study_full"
_FULL_CACHE_S = 2.0
_RETRY_AFTER_S = 30
# Dallinger's two views that create a participant.
_PARTICIPANT_CREATION_ENDPOINTS = {"post_participant", "create_participant"}

DEFAULT_IDLE_TIMEOUT_S = 600

_full_until = 0.0


def is_valid_participant_limit(value):
    """Return whether ``value`` can be ``max_concurrent_participants``.

    Valid limits are ``None`` (no limit) and whole numbers of at least 0.
    """
    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )


def recruiter_supports_participant_limits(recruiter_class):
    """Return whether newcomers from ``recruiter_class`` may wait for a place.

    An unknown recruiter (``None``) counts as supporting limits.
    """
    return recruiter_class is None or getattr(
        recruiter_class, "supports_max_concurrent_participants", False
    )


def count_active_participants(idle_timeout_s=DEFAULT_IDLE_TIMEOUT_S):
    """Count participants who are working and joined or submitted a page recently.

    Parameters
    ----------
    idle_timeout_s : float
        Participants with no page submission for this many seconds, and who
        joined longer ago than that, do not count. Default: 600.

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

    Called before every request; acts only on requests that would create a
    participant, and only for recruiters that support waiting newcomers. The
    decision comes from :meth:`~psynet.experiment.Experiment.is_at_capacity`.
    """
    global _full_until

    from .experiment import get_experiment
    from .recruiters import configured_recruiter_class

    if request.endpoint not in _PARTICIPANT_CREATION_ENDPOINTS:
        return None
    try:
        recruiter_class = configured_recruiter_class()
    except NotImplementedError:
        recruiter_class = None
    if not recruiter_supports_participant_limits(recruiter_class):
        return None

    now = time.monotonic()
    if now >= _full_until:
        if not get_experiment().is_at_capacity():
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

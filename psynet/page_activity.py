"""Track when each participant's browser tab was last seen visible.

Barriers with ``fail_if_hidden_for`` use this to fail participants who leave
the waiting screen: minimise the window, switch to another tab, or close it.
Each ``POST /response`` for the participant's current page sent from a
visible tab records the time. The waiting screen polls about every two
seconds, so a visible waiting participant's record stays fresh, while a hidden
or closed tab stops updating it. One timestamp covers both cases.

The records live in Redis rather than the database because they change every
few seconds and must not take row locks: the waiting-page poll deliberately
keeps its database transaction read-only so it never blocks barrier releases.
If Redis is unavailable or a record can't be read, nobody counts as away, so
no participant is failed because of a server problem.
"""

import time

from dallinger.db import redis_conn
from redis.exceptions import RedisError

from .utils import get_logger

logger = get_logger()

_EXPIRE_SECONDS = 24 * 3600


def _key(participant_id):
    return f"psynet:page_activity:{participant_id}"


def record_page_activity(participant_id: int, visible: bool):
    """Record that this participant's tab was just seen, if it was visible."""
    if not visible:
        return
    try:
        redis_conn.set(_key(participant_id), time.time(), ex=_EXPIRE_SECONDS)
    except RedisError:
        logger.warning(
            "Could not record page activity for participant %s.",
            participant_id,
            exc_info=True,
        )


def away_participants(participants, *, since, for_seconds: float):
    """Return the participants whose tab hasn't been seen visible for ``for_seconds``.

    Parameters
    ----------
    participants
        Participants to check. Bots have no browser and are never away.
    since
        Mapping from participant ID to the epoch time from which absence
        counts, such as when they arrived at a barrier. A tab last seen
        visible before then counts as seen then.
    for_seconds
        How long a tab must have been hidden or closed.
    """
    from .bot import Bot

    browsers = [p for p in participants if not isinstance(p, Bot)]
    if not browsers:
        return []
    try:
        raw = redis_conn.mget([_key(p.id) for p in browsers])
    except RedisError:
        logger.warning("Could not read page activity; counting nobody as away.")
        return []
    now = time.time()
    away = []
    for participant, value in zip(browsers, raw):
        try:
            seen = float(value) if value is not None else 0.0
        except ValueError:
            logger.warning(
                "Unreadable page activity for participant %s; not counting them as away.",
                participant.id,
            )
            continue
        if now - max(seen, since[participant.id]) >= for_seconds:
            away.append(participant)
    return away

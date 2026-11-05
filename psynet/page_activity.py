"""Track whether participants' browsers are still open and visible.

Groupers use this to avoid grouping participants whose tab is in the
background or closed, who would otherwise hold up their new group. Each
``POST /response`` for the participant's current page records when the
browser was last seen and whether its tab was visible. Waiting pages poll
about every two seconds and report visibility changes at once, so a waiting
participant's record stays fresh.

The records live in Redis rather than the database because they change every
few seconds and must not take row locks: the waiting-page poll deliberately
keeps its database transaction read-only so it never blocks barrier releases.
Records expire after an hour. If Redis is unavailable, participants count as
active, so grouping degrades to the behavior without activity checks.
"""

import json
import time

from dallinger.db import redis_conn
from redis.exceptions import RedisError

from .utils import get_logger

logger = get_logger()

_EXPIRE_SECONDS = 3600


def _key(participant_id):
    return f"psynet:page_activity:{participant_id}"


def record_page_activity(participant_id: int, visible: bool):
    """Record that this participant's browser was just seen, and whether its tab was visible."""
    value = json.dumps({"seen": time.time(), "visible": bool(visible)})
    try:
        redis_conn.set(_key(participant_id), value, ex=_EXPIRE_SECONDS)
    except RedisError:
        logger.warning(
            "Could not record page activity for participant %s.",
            participant_id,
            exc_info=True,
        )


def active_participants(participants, within: float):
    """Return the participants whose visible browser was seen in the last ``within`` seconds.

    Bots have no browser and always count as active, as do participants
    with no record yet (for example just after a server restart).
    """
    from .bot import Bot

    browsers = [p for p in participants if not isinstance(p, Bot)]
    if not browsers:
        return list(participants)
    try:
        raw = redis_conn.mget([_key(p.id) for p in browsers])
    except RedisError:
        logger.warning("Could not read page activity; counting everyone as active.")
        return list(participants)
    records = {p.id: json.loads(value) for p, value in zip(browsers, raw) if value}
    now = time.time()

    def is_active(participant):
        record = records.get(participant.id)
        if isinstance(participant, Bot) or record is None:
            return True
        return record["visible"] and now - record["seen"] <= within

    return [p for p in participants if is_active(p)]

"""Read a performance test's measurements from the server's database.

:class:`~psynet.perf_test.runtime.PerformanceTester` records the largest
``Request``, ``AsyncProcess`` and participant IDs before a test and passes them
here afterwards, so measurements cover only the test window: requests logged
before the bots were told to stop and processes that started by then, plus the
wait of the oldest process still queued at the end.

A bot only succeeds if the experiment did not fail its participant: failed
participants keep the status ``approved`` (see :func:`_bot_outcome`). Each
result also records the row counts of the tables that grow as a study collects
data (:func:`database_rows`), because capacity can fall as they grow.

The functions here only query the database; they neither run bots nor format
output. Database imports stay inside the functions so that importing
:mod:`psynet.perf_test` does not need a configured experiment.
"""

import logging
import math
import re
import time
from collections import Counter

from psynet.perf_test.results import (
    PROCESS_STAT_KEYS,
    quantile,
)

logger = logging.getLogger(__name__)


def count_non_bot_participants():
    """Return how many participants in the database PsyNet bots didn't create.

    Bots, including those of earlier performance tests and pre-fills, are
    :class:`psynet.bot.Bot` rows; their recruiter ID can't tell them apart,
    because real participants may have the same one.
    """
    from dallinger import db
    from dallinger.models import Participant
    from sqlalchemy import func, or_

    from psynet.bot import Bot

    bot_types = [
        mapper.polymorphic_identity for mapper in Bot.__mapper__.self_and_descendants
    ]
    n = (
        db.session.query(func.count(Participant.id))
        .filter(or_(Participant.type.is_(None), Participant.type.notin_(bot_types)))
        .scalar()
    )
    db.session.rollback()
    return n


def wait_for_async_processes(since=None, *, timeout_s, finished=False):
    """Wait up to ``timeout_s`` until no async process is waiting for a worker.

    Parameters
    ----------
    since : datetime.datetime, optional
        Only count processes enqueued from then on.
    finished : bool
        Also wait for processes that have started to finish.

    Returns
    -------
    int
        How many processes were still waiting when the wait ended.
    """
    from dallinger import db
    from sqlalchemy import func

    from psynet.process import AsyncProcess

    waiting_for = "finish" if finished else "start"
    filters = [
        AsyncProcess.failed.is_(False),
        AsyncProcess.finished.is_(False)
        if finished
        else AsyncProcess.time_started.is_(None),
    ]
    if since is not None:
        filters.append(AsyncProcess.time_enqueued >= since)
    deadline = time.monotonic() + timeout_s
    announced = False
    while True:
        waiting = (
            db.session.query(func.count(AsyncProcess.id)).filter(*filters).scalar()
        )
        db.session.rollback()
        if not waiting or time.monotonic() >= deadline:
            return waiting
        if not announced:
            logger.info(f"Waiting for {waiting:,} async processes to {waiting_for}...")
            announced = True
        time.sleep(2)


_KEY_ENDPOINTS = ("/timeline", "/response")


def _as_float(value):
    """Return a SQL aggregate as a float, or ``None`` if it is missing or not finite.

    Results are saved as JSON, which has no ``Decimal``, NaN or infinity.
    """
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def request_stats(after_request_id, last_request_id):
    """Return the result fields measured from requests in ``(after_request_id, last_request_id]``.

    Response times and failed requests cover only :data:`_KEY_ENDPOINTS`.
    """
    from dallinger import db
    from sqlalchemy import func

    from psynet.experiment import Request

    window = (Request.id > after_request_id, Request.id <= last_request_id)
    key_window = (*window, Request.endpoint.in_(_KEY_ENDPOINTS))
    stats = (
        db.session.query(
            func.count(Request.id).label("count"),
            func.avg(Request.duration).label("avg"),
            func.percentile_cont(0.5).within_group(Request.duration).label("median"),
            func.percentile_cont(0.95).within_group(Request.duration).label("p95"),
            func.percentile_cont(0.99).within_group(Request.duration).label("p99"),
            func.stddev_samp(Request.duration).label("stddev"),
            func.max(Request.duration).label("max"),
        )
        .filter(*key_window)
        .one()
    )
    endpoint_p95 = {
        endpoint: _as_float(p95)
        for endpoint, p95 in db.session.query(
            Request.endpoint,
            func.percentile_cont(0.95).within_group(Request.duration),
        )
        .filter(*key_window)
        .group_by(Request.endpoint)
        .all()
    }
    request_errors, busy_responses = _split_failed_requests(
        db.session.query(Request.status_code, func.count(Request.id))
        .filter(*key_window, Request.status_code >= 400)
        .group_by(Request.status_code)
        .all()
    )
    return dict(
        total_requests=db.session.query(func.count(Request.id))
        .filter(*window)
        .scalar(),
        key_requests=stats.count,
        avg_response_time=_as_float(stats.avg),
        median_response_time=_as_float(stats.median),
        p95_response_time=_as_float(stats.p95),
        endpoint_p95=endpoint_p95,
        p99_response_time=_as_float(stats.p99),
        stddev_response_time=_as_float(stats.stddev),
        max_response_time=_as_float(stats.max),
        request_errors=request_errors,
        busy_responses=busy_responses,
    )


def phase_stats(
    after_request_id, last_request_id, after_process_id, ended_at, boundary
):
    """Return the start-up and steady-state metrics of a test, split at ``boundary``.

    Reads the same requests and async processes as :func:`request_stats` and
    :func:`async_process_stats`. Requests logged, and processes enqueued,
    before ``boundary`` are start-up; the rest are the steady state.

    Returns
    -------
    tuple of (dict, dict)
        For the start-up and the steady state: ``key_requests``,
        ``request_errors`` (not counting busy or stale responses),
        ``p95_response_time``, ``async_processes`` (that started by
        ``ended_at``) and ``q_delay_p95``; the response and queue times are
        ``None`` without measurements.
    """
    from dallinger import db
    from sqlalchemy import func

    from psynet.experiment import Request
    from psynet.process import AsyncProcess

    in_steady_state = (Request.creation_time >= boundary).label("steady")
    requests = {
        row.steady: row
        for row in db.session.query(
            in_steady_state,
            func.count(Request.id).label("count"),
            func.count(Request.id)
            .filter(
                Request.status_code >= 400,
                Request.status_code.notin_(_BUSY_STATUS_CODES),
            )
            .label("errors"),
            func.percentile_cont(0.95).within_group(Request.duration).label("p95"),
        )
        .filter(
            Request.id > after_request_id,
            Request.id <= last_request_id,
            Request.endpoint.in_(_KEY_ENDPOINTS),
        )
        .group_by(in_steady_state)
    }
    enqueued_in_steady_state = AsyncProcess.time_enqueued >= boundary
    queues = {
        row[0]: row[1:]
        for row in db.session.query(
            enqueued_in_steady_state,
            func.count(AsyncProcess.id),
            func.percentile_cont(0.95).within_group(AsyncProcess.queue_delay),
        )
        .filter(
            AsyncProcess.id > after_process_id,
            AsyncProcess.time_started <= ended_at,
            AsyncProcess.queue_delay.isnot(None),
        )
        .group_by(enqueued_in_steady_state)
    }
    phases = []
    for steady in (False, True):
        row = requests.get(steady)
        n_processes, queue_p95 = queues.get(steady, (0, None))
        phases.append(
            dict(
                key_requests=row.count if row else 0,
                request_errors=row.errors if row else 0,
                p95_response_time=_as_float(row.p95) if row else None,
                async_processes=n_processes,
                q_delay_p95=_as_float(queue_p95),
            )
        )
    return tuple(phases)


def async_process_stats(after_process_id, ended_at):
    """Return the result fields measured from async processes after ``after_process_id``.

    Like requests, only processes that started by ``ended_at`` count: jobs
    left queued while the bots stop would otherwise report the stop time as
    queue delay. Those are covered by ``oldest_queued_s``. Queue delay is
    known once a process starts, so it also covers processes still running.
    """
    from dallinger import db
    from sqlalchemy import case, func, or_

    from psynet.process import AsyncProcess

    queue_window = (
        AsyncProcess.id > after_process_id,
        AsyncProcess.time_started <= ended_at,
        AsyncProcess.queue_delay.isnot(None),
    )
    time_taken, queue_delay = AsyncProcess.time_taken, AsyncProcess.queue_delay
    rows = (
        db.session.query(
            AsyncProcess.trial_maker_id,
            AsyncProcess.label,
            func.count(AsyncProcess.id).label("count"),
            func.avg(time_taken).label("avg"),
            func.percentile_cont(0.5).within_group(time_taken).label("median"),
            func.percentile_cont(0.95).within_group(time_taken).label("p95"),
            func.max(time_taken).label("max"),
            func.avg(queue_delay).label("q_avg"),
            func.percentile_cont(0.5).within_group(queue_delay).label("q_median"),
            func.percentile_cont(0.95).within_group(queue_delay).label("q_p95"),
            func.avg(
                case(
                    (
                        (queue_delay + time_taken) > 0,
                        queue_delay / (queue_delay + time_taken),
                    ),
                    else_=None,
                )
            ).label("q_share"),
        )
        .filter(*queue_window, AsyncProcess.finished == True)  # noqa: E712
        .group_by(AsyncProcess.trial_maker_id, AsyncProcess.label)
        .all()
    )
    process_stats = [
        {
            "trial_maker_id": row.trial_maker_id or "",
            "label": row.label or "",
            "count": row.count,
            **{key: _as_float(row._mapping[key]) for key in PROCESS_STAT_KEYS},
        }
        for row in rows
    ]
    q_delay_median, q_delay_p95 = (
        db.session.query(
            func.percentile_cont(0.5).within_group(queue_delay),
            func.percentile_cont(0.95).within_group(queue_delay),
        )
        .filter(*queue_window)
        .one()
    )
    oldest_enqueued = (
        db.session.query(func.min(AsyncProcess.time_enqueued))
        .filter(
            AsyncProcess.id > after_process_id,
            AsyncProcess.time_enqueued <= ended_at,
            AsyncProcess.failed.is_(False),
            or_(
                AsyncProcess.time_started.is_(None),
                AsyncProcess.time_started > ended_at,
            ),
        )
        .scalar()
    )
    return dict(
        process_stats=process_stats,
        q_delay_median=_as_float(q_delay_median),
        q_delay_p95=_as_float(q_delay_p95),
        oldest_queued_s=(
            (ended_at - oldest_enqueued).total_seconds() if oldest_enqueued else None
        ),
    )


def bot_outcome_stats(after_participant_id, errored_bot_ids):
    """Return how the test's bots ended, and the result fields that depend on it.

    Returns
    -------
    tuple of (dict, dict)
        Each bot's outcome (see :func:`_bot_outcome`) by participant ID, and
        the outcome counts, failure reasons, wait-page times and trial counts.
    """
    from psynet.bot import Bot

    bots = Bot.query.filter(Bot.id > after_participant_id).all()
    outcomes = {b.id: _bot_outcome(b, errored=b.id in errored_bot_ids) for b in bots}
    outcome_counts = Counter(outcomes.values())
    failed_reasons = Counter(
        _failure_reason(b) for b in bots if outcomes[b.id] == _FAILED_BY_EXPERIMENT
    )
    # Bots failed for waiting too long waited longest, so leaving them out
    # would make an overloaded server look healthier.
    wait_page_times = sorted(
        b.total_wait_page_time
        for b in bots
        if outcomes[b.id] in (_SUCCEEDED, _FAILED_BY_EXPERIMENT)
        and b.total_wait_page_time is not None
    )
    succeeded_bot_ids = [b.id for b in bots if outcomes[b.id] == _SUCCEEDED]
    min_trials, median_trials, max_trials = _trial_count_stats(succeeded_bot_ids)
    return outcomes, dict(
        bots_succeeded=outcome_counts[_SUCCEEDED],
        bots_failed=outcome_counts[_OTHER_END],
        bots_incomplete=outcome_counts[_STILL_RUNNING],
        participants_failed=outcome_counts[_FAILED_BY_EXPERIMENT],
        failed_reasons=dict(failed_reasons.most_common()),
        median_wait_page_time=quantile(wait_page_times, 0.5),
        p95_wait_page_time=quantile(wait_page_times, 0.95),
        max_wait_page_time=quantile(wait_page_times, 1),
        n_wait_page_samples=len(wait_page_times) if wait_page_times else None,
        min_trial_count=min_trials,
        median_trial_count=median_trials,
        max_trial_count=max_trials,
    )


def _trial_count_stats(bot_ids):
    """Return the min, median and max number of non-failed trials of the bots ``bot_ids``."""
    from dallinger import db
    from sqlalchemy import func

    from psynet.trial.main import Trial

    if not bot_ids:
        return None, None, None
    rows = (
        db.session.query(Trial.participant_id, func.count(Trial.id).label("n_trials"))
        .filter(
            Trial.participant_id.in_(bot_ids),
            Trial.failed == False,  # noqa: E712
        )
        .group_by(Trial.participant_id)
        .all()
    )
    counts = sorted([0] * (len(bot_ids) - len(rows)) + [r.n_trials for r in rows])
    return counts[0], quantile(counts, 0.5), counts[-1]


def bot_duration_stats(bot_durations, outcomes):
    """Return the average bot runtimes by outcome, from ``_BotState.bot_durations``."""
    return dict(
        avg_bot_duration=_mean([d for _, d, _ in bot_durations]),
        avg_succeeded_duration=_mean(
            [
                d
                for bot_id, d, stopped in bot_durations
                if not stopped and outcomes.get(bot_id) == _SUCCEEDED
            ]
        ),
        avg_experiment_failed_duration=_mean(
            [
                d
                for bot_id, d, _ in bot_durations
                if outcomes.get(bot_id) == _FAILED_BY_EXPERIMENT
            ]
        ),
        avg_failed_duration=_mean(
            [
                d
                for bot_id, d, stopped in bot_durations
                if not stopped and outcomes.get(bot_id, _OTHER_END) == _OTHER_END
            ]
        ),
        avg_incomplete_duration=_mean(
            [
                d
                for bot_id, d, stopped in bot_durations
                if (stopped and outcomes.get(bot_id) != _FAILED_BY_EXPERIMENT)
                or outcomes.get(bot_id) == _STILL_RUNNING
            ]
        ),
    )


def count_rq_workers():
    """Return how many async worker processes there are and how many jobs they can run at once.

    Returns ``(None, None)`` if they can't be counted.
    """
    try:
        from dallinger.db import redis_conn
        from rq import Worker

        workers = Worker.all(connection=redis_conn)
        # Dallinger's gevent workers record how many jobs each can run at once.
        n_slots = sum(int(redis_conn.hget(w.key, "pool_size") or 1) for w in workers)
        return len(workers), n_slots
    except Exception as e:
        logger.warning(f"Could not count async workers: {e}")
        return None, None


_SUCCEEDED = "succeeded"
_FAILED_BY_EXPERIMENT = "failed by the experiment"
_STILL_RUNNING = "still running"
_OTHER_END = "bot error or other status"


def _bot_outcome(participant, errored):
    """Return how a bot ended: ``_SUCCEEDED``, ``_FAILED_BY_EXPERIMENT``, ``_STILL_RUNNING`` or ``_OTHER_END``.

    A participant that the experiment failed, for example at a prescreen or
    when a timeline hold timed out, often still ends ``approved``, so
    ``failed`` is checked first. It is checked before ``errored`` too, so
    that a bot that raised after its participant was failed still counts
    towards the failure's reason; its error still counts as a bot error.

    Parameters
    ----------
    participant : psynet.bot.Bot
        The bot's participant.
    errored : bool
        Whether the bot raised an exception, whatever its participant's status.
    """
    if participant.failed:
        return _FAILED_BY_EXPERIMENT
    if errored:
        return _OTHER_END
    if participant.status in ("approved", "submitted"):
        return _SUCCEEDED
    if participant.status == "working":
        return _STILL_RUNNING
    return _OTHER_END


# Tags that say little on their own, listed after the specific tags.
_GENERIC_FAILURE_TAGS = frozenset(
    {"fail_on_timeout", "performance_check", "premature_exit"}
)


def _failure_reason(participant):
    """Return why the experiment failed ``participant``, as a key for counting.

    The reason joins the participant's failure tags (see
    :meth:`~psynet.participant.Participant.append_failure_tags`) in a stable
    order. Numbers in the labels of ``kind:label`` tags become ``N``, so
    that per-round barriers or loops count as one reason, e.g.
    ``timeline_hold:barrier:round_N, fail_on_timeout``.
    """
    tags = participant.failure_tags or (participant.failed_reason or "").split(", ")
    tags = {_normalize_failure_tag(tag) for tag in tags if tag}
    # UnsuccessfulEndPage tags every participant it ends, whatever the reason.
    tags = tags - {"UnsuccessfulEndPage"} or tags
    if not tags:
        return "no reason given"
    return ", ".join(sorted(tags, key=lambda t: (t in _GENERIC_FAILURE_TAGS, t)))


def _normalize_failure_tag(tag):
    """Replace the numbers in the label of a ``kind:label`` failure tag with ``N``."""
    kind, colon, label = str(tag).partition(":")
    return kind + colon + re.sub(r"\d+", "N", label)


# Tables that grow as a study collects data.
_GROWING_TABLES = (
    "participant",
    "trial",
    "response",
    "node",
    "network",
    "process",
    "asset",
)


def database_rows(connection=None):
    """Return the number of rows in each of ``_GROWING_TABLES``.

    Exact counts take well under a second even at hundreds of thousands of
    trials, and run twice per test. PostgreSQL's ``reltuples`` estimates would
    be cheaper, but only autovacuum and ``ANALYZE`` update them, so they lag
    behind a test that adds rows quickly. Tables that don't exist are left
    out. Counts on ``connection``, a SQLAlchemy connection, or by default on
    Dallinger's session; the caller should end the transaction afterwards.
    """
    from dallinger import db
    from sqlalchemy import inspect, text

    bind = db.session.get_bind() if connection is None else connection
    connection = db.session if connection is None else connection
    existing = set(inspect(bind).get_table_names())
    tables = [table for table in _GROWING_TABLES if table in existing]
    if not tables:
        return {}
    row = connection.execute(text(_count_rows_statement(tables))).one()
    return dict(row._mapping)


def database_rows_on_cursor(cursor):
    """Return :func:`database_rows` counted with a DB-API ``cursor`` on the experiment database."""
    names = ", ".join(f"'{table}'" for table in _GROWING_TABLES)
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
        f"AND tablename IN ({names})"
    )
    existing = {row[0] for row in cursor.fetchall()}
    tables = [table for table in _GROWING_TABLES if table in existing]
    if not tables:
        return {}
    cursor.execute(_count_rows_statement(tables))
    return {table: int(n) for table, n in zip(tables, cursor.fetchone())}


def _count_rows_statement(tables):
    columns = ", ".join(
        f'(SELECT count(*) FROM "{table}") AS "{table}"' for table in tables
    )
    return f"SELECT {columns}"


_BUSY_STATUS_CODES = frozenset({409, 503})


def _split_failed_requests(status_counts):
    """Split failed key-endpoint requests into errors and busy/stale responses.

    PsyNet answers with HTTP 503 when the experiment is busy and HTTP 409
    when a timeline moved on mid-render. Bots retry the responses that PsyNet
    marks as busy or stale, and any other 409 or 503 fails the bot. The
    request log records only status codes, so every 409 and 503 counts as a
    busy/stale response, and bots that fail on them count as bot errors.

    Parameters
    ----------
    status_counts : iterable of (int, int)
        ``(status_code, count)`` pairs for responses with status 400 or above.

    Returns
    -------
    tuple of (int, int)
        The number of request errors and of busy/stale responses.
    """
    errors = busy = 0
    for status_code, count in status_counts:
        if status_code in _BUSY_STATUS_CODES:
            busy += count
        else:
            errors += count
    return errors, busy


def _mean(values):
    """Return the mean of ``values``, or ``None`` if there are none."""
    return sum(values) / len(values) if values else None

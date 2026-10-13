"""What a performance test measured, and whether it stayed within capacity limits.

:class:`PerformanceTestResult` holds one test's measurements and is what
``--json-output`` saves. :class:`CapacityLimits` and :func:`capacity_failures`
decide whether a result passes, :func:`capacity_outcome` what a series of
results shows, and :func:`next_capacity_probe` chooses the next bot count of
a capacity search. :func:`recommend_workers` suggests ``worker_processes``
from how busy the async workers were. :func:`default_duration_minutes` and
:func:`confirmation_timing` choose how long tests last from how long a
participant session takes.

Failures from waiting too long, such as timed-out holds, count against
capacity (see :func:`_is_wait_timeout`); others, such as prescreens, are
reported only. Participants who got fewer trials because every chain was
busy count against capacity too (see :func:`busy_early_finish_cause`),
although they are not failed.

The terminal report (:mod:`psynet.perf_test.report`) and the suite
(:mod:`psynet.perf_test.suite`) word failure causes with the helpers here, so
that a cause reads the same everywhere. This module imports neither bots nor
the database, so it works on results read back from JSON.
"""

import copy
import math
from dataclasses import dataclass, field, fields
from urllib.parse import urlparse

DEFAULT_MAX_P95_S = 0.5
DEFAULT_MAX_QUEUE_P95_S = 5.0
CAPACITY_SEARCH_START = 10
CAPACITY_SEARCH_MAX = 2000
# The search stops once the gap between the largest passing and smallest
# failing bot counts is within this fraction of the passing count.
_CAPACITY_RESOLUTION = 0.1
# The most tests the capacity search runs: doubling from 10 to the 2000 cap
# takes 9, then bisecting between 1280 and 2000 takes 3. Recompute it if the
# constants above change.
CAPACITY_SEARCH_MAX_TESTS = 12
# A default test lasts this many participant sessions, so that bots finish
# and new ones replace them, but at most _MAX_DEFAULT_DURATION_MINUTES so that
# a long study's test stays practical.
_DEFAULT_SESSIONS_PER_TEST = 1.5
_MAX_DEFAULT_DURATION_MINUTES = 30
# A capacity search runs up to CAPACITY_SEARCH_MAX_TESTS tests, so its tests
# last one session but at most 5 minutes: 12 tests then take at most an hour,
# and the 7 or 8 a typical search runs about 40 minutes. They only see the
# start-up, which the confirmation test makes up for.
_SEARCH_SESSIONS_PER_TEST = 1
_MAX_SEARCH_DURATION_MINUTES = 5
# The confirmation test spreads arrivals over one session and lasts two, so
# that the last bots to arrive finish a session and the test sees about one
# session of steady state. At most an hour, which covers two sessions of a
# 30-minute study.
_CONFIRMATION_SESSIONS = 2
MAX_CONFIRMATION_DURATION_MINUTES = 60
# The shortest steady state that the report shows separately from the start-up.
MIN_STEADY_STATE_S = 60


def default_duration_minutes(session_minutes, minimum, search=False):
    """Return how long a test lasts by default, in whole minutes.

    Parameters
    ----------
    session_minutes : float or None
        How long a bot takes the experiment: the timeline's estimated
        duration times the bots' time factor. ``None`` or 0 if unknown.
    minimum : float
        The shortest default, ``Experiment.test_duration_minutes``.
    search : bool
        Whether the test is part of a capacity search (``--n-bots auto``).

    Returns
    -------
    float
        1.5 sessions rounded up and at most 30 minutes, or for a search one
        session rounded up and at most 5 minutes; at least ``minimum``.
    """
    if not session_minutes:
        return minimum
    sessions, longest = (
        (_SEARCH_SESSIONS_PER_TEST, _MAX_SEARCH_DURATION_MINUTES)
        if search
        else (_DEFAULT_SESSIONS_PER_TEST, _MAX_DEFAULT_DURATION_MINUTES)
    )
    return max(minimum, min(math.ceil(sessions * session_minutes), longest))


def confirmation_timing(session_minutes, minimum, arrival_minutes=None):
    """Return ``(duration_minutes, arrival_minutes)`` for a capacity search's confirmation test.

    Bots arrive evenly over one session and the test lasts two, so that it
    reaches the steady state: at least a session and a minute, so that a
    short study's steady state is long enough to report, and at most an
    hour, so a study over an hour long never reaches it.

    Parameters
    ----------
    session_minutes : float or None
        How long a bot takes the experiment, as for
        :func:`default_duration_minutes`.
    minimum : float
        The shortest test, the search tests' duration.
    arrival_minutes : float, optional
        The arrival window the user chose, which the confirmation keeps; the
        test then lasts a session longer than it, up to the same hour.

    Returns
    -------
    tuple of (float, float or None)
        The test length in whole minutes and the arrival window in minutes,
        ``None`` if the session length is unknown.
    """
    session_minutes = session_minutes or 0
    if arrival_minutes:
        duration = arrival_minutes + max(session_minutes, 1)
    else:
        # A short study still gets a steady state long enough to report.
        duration = max(
            _CONFIRMATION_SESSIONS * session_minutes,
            session_minutes + MIN_STEADY_STATE_S / 60,
        )
    duration = max(minimum, min(math.ceil(duration), MAX_CONFIRMATION_DURATION_MINUTES))
    if arrival_minutes:
        return duration, arrival_minutes
    return duration, round(min(session_minutes, duration / 2), 1) or None


def short_test_warning(duration_minutes, session_minutes):
    """Return a warning if a test is shorter than one participant session, else ``None``."""
    if not session_minutes or duration_minutes >= session_minutes:
        return None
    return (
        f"The test lasts {duration_minutes:g} min, but a participant session takes "
        f"about {session_minutes:.1f} min, so bots that take the whole session "
        "don't finish during it, and the test sees mostly the start of the "
        "study rather than its steady state. Use "
        f"--duration-minutes {math.ceil(_DEFAULT_SESSIONS_PER_TEST * session_minutes)} "
        "or more to see both."
    )


@dataclass(kw_only=True)
class PerformanceTestResult:
    """The measurements of one performance test, as written to ``--json-output``.

    Field names are the JSON keys, in order. Times are in seconds, and a
    measurement is ``None`` when the test did not produce it. Every field has
    a default so that :meth:`from_dict` can read results that older or newer
    PsyNet versions saved.
    """

    n_bots: int = 0
    duration_minutes: float | None = None
    # Minutes over which the bots arrived, or None if they started --stagger
    # seconds apart.
    arrival_minutes: float | None = None
    # How long a bot takes the experiment: the timeline's estimate times the
    # bots' time factor.
    session_minutes: float | None = None
    # Whether this is the confirmation test that ends a capacity search.
    confirmation: bool = False
    actual_duration: float | None = None
    server_stopped: bool = False
    # Why a bot process stopped during the test, if one did.
    bot_process_failure: str | None = None
    # Numbers of bot processes that didn't report after the test.
    unreported_bot_processes: list[int] = field(default_factory=list)
    bot_processes: int = 1
    slots_started: int | None = None
    # Most bots that were taking part at the same moment.
    peak_running: int | None = None
    # Seconds from the test start until the last bot slot started.
    ramp_up_s: float | None = None
    # Of the busiest process running bots; see runtime._LoadMonitor.
    tester_cpu_share: float | None = None
    tester_lag_p95_s: float | None = None
    total_bots_started: int = 0
    # Bots whose participant ended approved or submitted and was not failed.
    bots_succeeded: int = 0
    # Bots that raised, or whose participant ended with another status.
    bots_failed: int = 0
    # Bots still taking the experiment when the test ended.
    bots_incomplete: int = 0
    # Participants the experiment failed, e.g. at a prescreen or a hold timeout.
    participants_failed: int = 0
    # Number of failed participants by reason (see measure._failure_reason), most
    # common first.
    failed_reasons: dict[str, int] = field(default_factory=dict)
    # Rows in each table that grows as the study collects data
    # (see measure.database_rows), before the test and after the bots stopped.
    db_rows_before: dict[str, int] = field(default_factory=dict)
    db_rows_after: dict[str, int] = field(default_factory=dict)
    total_requests: int = 0
    # Requests to /timeline and /response, which the response times cover.
    key_requests: int = 0
    requests_per_sec: float | None = None
    bot_errors: int = 0
    # Number of bot errors of each kind, most common first.
    bot_error_kinds: dict[str, int] = field(default_factory=dict)
    avg_response_time: float | None = None
    median_response_time: float | None = None
    p95_response_time: float | None = None
    endpoint_p95: dict[str, float] = field(default_factory=dict)
    p99_response_time: float | None = None
    stddev_response_time: float | None = None
    max_response_time: float | None = None
    avg_bot_duration: float | None = None
    # How long creating each bot took, over n_init_samples bots.
    median_init_time: float | None = None
    p95_init_time: float | None = None
    max_init_time: float | None = None
    n_init_samples: int = 0
    request_errors: int = 0
    # HTTP 409 and 503 responses; see measure._split_failed_requests.
    busy_responses: int = 0
    # Total time each bot that succeeded or was failed by the experiment
    # spent on wait pages, over n_wait_page_samples bots.
    median_wait_page_time: float | None = None
    p95_wait_page_time: float | None = None
    max_wait_page_time: float | None = None
    n_wait_page_samples: int | None = None
    avg_succeeded_duration: float | None = None
    avg_experiment_failed_duration: float | None = None
    # Of bots that raised or whose participant ended with another status.
    avg_failed_duration: float | None = None
    avg_incomplete_duration: float | None = None
    # Of all async jobs that started.
    q_delay_median: float | None = None
    # For "high" and "low" priority async jobs, if any: how many started,
    # their p95 queue wait, and the backlog still queued at the end and how
    # long its oldest job had waited (see measure._queue_waits).
    queue_waits: dict[str, dict] = field(default_factory=dict)
    # Duration, CPU and queue-delay statistics by trial maker, job label and
    # priority.
    async_job_stats: list[dict] = field(default_factory=list)
    # Trials per bot that succeeded.
    min_trial_count: int | None = None
    median_trial_count: int | None = None
    max_trial_count: int | None = None
    # Bots whose chain trial makers finished a block early because every
    # eligible chain or node was busy, by trial maker (see
    # measure.busy_early_finish_stats).
    busy_early_finishes: dict[str, dict] = field(default_factory=dict)
    # Async worker processes registered with RQ at the end of the test.
    n_rq_workers: int | None = None
    # Jobs the async workers can run at once.
    n_rq_job_slots: int | None = None
    # The server's worker_processes config variable.
    configured_worker_processes: int | None = None
    # How busy the async workers were (see measure.worker_load).
    worker_load: dict = field(default_factory=dict)
    # CPU cores where the test ran: on an SSH server, the web container's.
    server_cores: int | None = None
    # Seconds from the test start until the first bot completed the
    # experiment, where the steady state begins.
    first_completion_s: float | None = None
    # Metrics before and after first_completion_s (see measure.phase_stats),
    # empty unless the steady state lasted at least MIN_STEADY_STATE_S.
    startup_phase: dict = field(default_factory=dict)
    steady_state_phase: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        """Return a result from a saved JSON result.

        Unknown keys are ignored, and missing or ``null`` values take the
        field's default.
        """
        names = {f.name for f in fields(cls)}
        return cls(
            **{
                k: copy.deepcopy(v)
                for k, v in data.items()
                if k in names and v is not None
            }
        )


# Statistics in each entry of PerformanceTestResult.async_job_stats, besides
# trial_maker_id, label, priority and count.
ASYNC_JOB_STAT_KEYS = (
    "avg",
    "median",
    "p95",
    "max",
    "cpu_avg",
    "q_avg",
    "q_median",
    "q_p95",
    "q_share",
)


POSTGRES_FULL = "PostgreSQL out of connections"
PGBOUNCER_FULL = "PgBouncer out of client connections"
# Bot errors of these kinds come from the connections that the processes
# running the bots open themselves, which participants don't.
_CONNECTION_LIMIT_KINDS = (POSTGRES_FULL, PGBOUNCER_FULL)
# PgBouncer's error when it already has max_client_conn clients, e.g.
# "FATAL:  no more connections allowed (max_client_conn)".
_PGBOUNCER_FULL_TEXT = "(max_client_conn)"


def connection_limit_kind(error):
    """Return ``POSTGRES_FULL`` or ``PGBOUNCER_FULL`` if ``error`` says the database refused a connection, else ``None``.

    ``error`` is an exception or text such as a command's output.
    """
    from psynet.isolated_environment import postgres_connection_limit_message

    if _PGBOUNCER_FULL_TEXT in str(error):
        return PGBOUNCER_FULL
    if postgres_connection_limit_message(error):
        return POSTGRES_FULL
    return None


# Async job priorities, as in psynet.async_job, which this module doesn't
# import so that it doesn't need a database.
PRIORITIES = ("high", "low")


# Failure tags that mean a participant waited too long, which under load
# usually means waiting for the server. Timeline holds (wait_while, async code
# blocks that wait, barriers) tag "timeline_hold:<hold>", while loops that reach
# max_loop_time (page-based waits, barriers without holds, "Waiting for trial")
# tag "while_loop:<label>", and both add "fail_on_timeout". Group barriers fail
# participants that take too long between barriers with "timeout between
# barriers". Extend these when PsyNet adds another kind of wait.
_WAIT_TIMEOUT_TAG_PREFIXES = ("timeline_hold:", "while_loop:")
_WAIT_TIMEOUT_TAGS = frozenset({"fail_on_timeout", "timeout between barriers"})


def _is_wait_timeout(reason):
    """Return whether a failure reason means the participant waited too long.

    ``reason`` comes from :func:`~psynet.perf_test.measure._failure_reason`.

    Other failures, such as prescreens (``performance_check``), are part of
    the design and don't count against capacity.
    """
    return any(
        tag in _WAIT_TIMEOUT_TAGS or tag.startswith(_WAIT_TIMEOUT_TAG_PREFIXES)
        for tag in reason.split(", ")
    )


# Simple sync groups fail the members left behind when one is failed, so in a
# test with wait timeouts these failures count as wait timeouts too.
_GROUP_TOO_SMALL_TAG = "sync group below minimum size"


def wait_timeout_reasons(result):
    """Return the reasons in ``result`` that count as waiting too long, with their counts."""
    failed_reasons = result.failed_reasons or {}
    waits = {r: n for r, n in failed_reasons.items() if _is_wait_timeout(r)}
    if waits:
        waits.update(
            (r, n)
            for r, n in failed_reasons.items()
            if _GROUP_TOO_SMALL_TAG in r.split(", ")
        )
    return waits


def count_wait_timeouts(result):
    """Return how many participants in ``result`` failed for waiting too long."""
    return sum(wait_timeout_reasons(result).values())


def top_counts(counts, limit=3):
    """Name the first ``limit`` items of ``counts``, e.g. ``12 performance_check, 3 timeout``."""
    items = list(counts.items())
    named = ", ".join(f"{count:,} {name}" for name, count in items[:limit])
    return named + (", ..." if len(items) > limit else "")


def describe_bot_error(err):
    """Summarize why a bot failed, e.g. ``HTTP 500 on /participant_status``.

    Bots raise on the first HTTP error, so this also counts failed requests
    that the server could not log because it could not reach the database.
    """
    import requests

    cause, seen = err, set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if kind := connection_limit_kind(cause):
            return kind
        response = getattr(cause, "response", None)
        if isinstance(cause, requests.HTTPError) and response is not None:
            route = urlparse(response.url or "").path.strip("/").split("/")[0]
            return f"HTTP {response.status_code} on /{route}"
        cause = cause.__cause__ or cause.__context__
    return type(err).__name__


def plural(count, noun):
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def describe_bot_errors(result):
    """Describe a result's bot errors, naming the most common causes."""
    text = plural(result.bot_errors, "bot error")
    kinds = result.bot_error_kinds or {}
    if len(kinds) == 1:
        return f"{text} ({next(iter(kinds))})"
    return f"{text} ({top_counts(kinds)})" if kinds else text


def quantile(sorted_values, q):
    """Return the value at quantile ``q`` of ``sorted_values``, or ``None`` if empty."""
    if not sorted_values:
        return None
    return sorted_values[min(int(len(sorted_values) * q), len(sorted_values) - 1)]


@dataclass(frozen=True)
class CapacityLimits:
    """Thresholds a performance test must stay within to count as within capacity.

    Parameters
    ----------
    max_p95_s : float
        Largest acceptable 95th-percentile response time, for ``/timeline``
        and ``/response`` together and for each of them.
    max_queue_p95_s : float
        Largest acceptable time high-priority async jobs spend waiting for a
        worker, measured by :func:`queue_wait_p95`. Participants don't wait
        for low-priority jobs, so their waits are only reported.
    max_request_error_rate : float
        Largest acceptable share of ``/timeline`` and ``/response`` requests
        that fail, not counting busy or stale responses (HTTP 409 and 503).
        A long test makes tens of thousands of requests, so a stray error
        should not count against a bot count that is otherwise well within
        capacity.
    allowed_request_errors : int
        Number of request errors that is acceptable however few requests a
        test makes, so that one stray error doesn't fail a short test.
    max_busy_response_rate : float
        Largest acceptable share of ``/timeline`` and ``/response`` requests
        answered as busy or stale. Bots retry these, so a server stuck on lock
        contention can otherwise pass with no errors and short response times.
        Each such response delays at most one request, so at 1% the delays
        stay well inside the 5% of requests that the p95 limit ignores.
    allowed_busy_responses : int
        Number of busy or stale responses that is acceptable however few
        requests a test makes, for the occasional contention at timeline holds
        and synchronized groups.
    max_bot_error_rate : float
        Largest acceptable share of bots that fail.
    max_wait_timeout_rate : float
        Largest acceptable share of bots whose participants the experiment
        failed for waiting too long, for example at a timeline hold that
        timed out (see :func:`_is_wait_timeout`). Such a participant is lost
        to the study just like one whose bot failed, so the default matches
        ``max_bot_error_rate``.
    max_busy_early_finish_rate : float
        Largest acceptable share of bots that got fewer trials in a trial
        maker because every chain was busy and ``wait_for_networks=False``
        (see :func:`busy_early_finish_cause`). Like a wait timeout, this
        loses data, so the default matches ``max_wait_timeout_rate``. It
        grows with the number of participants taking part at once, so unlike
        wait timeouts it sets the capacity and the suggested cap.
    allowed_busy_early_finishes : int
        Number of such bots per trial maker that is acceptable however few
        bots a test starts, so that one unlucky bot doesn't fail a small test.
    """

    max_p95_s: float = DEFAULT_MAX_P95_S
    max_queue_p95_s: float = DEFAULT_MAX_QUEUE_P95_S
    max_request_error_rate: float = 0.001
    allowed_request_errors: int = 1
    max_busy_response_rate: float = 0.01
    allowed_busy_responses: int = 10
    max_bot_error_rate: float = 0.01
    max_wait_timeout_rate: float = 0.01
    max_busy_early_finish_rate: float = 0.01
    allowed_busy_early_finishes: int = 1

    @classmethod
    def from_options(
        cls, max_p95_s=None, max_queue_p95_s=None, max_busy_early_finish_rate=None
    ):
        """Return limits from optional settings; ``None`` means the default."""
        options = {
            "max_p95_s": max_p95_s,
            "max_queue_p95_s": max_queue_p95_s,
            "max_busy_early_finish_rate": max_busy_early_finish_rate,
        }
        return cls(
            **{
                name: float(value)
                for name, value in options.items()
                if value is not None
            }
        )

    def allowed_busy_early_finishes_for(self, total_bots_started):
        """Return how many bots per trial maker may get fewer trials because every chain was busy."""
        return max(
            self.allowed_busy_early_finishes,
            self.max_busy_early_finish_rate * (total_bots_started or 0),
        )

    def describe(self, include_queue=True):
        """Return the limits as a phrase, for summaries.

        Pass ``include_queue=False`` when the tests ran no async jobs.
        """
        response = f"p95 response time under {self.max_p95_s * 1000:.0f} ms"
        errors = (
            f"at most {self.max_request_error_rate:.1%} of requests failing "
            f"({self.allowed_request_errors} always allowed), "
            f"{self.max_busy_response_rate:.0%} of requests answered busy or stale "
            f"({self.allowed_busy_responses} always allowed), "
            f"{self.max_bot_error_rate:.0%} of bots failing, "
            f"{self.max_wait_timeout_rate:.0%} of participants failed by the "
            "experiment for waiting too long and "
            f"{self.max_busy_early_finish_rate * 100:g}% getting fewer trials "
            f"because every chain was busy ({self.allowed_busy_early_finishes} "
            "always allowed)"
        )
        if not include_queue:
            return f"{response} and {errors}"
        return (
            f"{response}, p95 high-priority async queue wait under "
            f"{self.max_queue_p95_s:g} s and {errors}"
        )


def queue_wait_p95(result, priority="high"):
    """Return the 95th-percentile queue delay of ``priority`` async jobs, counting any unfinished backlog.

    Jobs still waiting when the test ended have no ``queue_delay`` yet,
    so the wait of the oldest one is used instead whenever it is longer.
    Returns ``None`` if the test ran no async jobs of that priority.
    """
    return _queue_wait_p95(result.queue_waits, priority)


def phase_queue_wait_p95(phase, priority="high"):
    """Return :func:`queue_wait_p95` for one phase of a test, counting the backlog at its end.

    ``phase`` is :attr:`PerformanceTestResult.startup_phase` or
    :attr:`~PerformanceTestResult.steady_state_phase`.
    """
    return _queue_wait_p95(phase.get("queue_waits"), priority)


def _queue_wait_p95(queue_waits, priority):
    waits = (queue_waits or {}).get(priority) or {}
    values = [
        float(v)
        for v in (waits.get("q_delay_p95"), waits.get("oldest_queued_s"))
        if v is not None
    ]
    return max(values) if values else None


# The low-priority backlog "grew" during the steady state if it ended at
# least this many times as long as it began, and at least this many jobs
# longer. A tapping study whose 3 workers couldn't keep up with 60
# participants went from 2 jobs to 95.
LOW_BACKLOG_GROWTH_RATIO = 2
LOW_BACKLOG_GROWTH_MIN_JOBS = 10


# Worker processes busier than this in the steady state can't keep up in the
# long run. Busier than _SATURATED_UTILIZATION, they were busy throughout, so
# the demand they show is a lower bound.
MAX_WORKER_UTILIZATION = 0.85
_SATURATED_UTILIZATION = 0.95
# recommend_workers sizes the worker processes to be this busy, leaving
# headroom for bursts and for jobs that slow down under load.
TARGET_WORKER_UTILIZATION = 0.7
# Matches psynet.async_job's rule: a job is CPU-heavy if its CPU time is at
# least this share of its run time.
_CPU_HEAVY_RATIO = 0.5
_MIN_STEADY_WORKER_JOBS = 20
# Cores left for the web server and database, which the test doesn't measure.
CORES_FOR_OTHERS = 2


def _worker_demand(result):
    """Return ``(utilization, greenlets)`` for the steady state of ``result``, or ``None``.

    With ``R`` jobs running per process on average and CPU share ``c`` of
    their run time: one slot per process gives ``U = R``. With more slots, a
    job's CPU time includes its neighbours', so ``c / max(R, 1)`` is the
    per-job CPU share. If that makes the jobs CPU-heavy, they move to one
    slot each and ``U = R``; otherwise ``U = max(R / slots, c × min(R, 1))``
    with the slots kept.
    """
    load, workers = result.worker_load or {}, result.n_rq_workers
    steady_s = (result.actual_duration or 0) - (result.first_completion_s or 0)
    if not (workers and load.get("jobs") and steady_s > 0):
        return None
    running = load["busy_s"] / (workers * steady_s)
    slots = (result.n_rq_job_slots or 0) // workers
    if slots <= 1:
        return running, 1
    cpu = load.get("cpu_share") or 0
    if cpu / max(running, 1) >= _CPU_HEAVY_RATIO:
        return running, 1
    return max(running / slots, cpu * min(running, 1)), slots


def worker_utilization(result):
    """Return the share of the steady state of ``result`` that its worker processes were busy, or ``None``."""
    demand = _worker_demand(result)
    return demand[0] if demand else None


def workers_falling_behind(result):
    """Say how the async workers fell behind in the steady state of ``result``, or return ``None``.

    They fell behind if they were more than :data:`MAX_WORKER_UTILIZATION`
    busy, or if the low-priority backlog grew (see
    :data:`LOW_BACKLOG_GROWTH_RATIO` and :data:`LOW_BACKLOG_GROWTH_MIN_JOBS`).
    """
    startup, steady = result.startup_phase, result.steady_state_phase
    if not (startup and steady):
        return None
    reasons = []
    utilization = worker_utilization(result)
    if utilization is not None and utilization > MAX_WORKER_UTILIZATION:
        busy = (
            "the whole time"
            if utilization >= _SATURATED_UTILIZATION
            else f"{utilization:.0%} of the time"
        )
        workers = result.n_rq_workers
        were = f"{workers} worker process{'es were' if workers != 1 else ' was'}"
        reasons.append(f"the {were} busy {busy}")
    start = ((startup.get("queue_waits") or {}).get("low") or {}).get("backlog") or 0
    end = ((steady.get("queue_waits") or {}).get("low") or {}).get("backlog") or 0
    if (
        end >= LOW_BACKLOG_GROWTH_RATIO * start
        and end - start >= LOW_BACKLOG_GROWTH_MIN_JOBS
    ):
        reasons.append(f"the low-priority backlog grew from {start:,} to {end:,} jobs")
    return " and ".join(reasons) or None


@dataclass
class WorkerAdvice:
    """What :func:`recommend_workers` suggests; ``skipped`` says why if nothing."""

    processes: int | None = None
    greenlets: int | None = None
    utilization: float | None = None
    steady_state: int | None = None
    burst: int | None = None
    # The processes needed before the cores cap: at least the current ones,
    # and one more if the workers fell behind.
    needed: int | None = None
    lower_bound: bool = False
    # Worker time per participant, if the lower bound comes from it.
    per_participant_s: float | None = None
    skipped: str | None = None


def recommend_workers(result, n_participants, burst=None):
    """Estimate the async worker processes that ``n_participants`` taking part at once need.

    ``max(U × W × n_participants / N / u, W_b × n_participants / N_b)``, at
    at least the current ``W`` (``W + 1`` if :func:`workers_falling_behind`)
    and at most the cores less :data:`CORES_FOR_OTHERS`, with ``U`` and the greenlets
    from :func:`_worker_demand` and ``u`` :data:`TARGET_WORKER_UTILIZATION`.
    For saturated single-slot workers the steady-state term is the lower
    bound ``n_participants × D / (S × u)``, with ``D`` the worker time per
    participant who completed and ``S`` the session length.

    Parameters
    ----------
    result : PerformanceTestResult
        A test with ``W`` workers and ``N`` bots, measured in its steady state.
    n_participants : int
        The participants at once to size the workers for.
    burst : tuple of (int, int), optional
        ``(W_b, N_b)``: the workers of the capacity search and the capacity
        they handled, when high-priority queue waits set it.

    Returns
    -------
    WorkerAdvice
    """
    load, workers = result.worker_load or {}, result.n_rq_workers
    demand = _worker_demand(result)
    jobs = load.get("jobs") or 0
    if demand is None or jobs < _MIN_STEADY_WORKER_JOBS:
        if not workers:
            why = "no worker processes were running"
        elif not load:
            why = f"the {result.n_bots:,}-bot test ran for less than {MIN_STEADY_STATE_S} s after its first bot finished"
        else:
            why = f"only {plural(jobs, 'worker job')} finished in the {result.n_bots:,}-bot test after its first bot finished"
        return WorkerAdvice(skipped=why)
    utilization, greenlets = demand
    lower_bound = utilization >= _SATURATED_UTILIZATION
    per_participant_s = load.get("per_participant_s")
    session_s = result.avg_succeeded_duration or (result.session_minutes or 0) * 60
    single_slot = (result.n_rq_job_slots or 0) <= workers
    if not (lower_bound and session_s and single_slot):
        per_participant_s = None
    if per_participant_s:
        needed = n_participants * per_participant_s / session_s
    else:
        needed = utilization * workers * n_participants / result.n_bots
    steady_state = _round_up(needed / TARGET_WORKER_UTILIZATION)
    burst_n = (
        _round_up(burst[0] * n_participants / burst[1])
        if burst and all(burst)
        else None
    )
    floor = workers + bool(workers_falling_behind(result))
    needed = max(steady_state, burst_n or 0, floor)
    processes = needed
    if result.server_cores:
        processes = min(needed, max(1, result.server_cores - CORES_FOR_OTHERS))
    return WorkerAdvice(
        processes,
        greenlets,
        utilization,
        steady_state,
        burst_n,
        needed,
        lower_bound,
        per_participant_s,
    )


def _round_up(value):
    """Round ``value`` up to at least 1, ignoring float error such as ``8.000000001``."""
    return max(1, math.ceil(round(value, 6)))


def missing_workers(result):
    """Return ``(running, configured)`` worker processes if fewer ran than ``worker_processes`` configures, else ``None``."""
    running, configured = result.n_rq_workers, result.configured_worker_processes
    if running is None or not configured or running >= configured:
        return None
    return running, configured


# Bots between runs, or still being created, leave a few slots briefly empty.
_MIN_RUNNING_SHARE = 0.9
_MAX_TESTER_LAG_P95_S = 0.05


def tester_lagged(result):
    """Return whether bots ran so late that they could not keep pace; see :func:`_tester_limits`."""
    lag = result.tester_lag_p95_s
    return lag is not None and lag > _MAX_TESTER_LAG_P95_S


def start_rate_limits(result):
    """Return the reasons bots did not all start, or take part at once, in a test."""
    reasons = []
    slots_started = result.slots_started
    if slots_started is not None and slots_started < result.n_bots:
        reasons.append(
            f"only {slots_started:,} of {result.n_bots:,} bots started "
            "(use a longer --duration-minutes)"
        )
    peak_running = result.peak_running
    if peak_running is not None and peak_running < _MIN_RUNNING_SHARE * result.n_bots:
        reasons.append(
            f"at most {peak_running:,} of {result.n_bots:,} bots were taking "
            "part at once, because new bots could not start fast enough"
        )
    return reasons


def _tester_limits(result):
    """Return the reasons the test process, not the server, held back a test.

    Besides bots that didn't all start or take part at once, a bot process
    that stopped and bot processes that didn't report their load, this
    includes bots that ran late:
    ``tester_lag_p95_s`` is the 95th percentile of how much later than asked
    a thread in the worst process running bots woke up (see
    :class:`~psynet.perf_test.runtime._LoadMonitor`). That is how long bots
    queue for the interpreter lock and the CPU before each step, so above
    ``_MAX_TESTER_LAG_P95_S`` they make requests noticeably more slowly than
    participants would and the server gets less load than the bot count
    suggests.
    """
    reasons = start_rate_limits(result)
    if result.bot_process_failure:
        reasons.append(result.bot_process_failure)
    unreported = result.unreported_bot_processes
    if unreported:
        reasons.append(
            f"bot process(es) {', '.join(map(str, unreported))} did not report "
            "after the test, so how late their bots ran is unknown"
        )
    if tester_lagged(result):
        where = (
            "the test process"
            if result.bot_processes == 1
            else "the busiest bot process"
        )
        reasons.append(
            f"bots in {where} were running "
            f"{result.tester_lag_p95_s * 1000:.0f} ms late (p95), so they could "
            "not keep pace (use more --bot-processes)"
        )
    return reasons


def _describe_waits(result):
    """Name the waits at which participants in ``result`` timed out."""
    tags = {
        tag
        for reason in wait_timeout_reasons(result)
        for tag in reason.split(", ")
        if tag != "fail_on_timeout"
        and (_is_wait_timeout(tag) or tag == _GROUP_TOO_SMALL_TAG)
    }
    return ", ".join(sorted(tags)) or "a wait"


def wait_timeout_cause(result, limits):
    """Return why ``result`` had too many participants fail for waiting too long, or ``None``."""
    wait_timeouts = count_wait_timeouts(result)
    if wait_timeouts <= limits.max_wait_timeout_rate * (result.total_bots_started or 0):
        return None
    return (
        f"{plural(wait_timeouts, 'participant')} failed for waiting too long "
        f"at {_describe_waits(result)}"
    )


def describe_busy_early_finish(result, trial_maker_id, detail=False):
    """Describe the bots that got fewer trials in a trial maker because every chain was busy.

    Parameters
    ----------
    result : PerformanceTestResult
        The test.
    trial_maker_id : str
        A key of ``result.busy_early_finishes``.
    detail : bool
        Also give their median number of trials, e.g. ``23 of 150 bots
        started (15%) got fewer trials in main_chain because every chain was
        busy; median 41 of 60 trials``.

    Counts are of bots started, which include the bots that replaced those
    that finished, so a bot that got no trials and was replaced at once
    counts like a participant who would have left.
    """
    stats = result.busy_early_finishes[trial_maker_id]
    n, started = stats["participants"], result.total_bots_started or 0
    who = plural(n, "bot")
    if started:
        who = f"{n:,} of {started:,} bots started ({n / started:.0%})"
    text = (
        f"{who} got fewer trials in {trial_maker_id} because every "
        f"{stats.get('candidate') or 'chain'} was busy"
    )
    median, expected = stats.get("median_trials"), stats.get("expected_trials")
    if detail and median is not None:
        text += f"; median {median:,}" + (f" of {expected:,}" if expected else "")
        text += " trials"
    return text


def busy_early_finish_cause(result, limits):
    """Return why ``result`` had too many bots get fewer trials because every chain was busy, or ``None``.

    Each trial maker is judged separately against
    ``limits.max_busy_early_finish_rate`` and
    ``limits.allowed_busy_early_finishes``.
    """
    allowed = limits.allowed_busy_early_finishes_for(result.total_bots_started)
    over = [
        describe_busy_early_finish(result, trial_maker_id)
        for trial_maker_id, stats in (result.busy_early_finishes or {}).items()
        if stats["participants"] > allowed
    ]
    return " and ".join(over) or None


def phase_limit_reasons(phase, limits):
    """Return the response-time, request-error and queue limits that one phase exceeded.

    ``phase`` is :attr:`PerformanceTestResult.startup_phase` or
    :attr:`~PerformanceTestResult.steady_state_phase`. As in
    :func:`queue_wait_p95`, only high-priority queue waits count, including
    the backlog left at the end of the phase.
    """
    reasons = []
    p95 = phase.get("p95_response_time")
    if p95 is not None and p95 > limits.max_p95_s:
        reasons.append(f"p95 response time {p95 * 1000:.0f} ms")
    errors = phase.get("request_errors") or 0
    allowed = max(
        limits.allowed_request_errors,
        limits.max_request_error_rate * (phase.get("key_requests") or 0),
    )
    if errors > allowed:
        reasons.append(plural(errors, "request error"))
    queue_wait = phase_queue_wait_p95(phase)
    if queue_wait is not None and queue_wait > limits.max_queue_p95_s:
        reasons.append(f"p95 high-priority async queue wait {queue_wait:.2f} s")
    return reasons


def capacity_failure_causes(result, limits):
    """Return ``(reason, server_limit)`` for each limit that ``result`` exceeded.

    ``server_limit`` is False when the reason only shows that the test could
    not measure the server at this bot count: bots didn't all start or take
    part at once, bots in a busy process ran too late to keep pace
    (so the server got less load than that many participants would give),
    bots failed because PostgreSQL or PgBouncer refused their connections
    (the bots open their own database connections in the processes running
    them, which participants don't), or no responses were recorded while
    bots were missing.
    """
    causes = [("server stopped", True)] if result.server_stopped else []
    tester_limits = _tester_limits(result)
    causes += [(reason, False) for reason in tester_limits]
    causes += _error_causes(result, limits)
    if wait_cause := wait_timeout_cause(result, limits):
        causes.append((wait_cause, True))
    if busy_cause := busy_early_finish_cause(result, limits):
        causes.append((busy_cause, True))
    p95 = result.p95_response_time
    if p95 is None:
        causes.append(("no responses recorded", not tester_limits))
    elif float(p95) > limits.max_p95_s:
        causes.append((f"p95 response time {float(p95) * 1000:.0f} ms", True))
    else:
        for endpoint, endpoint_p95 in sorted((result.endpoint_p95 or {}).items()):
            if float(endpoint_p95) > limits.max_p95_s:
                causes.append(
                    (
                        f"p95 response time for {endpoint} "
                        f"{float(endpoint_p95) * 1000:.0f} ms",
                        True,
                    )
                )
    queue_wait = queue_wait_p95(result)
    if queue_wait is not None and queue_wait > limits.max_queue_p95_s:
        causes.append((f"p95 high-priority async queue wait {queue_wait:.2f} s", True))
    return causes


def _error_causes(result, limits):
    """Return the ``(reason, server_limit)`` causes of :func:`capacity_failure_causes` that are errors.

    Those are request errors, busy or stale responses and bot errors.
    """
    causes = []
    key_requests = result.key_requests or 0
    request_errors = result.request_errors or 0
    if request_errors > max(
        limits.allowed_request_errors,
        limits.max_request_error_rate * key_requests,
    ):
        causes.append((plural(request_errors, "request error"), True))
    busy_responses = result.busy_responses or 0
    if busy_responses > max(
        limits.allowed_busy_responses,
        limits.max_busy_response_rate * key_requests,
    ):
        causes.append((plural(busy_responses, "busy/stale response"), True))
    bot_errors = result.bot_errors or 0
    max_bot_errors = limits.max_bot_error_rate * (result.total_bots_started or 0)
    if bot_errors > max_bot_errors:
        kinds = result.bot_error_kinds or {}
        connection_errors = sum(kinds.get(kind, 0) for kind in _CONNECTION_LIMIT_KINDS)
        causes.append(
            (
                describe_bot_errors(result),
                bot_errors - connection_errors > max_bot_errors,
            )
        )
    return causes


def exceeded_error_limits(result, limits=CapacityLimits()):
    """Return whether ``result`` had too many request errors, busy responses or bot errors."""
    return bool(_error_causes(result, limits))


def capacity_failures(result, limits=CapacityLimits()):
    """Return the reasons a test result exceeded ``limits`` (empty if it did not)."""
    return [reason for reason, _ in capacity_failure_causes(result, limits)]


# The suggested participant cap leaves this share of the capacity.
CAPACITY_HEADROOM = 0.8


@dataclass
class CapacityOutcome:
    """What the tests of a capacity search, or a list of bot counts, show about capacity.

    Built by :func:`capacity_outcome`.
    """

    # The largest passing bot count below the smallest failing one.
    capacity: int | None
    # Every passing bot count.
    passed: list[int]
    # The test with the smallest failing bot count, and its failure causes
    # from capacity_failure_causes.
    first_fail: PerformanceTestResult | None
    first_causes: list
    # Whether the first failure only shows that the test couldn't measure
    # the server.
    unmeasured: bool
    # The first failure's wait-timeout reason, if it had too many.
    wait_cause: str | None
    # The first failure's busy-chain reason, if too many participants got
    # fewer trials because every chain was busy. Unlike wait timeouts, this
    # sets the capacity: how often chains are busy depends on how many
    # participants take part at once, so a cap reduces it.
    busy_cause: str | None
    # Whether wait timeouts were the first failure's only server limit; they
    # can come from the design, so alone they don't show the capacity.
    waits_only: bool

    @property
    def cap(self):
        """Return the suggested participant cap, or ``None`` if the tests didn't find a limit."""
        if (
            self.capacity is None
            or self.first_fail is None
            or self.unmeasured
            or self.waits_only
        ):
            return None
        return max(1, int(self.capacity * CAPACITY_HEADROOM))


def capacity_outcome(results, limits=CapacityLimits()):
    """Return the :class:`CapacityOutcome` of ``results``, ignoring any confirmation test."""
    causes = [
        (r, capacity_failure_causes(r, limits)) for r in results if not r.confirmation
    ]
    passed = [r.n_bots for r, result_causes in causes if not result_causes]
    failed = [(r, result_causes) for r, result_causes in causes if result_causes]
    first_fail, first_causes = (
        min(failed, key=lambda f: f[0].n_bots) if failed else (None, [])
    )
    wait_cause = first_fail and wait_timeout_cause(first_fail, limits) or None
    busy_cause = first_fail and busy_early_finish_cause(first_fail, limits) or None
    return CapacityOutcome(
        capacity=max(
            (n for n in passed if first_fail is None or n < first_fail.n_bots),
            default=None,
        ),
        passed=passed,
        first_fail=first_fail,
        first_causes=first_causes,
        unmeasured=not any(server_limit for _, server_limit in first_causes),
        wait_cause=wait_cause,
        busy_cause=busy_cause,
        waits_only=bool(wait_cause)
        and not any(
            server_limit and reason != wait_cause
            for reason, server_limit in first_causes
        ),
    )


# A failed confirmation suggests at least this share of its bot count, because
# a queue that never drains overshoots its limit by far more than the load does.
_MIN_CONFIRMATION_RETRY_SHARE = 0.5


def overshoot(result, limits):
    """Return how many times its limit the worst load-dependent measure of ``result`` reached.

    The measures are response times, the high-priority async queue wait
    and, for each trial maker, the share of bots that got fewer trials
    because every chain was busy. Returns ``None`` if none exceeded its limit, e.g. when only
    errors did.
    """
    ratios = []
    p95s = [result.p95_response_time, *(result.endpoint_p95 or {}).values()]
    ratios += [float(p) / limits.max_p95_s for p in p95s if p is not None]
    queue_wait = queue_wait_p95(result)
    if queue_wait is not None and limits.max_queue_p95_s:
        ratios.append(queue_wait / limits.max_queue_p95_s)
    allowed_busy = limits.allowed_busy_early_finishes_for(result.total_bots_started)
    if allowed_busy:
        ratios += [
            stats["participants"] / allowed_busy
            for stats in (result.busy_early_finishes or {}).values()
        ]
    worst = max(ratios, default=0)
    return worst if worst > 1 else None


def retry_bot_count(result, limits):
    """Return the bot count to try after ``result``, a confirmation test, exceeded the limits.

    Divides its bot count by :func:`overshoot`, keeping between half and
    :data:`CAPACITY_HEADROOM` of it.
    """
    ratio = overshoot(result, limits) or 1 / CAPACITY_HEADROOM
    share = min(CAPACITY_HEADROOM, max(_MIN_CONFIRMATION_RETRY_SHARE, 1 / ratio))
    return max(1, int(result.n_bots * share))


def next_capacity_probe(highest_pass, lowest_fail, max_bots=CAPACITY_SEARCH_MAX):
    """Return the next bot count for the capacity search, or ``None`` when done.

    Parameters
    ----------
    highest_pass : int or None
        Largest bot count that has passed so far.
    lowest_fail : int or None
        Smallest bot count that has failed so far.
    max_bots : int
        The search never goes above this count.

    Returns
    -------
    int or None
        The bot count to test next, or ``None`` once the passing and failing
        counts are close enough or ``max_bots`` has passed.
    """
    if lowest_fail is None:
        if highest_pass is None:
            return CAPACITY_SEARCH_START
        if highest_pass >= max_bots:
            return None
        return min(highest_pass * 2, max_bots)
    lower = highest_pass or 0
    if lowest_fail - lower <= max(1, lower * _CAPACITY_RESOLUTION):
        return None
    return (lower + lowest_fail) // 2

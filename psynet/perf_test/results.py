"""What a performance test measured, and whether it stayed within capacity limits.

:class:`PerformanceTestResult` holds one test's measurements and is what
``--json-output`` saves. :class:`CapacityLimits` and :func:`capacity_failures`
decide whether a result passes, and :func:`next_capacity_probe` chooses the
next bot count of a capacity search. :func:`default_duration_minutes`
chooses how long a test lasts from how long a participant session takes.

Failures from waiting too long, such as timed-out holds, count against
capacity (see :func:`_is_wait_timeout`); others, such as prescreens, are
reported only. Participants who got fewer trials because every chain was
busy count against capacity in the same way (see
:func:`busy_early_finish_cause`), although they are not failed.

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
# a capacity search of a long study stays practical.
_DEFAULT_SESSIONS_PER_TEST = 1.5
_MAX_DEFAULT_DURATION_MINUTES = 30


def default_duration_minutes(session_minutes, minimum):
    """Return how long a test lasts by default, in whole minutes.

    Parameters
    ----------
    session_minutes : float or None
        How long a bot takes the experiment: the timeline's estimated
        duration times the bots' time factor. ``None`` or 0 if unknown.
    minimum : float
        The shortest default, ``Experiment.test_duration_minutes``.

    Returns
    -------
    float
        1.5 sessions rounded up, at least ``minimum`` and at most 30 minutes
        (unless ``minimum`` is longer).
    """
    if not session_minutes:
        return minimum
    sessions = math.ceil(_DEFAULT_SESSIONS_PER_TEST * session_minutes)
    return max(minimum, min(sessions, _MAX_DEFAULT_DURATION_MINUTES))


def short_test_warning(duration_minutes, session_minutes):
    """Return a warning if a test is shorter than one participant session, else ``None``."""
    if not session_minutes or duration_minutes >= session_minutes:
        return None
    return (
        f"The test lasts {duration_minutes:g} min, but a participant session takes "
        f"about {session_minutes:.1f} min, so the test only sees the start of the "
        "study, when every bot arrives at once, and not its steady state. Use "
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
    q_delay_median: float | None = None
    q_delay_p95: float | None = None
    # How long the oldest async process still queued at the end had waited.
    oldest_queued_s: float | None = None
    # Duration and queue-delay statistics by trial maker and process label.
    process_stats: list[dict] = field(default_factory=list)
    # Trials per bot that succeeded.
    min_trial_count: int | None = None
    median_trial_count: int | None = None
    max_trial_count: int | None = None
    # Bots whose chain trial makers finished a block early because every
    # eligible chain or node was busy, by trial maker (see
    # measure.busy_early_finish_stats).
    busy_early_finishes: dict[str, dict] = field(default_factory=dict)
    n_rq_workers: int | None = None
    # Jobs the async workers can run at once.
    n_rq_job_slots: int | None = None
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


# Statistics in each entry of PerformanceTestResult.process_stats, besides
# trial_maker_id, label and count.
PROCESS_STAT_KEYS = (
    "avg",
    "median",
    "p95",
    "max",
    "q_avg",
    "q_median",
    "q_p95",
    "q_share",
)


POSTGRES_FULL = "PostgreSQL out of connections"


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

    from psynet.isolated_environment import postgres_connection_limit_message

    cause, seen = err, set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if postgres_connection_limit_message(cause):
            return POSTGRES_FULL
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
        Largest acceptable time async processes spend waiting for a worker,
        measured by :func:`queue_wait_p95`.
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
        usually comes from the design and loses data, so the default matches
        ``max_wait_timeout_rate``.
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

    @classmethod
    def from_options(cls, max_p95_s=None, max_queue_p95_s=None):
        """Return limits from optional settings; ``None`` means the default."""
        defaults = cls()
        return cls(
            max_p95_s=defaults.max_p95_s if max_p95_s is None else float(max_p95_s),
            max_queue_p95_s=(
                defaults.max_queue_p95_s
                if max_queue_p95_s is None
                else float(max_queue_p95_s)
            ),
        )

    def describe(self, include_queue=True):
        """Return the limits as a phrase, for summaries.

        Pass ``include_queue=False`` when the tests ran no async processes.
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
            f"{self.max_busy_early_finish_rate:.0%} getting fewer trials "
            "because every chain was busy"
        )
        if not include_queue:
            return f"{response} and {errors}"
        return (
            f"{response}, p95 async queue wait under {self.max_queue_p95_s:g} s "
            f"and {errors}"
        )


def queue_wait_p95(result):
    """Return the 95th-percentile async queue delay, counting any unfinished backlog.

    Processes still waiting when the test ended have no ``queue_delay`` yet,
    so the wait of the oldest one is used instead whenever it is longer.
    Returns ``None`` if the test ran no async processes.
    """
    waits = [
        float(v) for v in (result.q_delay_p95, result.oldest_queued_s) if v is not None
    ]
    return max(waits) if waits else None


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
        Also give the share of bots and their median number of trials, e.g.
        ``23 of 150 participants (15%) got fewer trials in main_chain because
        every chain was busy; median 41 of 60 trials``.
    """
    stats = result.busy_early_finishes[trial_maker_id]
    n, started = stats["participants"], result.total_bots_started or 0
    who = plural(n, "participant")
    if detail and started:
        who = f"{n:,} of {plural(started, 'participant')} ({n / started:.0%})"
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
    ``limits.max_busy_early_finish_rate``.
    """
    allowed = limits.max_busy_early_finish_rate * (result.total_bots_started or 0)
    over = [
        describe_busy_early_finish(result, trial_maker_id)
        for trial_maker_id, stats in (result.busy_early_finishes or {}).items()
        if stats["participants"] > allowed
    ]
    return " and ".join(over) or None


# The shortest steady state that the report shows separately from the start-up.
MIN_STEADY_STATE_S = 60


def phase_limit_reasons(phase, limits, oldest_queued_s=None):
    """Return the response-time, request-error and queue limits that one phase exceeded.

    ``phase`` is :attr:`PerformanceTestResult.startup_phase` or
    :attr:`~PerformanceTestResult.steady_state_phase`. Pass the result's
    ``oldest_queued_s`` for the steady state, which a backlog left at the end
    belongs to, as in :func:`queue_wait_p95`.
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
    waits = [w for w in (phase.get("q_delay_p95"), oldest_queued_s) if w is not None]
    if waits and max(waits) > limits.max_queue_p95_s:
        reasons.append(f"p95 async queue wait {max(waits):.2f} s")
    return reasons


def capacity_failure_causes(result, limits):
    """Return ``(reason, server_limit)`` for each limit that ``result`` exceeded.

    ``server_limit`` is False when the reason only shows that the test could
    not measure the server at this bot count: bots didn't all start or take
    part at once, bots in a busy process ran too late to keep pace
    (so the server got less load than that many participants would give),
    bots failed because PostgreSQL ran out of connections (the
    bots open their own database connections in the processes running them,
    which participants don't), or no responses were recorded while bots were
    missing.
    """
    causes = [("server stopped", True)] if result.server_stopped else []
    tester_limits = _tester_limits(result)
    causes += [(reason, False) for reason in tester_limits]
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
        postgres_errors = (result.bot_error_kinds or {}).get(POSTGRES_FULL, 0)
        causes.append(
            (
                describe_bot_errors(result),
                bot_errors - postgres_errors > max_bot_errors,
            )
        )
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
        causes.append((f"p95 async queue wait {queue_wait:.2f} s", True))
    return causes


def capacity_failures(result, limits=CapacityLimits()):
    """Return the reasons a test result exceeded ``limits`` (empty if it did not)."""
    return [reason for reason, _ in capacity_failure_causes(result, limits)]


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

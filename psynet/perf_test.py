"""Load tests that run simulated participants against a PsyNet server.

:class:`PerformanceTester` backs ``psynet performance-test``. It runs bots as
threads (each a :class:`~psynet.bot.BotDriver` making real HTTP requests),
keeps a fixed number of them taking the experiment at once, and
then reads the server's ``Request`` and ``AsyncProcess`` tables to measure
response times and async queue waits. Measurements cover only the test window:
requests logged before the bots were told to stop and processes that started
by then, plus the wait of the oldest process still queued at the end.

:meth:`PerformanceTester.find_capacity` searches for the
largest bot count that stays within :class:`CapacityLimits`.

One Python process can only run so many bot threads: they share its
interpreter lock, and at a few hundred requests per second the process runs
out of CPU and every bot slows down, so the server gets less load than the bot
count suggests. Large tests therefore spread their bot threads over several
child processes (:class:`_BotProcesses`). The children only run bots; they
report each bot's progress to this process, which keeps all the bookkeeping
and reads all the results, exactly as with bot threads of its own. Bots share
their process, so experiment code they run must not rely on per-process state.
"""

import datetime
import logging
import math
import multiprocessing
import os
import queue
import random
import signal
import sys
import threading
import time
import traceback
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from urllib.parse import urlparse

from tabulate import tabulate

from psynet.log import bold, error, success, warning

logger = logging.getLogger(__name__)

_SERVER_CHECK_INTERVAL_S = 5
_BACKLOG_DRAIN_TIMEOUT_S = 120
_BOT_THREAD_PREFIX = "psynet-bot-"

DEFAULT_MAX_P95_S = 0.5
DEFAULT_MAX_QUEUE_P95_S = 5.0
_CAPACITY_SEARCH_START = 10
_CAPACITY_SEARCH_MAX = 2000
# The search stops once the gap between the largest passing and smallest
# failing bot counts is within this fraction of the passing count.
_CAPACITY_RESOLUTION = 0.1
_CAPACITY_HEADROOM = 0.8
_RAMP_UP_WARNING_SHARE = 0.25
_OPEN_FILE_TARGET = 65536
_MACOS_OPEN_FILE_MAX = 10240
# At realistic pacing a process runs about this many bots on well under a core.
_BOTS_PER_PROCESS = 250
_BOT_PROCESS_START_TIMEOUT_S = 300
# How much longer than the bots' stop timeout to wait for bot processes to reply.
_BOT_PROCESS_REPLY_GRACE_S = 10
_LAG_PROBE_INTERVAL_S = 0.05
_BOT_PROCESS_EXIT_JOIN_S = 5


def _is_bot_thread_record(record):
    """Return whether a log record came from a bot thread."""
    return record.threadName.startswith(_BOT_THREAD_PREFIX)


@contextmanager
def _bot_logs_to(stream):
    """Send log records from bot threads to ``stream`` rather than the console.

    Bot output still reaches the console with ``--debug``.
    """
    root = logging.getLogger()
    hidden_from = []
    if logger.getEffectiveLevel() > logging.DEBUG:
        for handler in root.handlers:
            handler.addFilter(_hide_bot_thread_records)
            hidden_from.append(handler)
    bot_handler = None
    if stream is not None:
        bot_handler = logging.StreamHandler(stream)
        bot_handler.addFilter(_is_bot_thread_record)
        bot_handler.setFormatter(
            logging.Formatter("%(threadName)s %(levelname)s %(message)s")
        )
        root.addHandler(bot_handler)
    try:
        yield
    finally:
        for handler in hidden_from:
            handler.removeFilter(_hide_bot_thread_records)
        if bot_handler is not None:
            root.removeHandler(bot_handler)


def log_to_console(level, console_level=None):
    """Make the root logger print bare messages to stdout, replacing its handlers.

    Records below ``console_level`` (by default ``level``) are not printed.
    """
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level or level)
    console.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [console]


def _hide_bot_thread_records(record):
    """Log filter that drops bot-thread records from the console."""
    return not _is_bot_thread_record(record)


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------


def _to_json_safe(value):
    """
    Recursively convert a value to a JSON-safe form.

    Handles Decimal, datetime, NaN/Inf, sets/frozensets, tuples, dicts, and lists.
    Sets are emitted in sorted order so output is deterministic across runs.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # Check bool before int since bool is a subclass of int
        return value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if value != value or value == float("inf") or value == float("-inf"):
            # NaN or Inf -> None (JSON doesn't support these)
            return None
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        # Sort for deterministic JSON output — sets have no native order,
        # which would produce noisy diffs when results are stored in git.
        # Fall back to insertion order if items are mutually incomparable.
        items = [_to_json_safe(item) for item in value]
        try:
            return sorted(items, key=lambda x: (x is None, str(type(x)), x))
        except TypeError:
            return items
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    # Fallback for unknown types
    return str(value)


def run_parallel_test(n_bots, time_factor, stagger_interval_s, check_bots):
    """Run ``n_bots`` bots at once, each in its own thread, then check them.

    The first bot error is re-raised once every bot has finished.
    """
    from dallinger import db

    from psynet.db import transaction
    from psynet.experiment import get_experiment

    from .bot import Bot, BotDriver

    logger.info(f"Testing experiment with {n_bots} parallel bots...")
    experiment = get_experiment()
    errors = []

    def run_bot():
        try:
            experiment.run_bot(BotDriver(), time_factor=time_factor)
        # pytest.fail() and pytest.skip() raise BaseException subclasses.
        except BaseException as err:
            logger.exception("Bot failed.")
            errors.append(err)
        finally:
            db.session.remove()

    threads = []
    for i in range(n_bots):
        if i > 0:
            time.sleep(stagger_interval_s)
        thread = threading.Thread(
            target=run_bot, name=f"{_BOT_THREAD_PREFIX}{i + 1}", daemon=True
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]

    with transaction():
        check_bots(Bot.query.all())


def raise_open_file_limit():
    """Raise this process's soft open-file limit to 65536, or its hard limit if lower.

    Each bot holds its own database and HTTP connections, and the default soft
    limit (often 1024, or 256 on macOS) runs out at a few hundred bots.
    """
    try:
        import resource
    except ImportError:
        return
    infinity = resource.RLIM_INFINITY
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = _OPEN_FILE_TARGET if hard == infinity else min(hard, _OPEN_FILE_TARGET)
    if soft == infinity or soft >= target:
        return
    # macOS refuses limits above its per-process maximum, whatever the hard limit.
    for limit in dict.fromkeys([target, min(target, _MACOS_OPEN_FILE_MAX)]):
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))
            return
        except (ValueError, OSError) as e:
            error = e
    logger.warning(f"Could not raise the open-file limit above {soft}: {error}")


class _LoadMonitor:
    """Measure how busy this process is from creation until :meth:`stop`.

    A daemon thread repeatedly waits for 50 ms and records how much later
    than that it wakes up. Bot threads queue just as long for the
    interpreter lock and the CPU before they can act, so this lag is how
    late the bots in this process run.
    """

    def __init__(self):
        self._lags_ms = Counter()
        self._stopped = threading.Event()
        self._cpu_start = time.process_time()
        self._wall_start = time.monotonic()
        self._thread = threading.Thread(
            target=self._probe, name="psynet-lag-probe", daemon=True
        )
        self._thread.start()

    def _probe(self):
        while True:
            start = time.monotonic()
            if self._stopped.wait(_LAG_PROBE_INTERVAL_S):
                return
            lag = time.monotonic() - start - _LAG_PROBE_INTERVAL_S
            self._lags_ms[max(0, round(lag * 1000))] += 1

    def stop(self):
        """Stop measuring and return this process's load since it started.

        Returns
        -------
        tuple of (float or None, float or None)
            The CPU time used per second, counting every thread, so 1.0 means
            a whole core; and the 95th-percentile lag in seconds.
        """
        wall_s = time.monotonic() - self._wall_start
        cpu_s = time.process_time() - self._cpu_start
        self._stopped.set()
        self._thread.join()
        lag_p95_ms = _quantile(sorted(self._lags_ms.elements()), 0.95)
        return (
            cpu_s / wall_s if wall_s > 0 else None,
            None if lag_p95_ms is None else lag_p95_ms / 1000,
        )


def _worst(process_loads, i):
    """Return the largest non-missing item ``i`` of the ``(cpu_share, lag_p95_s)`` pairs."""
    return max((load[i] for load in process_loads if load[i] is not None), default=None)


def _fit_redis_pool_to_bots(n_bots):
    """Let every bot thread hold a Redis connection at once.

    All bots share this process's Redis pool. A plain ``ConnectionPool`` fails
    bots with ``MaxConnectionsError`` at its limit (100 by default in
    redis-py 8). A ``BlockingConnectionPool`` makes them wait, and its queue
    of free slots is sized when it is created, so that queue grows too.
    """
    import redis
    from dallinger.db import redis_conn

    pool = redis_conn.connection_pool
    needed = n_bots + 100
    if pool.max_connections >= needed:
        return
    extra = needed - pool.max_connections
    pool.max_connections = needed
    if isinstance(pool, redis.BlockingConnectionPool):
        pool.pool.maxsize = needed
        for _ in range(extra):
            pool.pool.put_nowait(None)


def _choose_bot_processes(requested, max_bots):
    """Return how many processes to run up to ``max_bots`` bots in.

    ``"auto"`` gives a process per 250 bots, but at most one per four CPU
    cores, because bots run on the experiment server in ``performance-test
    ssh`` and must leave it most of its CPU.
    """
    if requested == "auto":
        by_cpu = (os.cpu_count() or 1) // 4
        return max(1, min(math.ceil(max_bots / _BOTS_PER_PROCESS), by_cpu))
    return max(1, min(int(requested), max_bots))


def _join_threads(threads, timeout_s):
    """Wait up to ``timeout_s`` in all for ``threads``; return how many still run."""
    deadline = time.time() + timeout_s
    for thread in threads:
        thread.join(max(0.0, deadline - time.time()))
    return sum(thread.is_alive() for thread in threads)


def _ended_early(result):
    """Return whether a test ended in a way that stops its suite."""
    return bool(result["server_stopped"] or result.get("bot_process_failure"))


class PerformanceTester:
    def __init__(
        self,
        authenticated_session,
        base_url,
        n_bots=1,
        duration_minutes=1,
        stagger_interval_s=0.1,
        time_factor=0.0,
        limits=None,
        bot_processes=1,
    ):
        """Set up a performance tester.

        Parameters
        ----------
        bot_processes : int or "auto"
            Number of processes to run the bots in. With 1 they run as threads
            in this process; ``"auto"`` chooses from the most bots a suite
            runs and the CPU count (see :func:`_choose_bot_processes`).
        """
        self.authenticated_session = authenticated_session
        self.base_url = base_url
        self.n_bots = n_bots
        self.duration_minutes = duration_minutes
        self.stagger_interval_s = stagger_interval_s
        self.time_factor = time_factor
        self.limits = limits or CapacityLimits()
        self.bot_processes = bot_processes
        self._n_bot_processes = 1
        # Runs the bots: _ThreadBots, or _BotProcesses during a suite that
        # needs several processes.
        self._bots = _ThreadBots(self)
        # Experiment code shares this process and may call random.seed().
        self._random = random.Random()

    def run(self, bot_counts=None, bot_log_file=None):
        """Run performance tests for one or more bot count values."""
        bot_counts = bot_counts or [self.n_bots]
        self._print_suite_header(", ".join(str(n) for n in bot_counts))

        def next_bot_count(results):
            return bot_counts[len(results)] if len(results) < len(bot_counts) else None

        return self._run_suite(
            max(bot_counts), next_bot_count, bot_log_file, n_tests=len(bot_counts)
        )

    def find_capacity(self, bot_log_file=None):
        """Search for the largest bot count the server handles within limits.

        Doubles the bot count from 10 until a test fails
        :func:`capacity_failures`, then bisects between the largest passing and
        smallest failing counts until they are within 10% of each other.

        Returns
        -------
        list[dict]
            One result per test, in the order they ran.
        """
        self._print_suite_header(
            f"automatic (from {_CAPACITY_SEARCH_START}, while keeping "
            f"{self.limits.describe()}; a test in which bots can't start fast "
            "enough, or run late because their process is too busy, "
            "could not be tested)"
        )
        max_tests = _max_capacity_probes()
        logger.info(
            f"Expected run time:    up to {max_tests} tests, about "
            f"{max_tests * self.duration_minutes:g} min plus pauses between tests"
        )
        highest_pass = lowest_fail = None

        def next_bot_count(results):
            nonlocal highest_pass, lowest_fail
            if results:
                n_bots = results[-1]["n_bots"]
                causes = _capacity_failure_causes(results[-1], self.limits)
                if causes:
                    outcome = (
                        "exceeded limits"
                        if any(server_limit for _, server_limit in causes)
                        else "could not be tested"
                    )
                    reasons = "; ".join(reason for reason, _ in causes)
                    logger.info(warning(f"{n_bots:,} bots {outcome}: {reasons}"))
                    lowest_fail = n_bots
                else:
                    highest_pass = n_bots
            return next_capacity_probe(highest_pass, lowest_fail)

        return self._run_suite(_CAPACITY_SEARCH_MAX, next_bot_count, bot_log_file)

    def _run_suite(self, max_bots, next_bot_count, bot_log_file, n_tests=None):
        """Run tests until ``next_bot_count(results_so_far)`` returns ``None``.

        Stops early if a test ends early, then prints the summary. ``max_bots``
        is the most bots any test may run, which sets the bot processes.

        Returns
        -------
        list[dict]
            One result per test, in the order they ran.
        """
        raise_open_file_limit()
        all_results = []
        with self._bot_runner(max_bots, bot_log_file):
            self._suite_started_at = datetime.datetime.now()
            while (n_bots := next_bot_count(all_results)) is not None:
                if all_results:
                    self._pause_between_tests()
                label = f"{len(all_results) + 1}" + (f"/{n_tests}" if n_tests else "")
                result = self._run_one_test(label, n_bots, bot_log_file)
                all_results.append(result)
                if _ended_early(result):
                    break
        self._print_performance_summary(all_results)
        return all_results

    @contextmanager
    def _bot_runner(self, max_bots, bot_log_file):
        """Start the bot processes a suite of up to ``max_bots`` bots needs, if any.

        They last for the whole suite, because each one imports the
        experiment, which can take seconds and much memory.
        """
        n_processes = _choose_bot_processes(self.bot_processes, max_bots)
        self._n_bot_processes = n_processes
        chosen = " (auto)" if self.bot_processes == "auto" else ""
        logger.info(f"Bot processes:        {n_processes}{chosen}")
        if n_processes == 1:
            yield
            return
        log_path = getattr(bot_log_file, "name", None)
        logger.info(f"Starting {n_processes} bot processes...")
        self._bots = _BotProcesses(
            n_processes,
            stagger_interval_s=self.stagger_interval_s,
            time_factor=self.time_factor,
            bot_log_path=log_path if os.path.isfile(str(log_path)) else None,
        )
        try:
            yield
        finally:
            bot_processes, self._bots = self._bots, _ThreadBots(self)
            bot_processes.close()

    def _pause_between_tests(self):
        """Pause, then let async processes queued by earlier tests start.

        Otherwise they would hold up the next test's processes and count
        against its queue wait.
        """
        from dallinger import db
        from sqlalchemy import func

        from psynet.process import AsyncProcess

        time.sleep(5)
        deadline = time.monotonic() + _BACKLOG_DRAIN_TIMEOUT_S
        announced = False
        while True:
            queued = (
                db.session.query(func.count(AsyncProcess.id))
                .filter(
                    AsyncProcess.time_enqueued >= self._suite_started_at,
                    AsyncProcess.time_started.is_(None),
                    AsyncProcess.failed.is_(False),
                )
                .scalar()
            )
            db.session.rollback()
            if not queued:
                return
            if time.monotonic() >= deadline:
                logger.warning(
                    warning(
                        f"{queued:,} async processes from earlier tests are still "
                        "queued, so they may slow the next test's processes."
                    )
                )
                return
            if not announced:
                logger.info(
                    f"Waiting for {queued:,} queued async processes to start..."
                )
                announced = True
            time.sleep(2)

    def _print_suite_header(self, bots_description):
        logger.info(bold("=" * 80))
        logger.info(bold("\u26a1 PERFORMANCE TEST SUITE"))
        logger.info(f"Bots per test:        {bots_description}")
        logger.info(f"Test duration:        {self.duration_minutes:g} min")
        logger.info(f"Bot start stagger:    ~{self.stagger_interval_s:g}s")
        logger.info(f"Bot time factor:      {self.time_factor:g}")

    def _run_one_test(self, label, n_bots, bot_log_file):
        logger.info("")
        logger.info(bold("=" * 80))
        logger.info(bold(f"TEST {label}: Running with {n_bots:,} concurrent bots"))
        return self._test_performance(n_bots, bot_log_file=bot_log_file)

    def _print_performance_summary(self, results):
        """Print cross-test comparison table and the capacity it implies."""
        for line in format_performance_summary(results):
            logger.info(line)
        for line in format_capacity_summary(results, self.limits, self.time_factor):
            logger.info(line)

    def _test_performance(self, n, bot_log_file):
        """Run a load test with n concurrent bots for configured duration."""
        duration_minutes = self.duration_minutes
        logger.info("")
        logger.info(
            "\u25b6 Starting load test with {n:,} concurrent bots for {duration_minutes} minutes...".format(
                n=n, duration_minutes=duration_minutes
            )
        )

        initial_state = self._capture_initial_state()
        bot_state = self._initialize_bot_tracking()
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        self._bots.begin_test(bot_state, end_time, n)

        # Only bot threads in this process log here; bot processes append
        # to the same file themselves.
        with _bot_logs_to(bot_log_file):
            try:
                self._run_monitoring_loop(
                    n, bot_state, self._bots.start_slot, start_time, end_time
                )
                actual_duration = time.time() - start_time
                last_request_id = self._max_request_id()
                ended_at = datetime.datetime.now()
            finally:
                self._stop_bots(bot_state)
        self._clear_realtime_status()

        return self._calculate_and_report_results(
            n,
            duration_minutes,
            actual_duration,
            initial_state,
            bot_state,
            last_request_id,
            ended_at,
        )

    @staticmethod
    def _max_request_id():
        """Return the ID of the most recently logged request, or 0 if none."""
        from dallinger import db
        from sqlalchemy import func

        from psynet.experiment import Request

        return db.session.query(func.max(Request.id)).scalar() or 0

    def _capture_initial_state(self):
        """Capture initial database state before test."""
        from dallinger import db
        from sqlalchemy import func

        from psynet.participant import Participant
        from psynet.process import AsyncProcess

        max_request_id = self._max_request_id()
        max_process_id = db.session.query(func.max(AsyncProcess.id)).scalar() or 0
        max_participant_id = db.session.query(func.max(Participant.id)).scalar() or 0

        return {
            "max_request_id": max_request_id,
            "max_process_id": max_process_id,
            "max_participant_id": max_participant_id,
        }

    def _initialize_bot_tracking(self):
        """Initialize tracking structures for bots."""
        return {
            "lock": threading.Lock(),
            # Bot ID -> time the bot was created, for bots taking the experiment.
            "running": {},
            "total_bots_started": 0,
            "bots_completed_during_test": 0,
            "total_bot_errors": 0,
            "errored_bot_ids": set(),
            # Short description of each failure, e.g. "HTTP 500 on /response".
            "bot_error_kinds": Counter(),
            "bot_durations": [],
            "initialization_times": [],
            "first_bot_initialized": False,
            "server_stopped": False,
            "slots_started": 0,
            # Most bots that were taking part at the same moment.
            "peak_running": 0,
            # Seconds from the test start until the last bot slot started.
            "ramp_up_s": None,
            # (CPU share, p95 lag in s) of each process running bots.
            "process_loads": [],
            # Why a bot process stopped during the test, if one did.
            "bot_process_failure": None,
            # Numbers of bot processes that didn't report their load.
            "unreported_bot_processes": [],
            "last_status_update": time.time(),
            "status_line_length": 0,
        }

    def _bounded_random_multiplier(self, max_multiplier=3.0):
        """Bounded lognormal distribution for user completion times"""
        sigma = 0.6
        mu = -0.5 * sigma * sigma
        while True:
            x = self._random.lognormvariate(mu, sigma)
            if x <= max_multiplier:
                return x

    def _bounded_random_stagger(self, max_multiplier=5.0):
        """Return a gamma-distributed stagger bounded relative to its mean."""
        k = 3.0
        theta = self.stagger_interval_s / k
        if not theta:
            return 0.0
        max_stagger = max_multiplier * self.stagger_interval_s
        while True:
            x = self._random.gammavariate(k, theta)
            if x <= max_stagger:
                return x

    def _run_bot_slot(self, stop_event, end_time, record):
        """Run bots one after another until the test ends.

        Each slot stands for one participant at a time, so ``n`` slots keep
        ``n`` participants active. Slots are threads: they cost far less
        memory and start-up CPU than a process per bot, and the bots spend
        most of their time waiting on the server.

        ``record(kind, *args)`` reports each bot's progress, as handled by
        :meth:`_record_bot_event`.
        """
        from dallinger import db

        from psynet.bot import BotDriver
        from psynet.experiment import get_experiment
        from psynet.participant import DriverStopped

        experiment = get_experiment()
        while not stop_event.is_set() and time.time() < end_time:
            create_time = time.time()
            bot_id = None
            error_kind = None
            record("attempt")
            try:
                bot = BotDriver()
                bot.stop_event = stop_event
                bot_id = bot.id
                record("start", bot_id, time.time() - create_time)
                if stop_event.is_set():
                    raise DriverStopped()
                experiment.run_bot(
                    bot,
                    time_factor=self.time_factor * self._bounded_random_multiplier(),
                )
                outcome = "completed"
            except DriverStopped:
                outcome = "stopped"
            except BaseException as err:
                logger.exception("Bot %s failed.", bot_id)
                outcome = "error"
                error_kind = _describe_bot_error(err)
            finally:
                db.session.remove()
            record("end", bot_id, outcome, error_kind)
            stop_event.wait(self._bounded_random_stagger())

    @classmethod
    def _record_bot_event(cls, bot_state, end_time, kind, *args):
        """Apply one bot's progress report to ``bot_state``.

        Reports come from bot threads in this process or, as events, from
        bot processes. ``kind`` is ``"attempt"`` before a bot is created,
        ``"start"`` with ``(bot_id, init_time_s)`` once it exists, and
        ``"end"`` with ``(bot_id, outcome, error_kind)`` when it finishes.
        """
        if kind == "attempt":
            with bot_state["lock"]:
                bot_state["total_bots_started"] += 1
        elif kind == "start":
            cls._record_bot_start(bot_state, *args)
        else:
            bot_id, outcome, error_kind = args
            cls._record_bot_end(bot_state, bot_id, outcome, end_time, error_kind)

    @staticmethod
    def _record_bot_start(bot_state, bot_id, init_time):
        """Record that a bot started, for the live status and results."""
        now = time.time()
        with bot_state["lock"]:
            bot_state["initialization_times"].append(init_time)
            bot_state["first_bot_initialized"] = True
            bot_state["running"][bot_id] = now
            bot_state["peak_running"] = max(
                bot_state["peak_running"], len(bot_state["running"])
            )

    @staticmethod
    def _record_bot_end(bot_state, bot_id, outcome, end_time, error_kind=None):
        """Record how and when a bot finished."""
        now = time.time()
        with bot_state["lock"]:
            start = bot_state["running"].pop(bot_id, None)
            if outcome == "error":
                bot_state["total_bot_errors"] += 1
                bot_state["bot_error_kinds"][error_kind] += 1
                if bot_id is not None:
                    bot_state["errored_bot_ids"].add(bot_id)
            elif outcome == "completed" and now < end_time:
                bot_state["bots_completed_during_test"] += 1
            if start is not None:
                bot_state["bot_durations"].append(
                    (bot_id, now - start, outcome == "stopped")
                )

    def _stop_bots(self, bot_state, timeout_s=30):
        """Stop the bots that are still running and wait for their threads."""
        process_loads, unreported, n_alive = self._bots.end_test(timeout_s)
        bot_state["process_loads"] += process_loads
        bot_state["unreported_bot_processes"] = unreported
        if n_alive:
            logger.warning(
                f"{n_alive} bot(s) were still waiting for the server "
                f"{timeout_s} s after the test ended; their requests may "
                "still load the server during the next test."
            )

    def _show_realtime_status(self, bot_state, current_time, end_time, force=False):
        """Show real-time status update if not in debug mode and enough time has passed."""
        is_debug = logger.getEffectiveLevel() <= logging.DEBUG
        if is_debug:
            return

        # Redraw a terminal every 2 seconds; logs and SSH sessions get a new
        # line every 30 seconds instead of carriage-return redraws.
        interactive = sys.stdout.isatty()
        interval = 2 if interactive else 30
        if not force and current_time - bot_state["last_status_update"] < interval:
            return

        bot_state["last_status_update"] = current_time

        # Calculate stats
        running = len(bot_state["running"])
        completed = bot_state["bots_completed_during_test"]
        errors = bot_state["total_bot_errors"]

        # Calculate average response time from recent bot durations
        recent_durations = [d for _, d, _ in bot_state["bot_durations"][-5:]]
        avg_duration = (
            sum(recent_durations) / len(recent_durations) if recent_durations else 0
        )

        # Time remaining
        time_left = max(0, end_time - current_time)
        mins_left = int(time_left / 60)
        secs_left = int(time_left % 60)

        # Build status line
        status = f"\U0001f916 Running: {running} | \u2713 Completed: {completed:,} | \u2717 Errors: {errors} | \u23f1 Avg: {avg_duration:.1f}s | \u23f3 {mins_left}:{secs_left:02d} left"

        if not interactive:
            print(status, flush=True)
            return

        # Clear previous line and print new status
        sys.stdout.write("\r" + " " * bot_state["status_line_length"] + "\r")
        sys.stdout.write(status)
        sys.stdout.flush()
        bot_state["status_line_length"] = len(status)

    def _clear_realtime_status(self):
        """Clear the status line when progress is complete."""
        is_debug = logger.getEffectiveLevel() <= logging.DEBUG
        if not is_debug and sys.stdout.isatty():
            sys.stdout.write("\r" + " " * 150 + "\r")
            sys.stdout.flush()

    def _run_monitoring_loop(self, n, bot_state, start_bot_slot, start_time, end_time):
        """Start ``n`` staggered bot slots and watch the server until the test ends."""
        # The first bot waits for the experiment launch; the rest follow it.
        start_bot_slot()
        n_started = bot_state["slots_started"] = 1
        if n_started >= n:
            bot_state["ramp_up_s"] = 0.0
        next_slot_time = None
        next_server_check = start_time
        while time.time() < end_time:
            current_time = time.time()

            if current_time >= next_server_check:
                next_server_check = current_time + _SERVER_CHECK_INTERVAL_S
                if not server_is_reachable(self.base_url, self.authenticated_session):
                    self._clear_realtime_status()
                    logger.warning(
                        warning(
                            "The experiment server stopped during the test, so the "
                            "test ends early. A local server stops once the "
                            "experiment reports that it is complete; raise its "
                            "participant target so that the test lasts the full "
                            "duration."
                        )
                    )
                    bot_state["server_stopped"] = True
                    return
                failure = self._bots.failure()
                if failure:
                    self._clear_realtime_status()
                    logger.warning(warning(f"The test ends early: {failure}."))
                    bot_state["bot_process_failure"] = failure
                    return

            if n_started < n and bot_state["first_bot_initialized"]:
                if next_slot_time is None:
                    next_slot_time = current_time
                while n_started < n and current_time >= next_slot_time:
                    start_bot_slot()
                    n_started = bot_state["slots_started"] = n_started + 1
                    next_slot_time += self._bounded_random_stagger()
                if n_started >= n:
                    bot_state["ramp_up_s"] = time.time() - start_time

            self._show_realtime_status(bot_state, current_time, end_time)
            time.sleep(0.05)

    def _calculate_and_report_results(
        self,
        n,
        duration_minutes,
        actual_duration,
        initial_state,
        bot_state,
        last_request_id,
        ended_at,
    ):
        """Calculate final metrics and report results.

        Request statistics cover requests logged up to ``last_request_id``, i.e.
        before the bots were stopped, so that they match ``actual_duration``.
        Async processes count if they started by ``ended_at``.
        ``oldest_queued_s`` is how long the oldest async process enqueued
        during the test had been waiting for a worker at ``ended_at``, so a
        backlog that never drains still counts against capacity.
        """
        from dallinger import db
        from sqlalchemy import case, func, or_

        from psynet.bot import Bot
        from psynet.experiment import Request
        from psynet.process import AsyncProcess

        request_window = (
            Request.id > initial_state["max_request_id"],
            Request.id <= last_request_id,
        )
        requests_during_test = (
            db.session.query(func.count(Request.id)).filter(*request_window).scalar()
        )

        key_endpoints = ["/timeline", "/response"]

        stats = (
            db.session.query(
                func.count(Request.id).label("count"),
                func.avg(Request.duration).label("avg"),
                func.percentile_cont(0.5)
                .within_group(Request.duration)
                .label("median"),
                func.percentile_cont(0.95).within_group(Request.duration).label("p95"),
                func.percentile_cont(0.99).within_group(Request.duration).label("p99"),
                func.stddev_samp(Request.duration).label("stddev"),
                func.max(Request.duration).label("max"),
            )
            .filter(
                *request_window,
                Request.endpoint.in_(key_endpoints),
            )
            .one()
        )

        endpoint_p95 = dict(
            db.session.query(
                Request.endpoint,
                func.percentile_cont(0.95).within_group(Request.duration),
            )
            .filter(*request_window, Request.endpoint.in_(key_endpoints))
            .group_by(Request.endpoint)
            .all()
        )

        request_errors, busy_responses = _split_failed_requests(
            db.session.query(Request.status_code, func.count(Request.id))
            .filter(
                *request_window,
                Request.endpoint.in_(key_endpoints),
                Request.status_code >= 400,
            )
            .group_by(Request.status_code)
            .all()
        )

        # Like requests, only count processes that started before the test
        # ended: jobs left queued while the bots stop would otherwise report
        # the stop time as queue delay. Those are covered by oldest_queued_s.
        # Queue delay is known once a process starts, so it also covers
        # processes that were still running.
        queue_window = (
            AsyncProcess.id > initial_state["max_process_id"],
            AsyncProcess.time_started <= ended_at,
            AsyncProcess.queue_delay.isnot(None),
        )
        process_window = (
            *queue_window,
            AsyncProcess.finished == True,  # noqa: E712
        )

        # Async process duration stats, grouped by (trial_maker_id, label).
        process_stats_rows = (
            db.session.query(
                AsyncProcess.trial_maker_id,
                AsyncProcess.label,
                func.count(AsyncProcess.id).label("count"),
                func.avg(AsyncProcess.time_taken).label("avg"),
                func.percentile_cont(0.5)
                .within_group(AsyncProcess.time_taken)
                .label("median"),
                func.percentile_cont(0.95)
                .within_group(AsyncProcess.time_taken)
                .label("p95"),
                func.max(AsyncProcess.time_taken).label("max"),
                func.avg(AsyncProcess.queue_delay).label("q_avg"),
                func.percentile_cont(0.5)
                .within_group(AsyncProcess.queue_delay)
                .label("q_median"),
                func.percentile_cont(0.95)
                .within_group(AsyncProcess.queue_delay)
                .label("q_p95"),
                func.avg(
                    case(
                        (
                            (AsyncProcess.queue_delay + AsyncProcess.time_taken) > 0,
                            AsyncProcess.queue_delay
                            / (AsyncProcess.queue_delay + AsyncProcess.time_taken),
                        ),
                        else_=None,
                    )
                ).label("q_share"),
            )
            .filter(*process_window)
            .group_by(AsyncProcess.trial_maker_id, AsyncProcess.label)
            .all()
        )
        process_stats = [
            {
                "trial_maker_id": row.trial_maker_id or "",
                "label": row.label or "",
                "count": row.count,
                "avg": row.avg,
                "median": row.median,
                "p95": row.p95,
                "max": row.max,
                "q_avg": row.q_avg,
                "q_median": row.q_median,
                "q_p95": row.q_p95,
                "q_share": row.q_share,
            }
            for row in process_stats_rows
        ]

        q_delay_median, q_delay_p95 = (
            db.session.query(
                func.percentile_cont(0.5).within_group(AsyncProcess.queue_delay),
                func.percentile_cont(0.95).within_group(AsyncProcess.queue_delay),
            )
            .filter(*queue_window)
            .one()
        )

        oldest_enqueued = (
            db.session.query(func.min(AsyncProcess.time_enqueued))
            .filter(
                AsyncProcess.id > initial_state["max_process_id"],
                AsyncProcess.time_enqueued <= ended_at,
                AsyncProcess.failed.is_(False),
                or_(
                    AsyncProcess.time_started.is_(None),
                    AsyncProcess.time_started > ended_at,
                ),
            )
            .scalar()
        )
        oldest_queued_s = (
            (ended_at - oldest_enqueued).total_seconds() if oldest_enqueued else None
        )

        bots = Bot.query.filter(Bot.id > initial_state["max_participant_id"]).all()
        # A bot whose thread raised failed, whatever status the server recorded.
        bot_status_map = {
            b.id: "failed" if b.id in bot_state["errored_bot_ids"] else b.status
            for b in bots
        }
        succeeded_statuses = {"approved", "submitted"}
        bots_succeeded = bots_failed = bots_incomplete = 0
        for status in bot_status_map.values():
            if status in succeeded_statuses:
                bots_succeeded += 1
            elif status == "working":
                bots_incomplete += 1
            else:
                bots_failed += 1

        succeeded_bots = [b for b in bots if bot_status_map[b.id] in succeeded_statuses]
        wait_page_times = sorted(
            b.total_wait_page_time
            for b in succeeded_bots
            if b.total_wait_page_time is not None
        )
        median_wait_page_time = _quantile(wait_page_times, 0.5)
        p95_wait_page_time = _quantile(wait_page_times, 0.95)
        max_wait_page_time = _quantile(wait_page_times, 1)

        avg_response_time = stats.avg
        median_response_time = stats.median
        p95_response_time = stats.p95
        p99_response_time = stats.p99
        stddev_response_time = stats.stddev
        max_response_time = stats.max

        def _trial_count_stats(bot_ids):
            from psynet.trial.main import Trial  # noqa: lazy to avoid circular

            if not bot_ids:
                return None, None, None
            rows = (
                db.session.query(
                    Trial.participant_id, func.count(Trial.id).label("n_trials")
                )
                .filter(
                    Trial.participant_id.in_(bot_ids),
                    Trial.failed == False,  # noqa: E712
                )
                .group_by(Trial.participant_id)
                .all()
            )
            counts = sorted(
                [0] * (len(bot_ids) - len(rows)) + [r.n_trials for r in rows]
            )
            return counts[0], _quantile(counts, 0.5), counts[-1]

        succeeded_bot_ids = [b.id for b in succeeded_bots]
        (
            min_trial_count,
            median_trial_count,
            max_trial_count,
        ) = _trial_count_stats(succeeded_bot_ids)
        succeeded_durations = [
            d
            for bot_id, d, terminated in bot_state["bot_durations"]
            if not terminated and bot_status_map.get(bot_id) in succeeded_statuses
        ]
        failed_durations = [
            d
            for bot_id, d, terminated in bot_state["bot_durations"]
            if not terminated
            and bot_status_map.get(bot_id) not in succeeded_statuses
            and bot_status_map.get(bot_id) != "working"
        ]
        incomplete_durations = [
            d
            for bot_id, d, terminated in bot_state["bot_durations"]
            if terminated or bot_status_map.get(bot_id) == "working"
        ]
        all_durations = [d for _, d, _ in bot_state["bot_durations"]]

        avg_bot_duration = _mean(all_durations)
        avg_succeeded_duration = _mean(succeeded_durations)
        avg_failed_duration = _mean(failed_durations)
        avg_incomplete_duration = _mean(incomplete_durations)
        avg_init_time = _mean(bot_state["initialization_times"])

        requests_per_sec = (
            requests_during_test / actual_duration if actual_duration > 0 else None
        )
        n_wait_page_samples = len(wait_page_times) if wait_page_times else None
        initialization_times = list(bot_state["initialization_times"])

        result = {
            "n_bots": n,
            "duration_minutes": duration_minutes,
            "actual_duration": actual_duration,
            "server_stopped": bot_state["server_stopped"],
            "bot_process_failure": bot_state["bot_process_failure"],
            "unreported_bot_processes": bot_state["unreported_bot_processes"],
            "bot_processes": self._n_bot_processes,
            "slots_started": bot_state["slots_started"],
            "peak_running": bot_state["peak_running"],
            "ramp_up_s": bot_state["ramp_up_s"],
            "tester_cpu_share": _worst(bot_state["process_loads"], 0),
            "tester_lag_p95_s": _worst(bot_state["process_loads"], 1),
            "total_bots_started": bot_state["total_bots_started"],
            "completed_during_test": bot_state["bots_completed_during_test"],
            "bots_succeeded": bots_succeeded,
            "bots_failed": bots_failed,
            "bots_incomplete": bots_incomplete,
            "total_requests": requests_during_test,
            "key_requests": stats.count,
            "requests_per_sec": requests_per_sec,
            "bot_errors": bot_state["total_bot_errors"],
            "bot_error_kinds": dict(bot_state["bot_error_kinds"].most_common()),
            "avg_response_time": avg_response_time,
            "median_response_time": median_response_time,
            "p95_response_time": p95_response_time,
            "endpoint_p95": endpoint_p95,
            "p99_response_time": p99_response_time,
            "stddev_response_time": stddev_response_time,
            "max_response_time": max_response_time,
            "avg_bot_duration": avg_bot_duration,
            "avg_init_time": avg_init_time,
            "initialization_times": initialization_times,
            "request_errors": request_errors,
            "busy_responses": busy_responses,
            "median_wait_page_time": median_wait_page_time,
            "p95_wait_page_time": p95_wait_page_time,
            "max_wait_page_time": max_wait_page_time,
            "n_wait_page_samples": n_wait_page_samples,
            "avg_succeeded_duration": avg_succeeded_duration,
            "avg_failed_duration": avg_failed_duration,
            "avg_incomplete_duration": avg_incomplete_duration,
            "q_delay_median": q_delay_median,
            "q_delay_p95": q_delay_p95,
            "oldest_queued_s": oldest_queued_s,
            "process_stats": process_stats,
            "min_trial_count": min_trial_count,
            "median_trial_count": median_trial_count,
            "max_trial_count": max_trial_count,
            "n_succeeded_bots": len(succeeded_bot_ids),
        }

        try:
            from dallinger.db import redis_conn
            from rq import Worker

            workers = Worker.all(connection=redis_conn)
            result["n_rq_workers"] = len(workers)
            # Dallinger's gevent workers record how many jobs each can run at once.
            result["n_rq_job_slots"] = sum(
                int(redis_conn.hget(w.key, "pool_size") or 1) for w in workers
            )
        except Exception as e:
            logger.warning(f"Could not count async workers: {e}")

        self._report_test_results(result)
        return result

    def _report_test_results(self, result):
        """Print detailed results after a single test completes."""
        for line in format_test_results(result):
            logger.info(line)


class _ThreadBots:
    """Run bot slots as threads in this process.

    :class:`PerformanceTester` uses this directly for one process, and each
    bot process uses it for its share of the slots (see :class:`_BotProcesses`,
    which has the same interface).
    """

    def __init__(self, tester, thread_prefix=_BOT_THREAD_PREFIX):
        self._tester = tester
        self._thread_prefix = thread_prefix
        self._stop_event, self._threads = threading.Event(), []
        self._end_time = self._record = self._load = None

    def begin_test(self, bot_state, end_time, n_bots, record=None):
        """Prepare for a test of ``n_bots`` slots that ends at ``end_time``.

        Bots report to ``record`` (see :meth:`PerformanceTester._run_bot_slot`),
        which by default updates ``bot_state``.
        """
        self._stop_event, self._threads = threading.Event(), []
        self._end_time = end_time
        self._record = record or partial(
            PerformanceTester._record_bot_event, bot_state, end_time
        )
        _fit_redis_pool_to_bots(n_bots)
        self._load = _LoadMonitor()

    def start_slot(self):
        """Start one bot slot in a new thread."""
        thread = threading.Thread(
            target=self._tester._run_bot_slot,
            args=(self._stop_event, self._end_time, self._record),
            name=f"{self._thread_prefix}{len(self._threads) + 1}",
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def end_test(self, timeout_s):
        """Stop the test's bots, as :meth:`_BotProcesses.end_test` does, for this process."""
        load = (None, None) if self._load is None else self._load.stop()
        self._load = None
        self._stop_event.set()
        return [load], [], _join_threads(self._threads, timeout_s)

    def failure(self):
        """Return ``None``: threads can't stop the way a process can."""
        return None

    def close(self, timeout_s=_BOT_PROCESS_EXIT_JOIN_S):
        """Stop any bots still running, waiting up to ``timeout_s`` for them."""
        self._stop_event.set()
        _join_threads(self._threads, timeout_s)


def _serve_bot_commands(bots, index, commands, events):
    """Run ``bots`` in a bot process as the parent asks, until it says to exit.

    See :class:`_BotProcesses` for the commands and events.
    """
    test_id = 0
    while True:
        command, *args = commands.get()
        if command == "test":
            test_id, end_time, n_slots = args
            record = partial(_put_bot_event, events, test_id)
            bots.begin_test(None, end_time, n_slots, record=record)
        elif command == "slot":
            bots.start_slot()
        elif command == "stop":
            (load,), _, n_alive = bots.end_test(*args)
            events.put((test_id, "finished", index, load, n_alive))
        elif command == "exit":
            bots.close()
            return


def _put_bot_event(events, test_id, kind, *args):
    """Send a bot's progress report from a bot process to the parent."""
    events.put((test_id, kind, *args))


_REPLY_KINDS = frozenset({"ready", "failed", "finished"})


class _BotProcesses:
    """Run bot slots in spawned child processes, each using :class:`_ThreadBots`.

    The parent keeps all the bookkeeping. It sends each child commands on the
    child's own queue: ``("test", test_id, end_time, n_slots)`` before a test,
    ``("slot",)`` to start one bot slot, ``("stop", timeout_s)`` to stop the
    test's bots and ``("exit",)`` to stop them and exit. Children send
    messages on one shared queue, each tagged with the test it belongs to
    (0 before the first test): ``(test_id, kind, *args)`` for each bot's
    progress, which a thread here applies to the test's ``bot_state`` with
    :meth:`PerformanceTester._record_bot_event` just as a bot thread in the
    parent would, and ``(test_id, kind, index, *payload)`` replies:
    ``"ready"``, ``"failed"`` with a traceback, and ``"finished"`` with the
    child's load (see :class:`_LoadMonitor`) and how many of its bots were
    still running. Messages from an earlier test are dropped, so bots that
    outlive their test can't affect the next one.

    Children are spawned, not forked: database engines, Redis pools and
    threads don't survive a fork. They ignore Ctrl-C and leave stopping to
    the parent, and as daemon processes they end with it.
    """

    def __init__(self, n_processes, *, stagger_interval_s, time_factor, bot_log_path):
        context = multiprocessing.get_context("spawn")
        self._events = context.Queue()
        self._replies = queue.Queue()
        self._commands = [context.Queue() for _ in range(n_processes)]
        settings = {
            "stagger_interval_s": stagger_interval_s,
            "time_factor": time_factor,
            "log_level": logger.getEffectiveLevel(),
            "bot_log_path": bot_log_path,
        }
        self._processes = [
            context.Process(
                target=_run_bot_process,
                args=(index, commands, self._events, settings),
                name=f"psynet-bot-process-{index + 1}",
                daemon=True,
            )
            for index, commands in enumerate(self._commands)
        ]
        # (test_id, bot_state, end_time), replaced as a whole so that the
        # event thread always reads a consistent test.
        self._test = (0, None, None)
        self._n_slots_started = 0
        self._event_thread = threading.Thread(
            target=self._apply_events, name="psynet-bot-events", daemon=True
        )
        self._event_thread.start()
        try:
            for process in self._processes:
                process.start()
            ready = self._collect_replies("ready", _BOT_PROCESS_START_TIMEOUT_S)
            if len(ready) < n_processes:
                raise RuntimeError(
                    self.failure()
                    or f"Bot processes did not start within "
                    f"{_BOT_PROCESS_START_TIMEOUT_S} s."
                )
        except BaseException:
            self.close()
            raise

    def _apply_events(self):
        """Apply the current test's bot events and pass its replies on, until closed."""
        while True:
            event = self._events.get()
            if event is None:
                return
            test_id, kind, *args = event
            current_id, bot_state, end_time = self._test
            if test_id != current_id:
                continue
            if kind in _REPLY_KINDS:
                self._replies.put(event)
                continue
            try:
                PerformanceTester._record_bot_event(bot_state, end_time, kind, *args)
            except Exception:
                logger.exception("Could not record bot event %r.", event)

    def _collect_replies(self, kind, timeout_s):
        """Wait up to ``timeout_s`` for a ``kind`` reply from each live child.

        Returns
        -------
        dict
            The payload of each reply, by child index.
        """
        replies = {}
        deadline = time.monotonic() + timeout_s
        while len(replies) < len(self._processes):
            waiting = [
                index
                for index, process in enumerate(self._processes)
                if index not in replies and process.is_alive()
            ]
            remaining = deadline - time.monotonic()
            done_waiting = not waiting or remaining <= 0
            try:
                # Still read replies that a child sent just before it exited.
                test_id, reply_kind, index, *payload = self._replies.get(
                    timeout=0.5 if done_waiting else min(1.0, remaining)
                )
            except queue.Empty:
                if done_waiting:
                    break
                continue
            if test_id != self._test[0]:
                continue
            if reply_kind == "failed":
                raise RuntimeError(
                    f"Bot process {index + 1} could not start:\n{payload[0]}"
                )
            if reply_kind == kind:
                replies[index] = payload
        return replies

    def begin_test(self, bot_state, end_time, n_bots):
        """Tell the children that a test of ``n_bots`` bots, ending at ``end_time``, starts."""
        test_id = self._test[0] + 1
        self._test = (test_id, bot_state, end_time)
        while not self._replies.empty():
            self._replies.get_nowait()
        self._n_slots_started = 0
        n_slots = math.ceil(n_bots / len(self._processes))
        for commands in self._commands:
            commands.put(("test", test_id, end_time, n_slots))

    def start_slot(self):
        """Start one bot slot, in each child in turn."""
        index = self._n_slots_started % len(self._commands)
        self._commands[index].put(("slot",))
        self._n_slots_started += 1

    def end_test(self, timeout_s):
        """Stop the test's bots, waiting up to ``timeout_s`` for them.

        Returns
        -------
        tuple of (list of tuple, list of int, int)
            The load of each child that reported, as returned by
            :meth:`_LoadMonitor.stop`; the numbers of those that didn't; and
            how many bots were still running when the children stopped
            waiting for them.
        """
        for commands in self._commands:
            commands.put(("stop", timeout_s))
        replies = self._collect_replies(
            "finished", timeout_s + _BOT_PROCESS_REPLY_GRACE_S
        )
        unreported = [i + 1 for i in range(len(self._processes)) if i not in replies]
        process_loads = [load for load, _ in replies.values()]
        n_alive = sum(n for _, n in replies.values())
        return process_loads, unreported, n_alive

    def failure(self):
        """Describe the first child that has stopped, or return ``None``."""
        for index, process in enumerate(self._processes):
            if process.exitcode is not None:
                return (
                    f"bot process {index + 1} stopped unexpectedly "
                    f"(exit code {process.exitcode})"
                )
        return None

    def close(self, timeout_s=10):
        """Ask the children to exit, terminating any that don't within ``timeout_s``."""
        started = [process for process in self._processes if process.pid is not None]
        for commands, process in zip(self._commands, self._processes):
            if process.is_alive():
                commands.put(("exit",))
        deadline = time.monotonic() + timeout_s
        for process in started:
            process.join(max(0.0, deadline - time.monotonic()))
        stragglers = [process for process in started if process.is_alive()]
        if stragglers:
            logger.warning(
                f"Terminating {len(stragglers)} bot process(es) that did not "
                f"exit within {timeout_s} s."
            )
            for process in stragglers:
                process.terminate()
                process.join(5)
        self._events.put(None)
        self._event_thread.join(5)


def _run_bot_process(index, commands, events, settings):
    """Run bot slots in a child process started by :class:`_BotProcesses`."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    level = settings["log_level"]
    # Bot output goes to the bot log; the parent reports on the test.
    log_to_console(level, level if level <= logging.DEBUG else logging.WARNING)
    try:
        # Loads the dashboard credentials as performance-test local does.
        from psynet.command_line import _load_runtime_server_config
        from psynet.experiment import get_experiment

        _load_runtime_server_config()
        get_experiment()
        raise_open_file_limit()
        tester = PerformanceTester(
            authenticated_session=None,
            base_url=None,
            stagger_interval_s=settings["stagger_interval_s"],
            time_factor=settings["time_factor"],
        )
        bots = _ThreadBots(tester, f"{_BOT_THREAD_PREFIX}{index + 1}.")
    except BaseException:
        events.put((0, "failed", index, traceback.format_exc()))
        return
    events.put((0, "ready", index))
    log_path = settings["bot_log_path"]
    # Appending lets every bot process share the parent's bot log.
    bot_log = open(log_path, "a") if log_path else None
    try:
        with _bot_logs_to(bot_log):
            _serve_bot_commands(bots, index, commands, events)
    finally:
        if bot_log is not None:
            bot_log.close()


def colorize_success_rate(rate_str):
    if rate_str == "N/A":
        return rate_str
    pct = float(rate_str.rstrip("%"))
    if pct >= 100:
        return success(rate_str)
    elif pct > 0:
        return warning(rate_str)
    else:
        return error(rate_str)


def _fmt(value, suffix=""):
    return f"{value:.3f}{suffix}" if value is not None else "N/A"


def _describe_workers(result):
    """Describe the async worker processes and how many jobs they can run at once."""
    n_workers = result.get("n_rq_workers")
    if not n_workers:
        return ""
    text = f"{n_workers} worker process{'es' if n_workers != 1 else ''}"
    n_slots = result.get("n_rq_job_slots")
    if n_slots and n_slots != n_workers:
        text += f", up to {n_slots} jobs at once"
    return text


_POSTGRES_FULL = "PostgreSQL out of connections"


def _describe_bot_error(err):
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
            return _POSTGRES_FULL
        response = getattr(cause, "response", None)
        if isinstance(cause, requests.HTTPError) and response is not None:
            route = urlparse(response.url or "").path.strip("/").split("/")[0]
            return f"HTTP {response.status_code} on /{route}"
        cause = cause.__cause__ or cause.__context__
    return type(err).__name__


def _plural(count, noun):
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _describe_bot_errors(result, limit=3):
    """Describe a result's bot errors, naming the most common causes."""
    text = _plural(result["bot_errors"], "bot error")
    kinds = list((result.get("bot_error_kinds") or {}).items())
    if not kinds:
        return text
    if len(kinds) == 1:
        return f"{text} ({kinds[0][0]})"
    named = ", ".join(f"{count:,} {kind}" for kind, count in kinds[:limit])
    if len(kinds) > limit:
        named += ", ..."
    return f"{text} ({named})"


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


def _quantile(sorted_values, q):
    """Return the value at quantile ``q`` of ``sorted_values``, or ``None`` if empty."""
    if not sorted_values:
        return None
    return sorted_values[min(int(len(sorted_values) * q), len(sorted_values) - 1)]


def format_test_results(result):
    """Format detailed results after a single test completes. Returns list[str]."""
    lines = []

    def _table_lines(rows, headers, indent="  ", min_label_width=28, **kwargs):
        kwargs.setdefault("tablefmt", "plain")
        if min_label_width and rows and not headers:
            rows = [[r[0].ljust(min_label_width)] + r[1:] for r in rows]
        table = tabulate(rows, headers=headers, **kwargs)
        for line in table.splitlines():
            lines.append(f"{indent}{line}")

    def _section(title):
        lines.append(bold(f"  {title}"))
        lines.append(f"  {'-' * 36}")

    bots_finished = max(
        result["completed_during_test"],
        result["bots_succeeded"] + result["bots_failed"],
    )

    total_started = result["total_bots_started"]
    if total_started > 0:
        completion_rate = f"{(bots_finished / total_started) * 100:.0f}%"
    else:
        completion_rate = "N/A"

    lines.append("")
    lines.append(success("\u2713 Test completed"))
    lines.append(bold(f"TEST RESULTS (n={result['n_bots']:,} bots)"))
    lines.append("")

    # BOT OUTCOMES
    _section("BOT OUTCOMES")
    bots_in_db = (
        result["bots_succeeded"] + result["bots_failed"] + result["bots_incomplete"]
    )
    bots_not_in_db = result["total_bots_started"] - bots_in_db
    outcome_rows = [
        ["Bots started", result["total_bots_started"]],
        ["Completed successfully", result["bots_succeeded"]],
        ["Completed with error", result["bots_failed"]],
        ["Timed out (still running)", result["bots_incomplete"]],
    ]
    if bots_not_in_db > 0:
        outcome_rows.append(["Never reached DB", bots_not_in_db])
    outcome_rows.append(["Completion rate", colorize_success_rate(completion_rate)])
    _table_lines(outcome_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    error_kinds = result.get("bot_error_kinds")
    if error_kinds:
        _section("BOT ERRORS")
        _table_lines(
            [[kind, count] for kind, count in error_kinds.items()],
            headers=[],
            colalign=("left", "right"),
        )
        lines.append("")

    # BOT RUNTIMES
    _section("BOT RUNTIMES")
    runtime_rows = []
    if result.get("actual_duration") is not None:
        runtime_rows.append(["Test duration", f"{result['actual_duration']:.1f}s"])
    if result.get("avg_bot_duration") is not None:
        runtime_rows.append(["Avg runtime", f"{result['avg_bot_duration']:.1f}s"])
    if result.get("avg_succeeded_duration") is not None:
        runtime_rows.append(
            [
                "Avg runtime (succeeded)",
                f"{result['avg_succeeded_duration']:.1f}s",
            ]
        )
    if result.get("avg_failed_duration") is not None:
        runtime_rows.append(
            [
                "Avg runtime (failed)",
                f"{result['avg_failed_duration']:.1f}s",
            ]
        )
    if result.get("avg_incomplete_duration") is not None:
        runtime_rows.append(
            [
                "Avg runtime (timed out)",
                f"{result['avg_incomplete_duration']:.1f}s",
            ]
        )
    if result.get("tester_lag_p95_s") is not None:
        lag = f"{result['tester_lag_p95_s'] * 1000:.0f} ms"
        runtime_rows.append(
            [
                "Bot lag (p95, worst process)",
                warning(lag) if _tester_lagged(result) else lag,
            ]
        )
    if result.get("tester_cpu_share") is not None:
        runtime_rows.append(
            ["Bot process CPU (busiest)", f"{result['tester_cpu_share']:.0%} of a core"]
        )
    if runtime_rows:
        _table_lines(runtime_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    # Bot initialization time distribution (sub-section)
    init_times = result.get("initialization_times", [])
    if init_times:
        init_sorted = sorted(init_times)
        init_median = _quantile(init_sorted, 0.5)
        init_p95 = _quantile(init_sorted, 0.95)
        init_max = init_sorted[-1]
        n_init = len(init_sorted)
        lines.append(bold(f"  BOT INIT TIMES (n={n_init}):"))
        lines.append(f"  {'-' * 36}")
        init_rows = [
            ["Median", _fmt(init_median, "s")],
            ["95th percentile", _fmt(init_p95, "s")],
            ["Max", _fmt(init_max, "s")],
        ]
        _table_lines(
            init_rows,
            headers=[],
            colalign=("left", "right"),
        )
        lines.append("")

    # REQUEST METRICS
    _section("REQUEST METRICS")
    request_rows = [
        ["Total requests", result["total_requests"]],
        # Requests that fail before the server can log them appear only
        # under BOT ERRORS.
        ["Request errors (logged)", result["request_errors"]],
    ]
    if result.get("busy_responses"):
        request_rows.append(
            ["Busy/stale responses (409/503)", result["busy_responses"]]
        )
    if result.get("requests_per_sec") is not None:
        request_rows.append(["Throughput", f"{result['requests_per_sec']:.2f} req/s"])
    _table_lines(request_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    # RESPONSE TIMES
    n_req = result.get("key_requests", "?")
    _section(f"RESPONSE TIMES (n={n_req} /timeline and /response requests)")
    resp_rows = [
        ["Median", _fmt(result["median_response_time"], "s")],
        ["95th percentile", _fmt(result["p95_response_time"], "s")],
        ["99th percentile", _fmt(result["p99_response_time"], "s")],
        ["Max", _fmt(result["max_response_time"], "s")],
        ["Mean", _fmt(result["avg_response_time"], "s")],
        ["Std dev", _fmt(result["stddev_response_time"], "s")],
    ]
    _table_lines(resp_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    # WAIT PAGE TIMES
    if result.get("median_wait_page_time") is not None:
        n_wait = result.get("n_wait_page_samples", "?")
        page_word = "page" if n_wait == 1 else "pages"
        _section(f"WAIT PAGE TIMES (n={n_wait} {page_word})")
        wait_rows = [
            ["Median", f"{result['median_wait_page_time']:.1f}s"],
            ["95th percentile", f"{result['p95_wait_page_time']:.1f}s"],
            ["Max", f"{result['max_wait_page_time']:.1f}s"],
        ]
        _table_lines(wait_rows, headers=[], colalign=("left", "right"))
        lines.append("")

    # TRIALS PER BOT
    n_succeeded = result.get("n_succeeded_bots", 0)
    bot_word = "bot" if n_succeeded == 1 else "bots"
    _section(f"TRIALS PER BOT (n={n_succeeded} {bot_word} succeeded)")
    _tc = lambda k, fallback=0: (  # noqa: E731
        result[k] if result.get(k) is not None else fallback
    )
    trial_rows = [
        ["Min", _tc("min_trial_count")],
        ["Median", _tc("median_trial_count")],
        ["Max", _tc("max_trial_count")],
    ]
    _table_lines(trial_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    # ASYNC PROCESS TIMES
    if result.get("process_stats"):
        n_procs = sum(ps["count"] for ps in result["process_stats"])
        worker_info = _describe_workers(result)
        worker_info = f", {worker_info}" if worker_info else ""
        _section(f"ASYNC PROCESS TIMES ({n_procs} completed{worker_info})")
        lines.append("  Avg/Med/P95/Max — statistics on actual execution time")
        lines.append(
            "  Q Avg/Q Med/Q P95 — statistics on queue delay (time waiting in RQ queue)"
        )
        lines.append(
            "  Q Share — avg of per-process queue_delay / (queue_delay + exec_time),"
        )
        lines.append(
            "    i.e. avg percentage of total time spent queuing rather than executing"
        )
        lines.append(
            "  Colors: yellow = Q Share > 20% and Q P95 > 0.2s (moderate contention)"
        )
        lines.append(
            "          red = Q Share > 20% and Q P95 > 0.5s (significant contention)"
        )
        lines.append("\n")

        def _color_q_share(q_share, q_p95):
            if q_share is None or q_p95 is None:
                return "N/A"
            text = f"{q_share:.0%}"
            if q_share > 0.2 and q_p95 > 0.5:
                return error(text)
            if q_share > 0.2 and q_p95 > 0.2:
                return warning(text)
            return text

        proc_rows = [
            [
                ps["trial_maker_id"],
                ps["label"],
                ps["count"],
                _fmt(ps["avg"]),
                _fmt(ps["median"]),
                _fmt(ps["p95"]),
                _fmt(ps["max"]),
                _fmt(ps["q_avg"]),
                _fmt(ps["q_median"]),
                _fmt(ps["q_p95"]),
                _color_q_share(ps["q_share"], ps["q_p95"]),
            ]
            for ps in result["process_stats"]
        ]
        _table_lines(
            proc_rows,
            headers=[
                "Trial Maker",
                "Label",
                "Count",
                "Avg (s)",
                "Med (s)",
                "P95 (s)",
                "Max (s)",
                "Q Avg (s)",
                "Q Med (s)",
                "Q P95 (s)",
                "Q Share",
            ],
            indent="    ",
            tablefmt="simple",
            colalign=(
                "left",
                "left",
                "right",
                "right",
                "right",
                "right",
                "right",
                "right",
                "right",
                "right",
            ),
        )
        lines.append("")
    else:
        worker_info = _describe_workers(result)
        worker_info = f" ({worker_info})" if worker_info else ""
        _section(f"ASYNC PROCESS TIMES{worker_info}")
        lines.append("  No completed async processes.")
        lines.append("")

    if result.get("oldest_queued_s") is not None:
        lines.append(
            warning(
                "  Still queued when the test ended: oldest process had waited "
                f"{result['oldest_queued_s']:.1f}s for a worker."
            )
        )
        lines.append("")

    return lines


def _ratio(value, baseline, is_baseline):
    """Format ``value / baseline`` for the summary's "vs base" columns."""
    if is_baseline:
        return "\u2014"
    if value is None or not baseline or baseline <= 0:
        return "N/A"
    return f"{value / baseline:.1f}x"


def format_performance_summary(results):
    """Format cross-test comparison table. Returns list[str]."""
    lines = []
    results = sorted(results, key=lambda r: r["n_bots"])

    show_scaling = (
        len(results) > 1 and results[0].get("median_response_time") is not None
    )
    baseline_response_median = (
        results[0].get("median_response_time") if show_scaling else None
    )
    baseline_q_median = results[0].get("q_delay_median") if show_scaling else None

    summary_headers = [
        "Bots",
        "Succeeded",
        "Requests",
        "Req/s",
        "Resp P95 (s)",
        "Resp Med (s)",
    ]
    if show_scaling:
        summary_headers.append("Resp Med vs base")
    summary_headers.append("Q Med all (s)")
    if show_scaling:
        summary_headers.append("Q Med vs base")
    summary_headers.append("Q P95 (s)")

    summary_rows = []
    for i, result in enumerate(results):
        response_median = result.get("median_response_time")
        q_median = result.get("q_delay_median")
        row = [
            result["n_bots"],
            result["bots_succeeded"],
            result["total_requests"],
            (
                f"{result['requests_per_sec']:.1f}"
                if result.get("requests_per_sec") is not None
                else "N/A"
            ),
            _fmt(result.get("p95_response_time")),
            _fmt(response_median),
        ]
        if show_scaling:
            row.append(_ratio(response_median, baseline_response_median, i == 0))
        row.append(_fmt(q_median))
        if show_scaling:
            row.append(_ratio(q_median, baseline_q_median, i == 0))
        row.append(_fmt(queue_wait_p95(result)))
        summary_rows.append(row)

    lines.append("")
    lines.append(bold("CUMULATIVE PERFORMANCE TEST SUMMARY\n"))
    lines.append(
        "  Resp P95 / Resp Med — 95th percentile / median HTTP response time for key "
        "endpoints (/timeline, /response)"
    )
    lines.append("  Q Med all — median queue delay across all async processes")
    lines.append(
        "  Q P95 — 95th percentile queue delay, or the wait of the oldest process "
        "still queued at the end if longer"
    )
    if show_scaling:
        lines.append("  vs base — ratio of the median to the lowest bot count's")
    lines.append("")
    table = tabulate(summary_rows, headers=summary_headers, tablefmt="simple")
    for line in table.splitlines():
        lines.append(f"  {line}")
    lines.append("")

    return lines


def server_is_reachable(url, session=None):
    """Return whether a server accepts connections at ``url``."""
    import requests

    try:
        (session or requests).head(url, timeout=10)
    except requests.Timeout:
        # Includes ConnectTimeout: a full connection backlog under load
        # still means the server is up.
        return True
    except requests.ConnectionError:
        return False
    return True


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
    """

    max_p95_s: float = DEFAULT_MAX_P95_S
    max_queue_p95_s: float = DEFAULT_MAX_QUEUE_P95_S
    max_request_error_rate: float = 0.001
    allowed_request_errors: int = 1
    max_busy_response_rate: float = 0.01
    allowed_busy_responses: int = 10
    max_bot_error_rate: float = 0.01

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
            f"({self.allowed_busy_responses} always allowed) and "
            f"{self.max_bot_error_rate:.0%} of bots failing"
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
        float(v)
        for v in (result.get("q_delay_p95"), result.get("oldest_queued_s"))
        if v is not None
    ]
    return max(waits) if waits else None


# Bots between runs, or still being created, leave a few slots briefly empty.
_MIN_RUNNING_SHARE = 0.9
_MAX_TESTER_LAG_P95_S = 0.05


def _tester_lagged(result):
    """Return whether bots ran so late that they could not keep pace; see :func:`_tester_limits`."""
    lag = result.get("tester_lag_p95_s")
    return lag is not None and lag > _MAX_TESTER_LAG_P95_S


def _start_rate_limits(result):
    """Return the reasons bots did not all start, or take part at once, in a test."""
    reasons = []
    slots_started = result.get("slots_started")
    if slots_started is not None and slots_started < result.get("n_bots", 0):
        reasons.append(
            f"only {slots_started:,} of {result['n_bots']:,} bots started "
            "(use a longer --duration-minutes)"
        )
    peak_running = result.get("peak_running")
    if peak_running is not None and peak_running < _MIN_RUNNING_SHARE * result.get(
        "n_bots", 0
    ):
        reasons.append(
            f"at most {peak_running:,} of {result['n_bots']:,} bots were taking "
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
    :class:`_LoadMonitor`). That is how long bots queue for the interpreter
    lock and the CPU before each step, so above ``_MAX_TESTER_LAG_P95_S``
    they make requests noticeably more slowly than participants would and
    the server gets less load than the bot count suggests.
    """
    reasons = _start_rate_limits(result)
    if result.get("bot_process_failure"):
        reasons.append(result["bot_process_failure"])
    unreported = result.get("unreported_bot_processes")
    if unreported:
        reasons.append(
            f"bot process(es) {', '.join(map(str, unreported))} did not report "
            "after the test, so how late their bots ran is unknown"
        )
    if _tester_lagged(result):
        where = (
            "the test process"
            if result.get("bot_processes", 1) == 1
            else "the busiest bot process"
        )
        reasons.append(
            f"bots in {where} were running "
            f"{result['tester_lag_p95_s'] * 1000:.0f} ms late (p95), so they could "
            "not keep pace (use more --bot-processes)"
        )
    return reasons


def _capacity_failure_causes(result, limits):
    """Return ``(reason, server_limit)`` for each limit that ``result`` exceeded.

    ``server_limit`` is False when the reason only shows that the test could
    not measure the server at this bot count: bots didn't all start or take
    part at once, bots in a busy process ran too late to keep pace
    (so the server got less load than that many participants would give),
    bots failed because PostgreSQL ran out of connections (the
    bots open their own database connections in this process, which
    participants don't), or no responses were recorded while bots were
    missing.
    """
    causes = [("server stopped", True)] if result.get("server_stopped") else []
    tester_limits = _tester_limits(result)
    causes += [(reason, False) for reason in tester_limits]
    key_requests = result.get("key_requests") or 0
    request_errors = result.get("request_errors") or 0
    if request_errors > max(
        limits.allowed_request_errors,
        limits.max_request_error_rate * key_requests,
    ):
        causes.append((_plural(request_errors, "request error"), True))
    busy_responses = result.get("busy_responses") or 0
    if busy_responses > max(
        limits.allowed_busy_responses,
        limits.max_busy_response_rate * key_requests,
    ):
        causes.append((_plural(busy_responses, "busy/stale response"), True))
    bot_errors = result.get("bot_errors") or 0
    max_bot_errors = limits.max_bot_error_rate * (result.get("total_bots_started") or 0)
    if bot_errors > max_bot_errors:
        postgres_errors = (result.get("bot_error_kinds") or {}).get(_POSTGRES_FULL, 0)
        causes.append(
            (
                _describe_bot_errors(result),
                bot_errors - postgres_errors > max_bot_errors,
            )
        )
    p95 = result.get("p95_response_time")
    if p95 is None:
        causes.append(("no responses recorded", not tester_limits))
    elif float(p95) > limits.max_p95_s:
        causes.append((f"p95 response time {float(p95) * 1000:.0f} ms", True))
    else:
        for endpoint, endpoint_p95 in sorted(
            (result.get("endpoint_p95") or {}).items()
        ):
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
    return [reason for reason, _ in _capacity_failure_causes(result, limits)]


def next_capacity_probe(highest_pass, lowest_fail, max_bots=_CAPACITY_SEARCH_MAX):
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
            return _CAPACITY_SEARCH_START
        if highest_pass >= max_bots:
            return None
        return min(highest_pass * 2, max_bots)
    lower = highest_pass or 0
    if lowest_fail - lower <= max(1, lower * _CAPACITY_RESOLUTION):
        return None
    return (lower + lowest_fail) // 2


def _max_capacity_probes(max_bots=_CAPACITY_SEARCH_MAX):
    """Return the most tests the capacity search can run, over all capacities."""

    def n_probes(capacity):
        highest_pass = lowest_fail = None
        n = 0
        while (
            probe := next_capacity_probe(highest_pass, lowest_fail, max_bots)
        ) is not None:
            n += 1
            if probe <= capacity:
                highest_pass = probe
            else:
                lowest_fail = probe
        return n

    return max(n_probes(capacity) for capacity in range(max_bots + 1))


_POSTGRES_ADVICE = (
    "  Some bots failed because PostgreSQL ran out of connections. The bots "
    "open their own database connections in this test process, which "
    "participants don't, so this limits the test rather than the experiment. "
    "Run fewer bots at once, stop other experiments that share the database "
    "server, or raise max_connections."
)
_QUEUE_ADVICE = (
    "  Async processes waited too long for a worker: add worker processes "
    "with num_dynos_worker, or make the processes faster."
)
_START_RATE_ADVICE = (
    "  Bots that cannot start fast enough limit the test rather than the "
    "server, because this process creates each bot's "
    "participant itself. Bots that take longer, in a longer experiment or "
    "with a larger --time-factor, give a better measure of the server."
)
_TESTER_LAG_ADVICE = (
    "  A process running bots was so busy that its bots ran late and made "
    "requests more slowly than participants would, so the server got less "
    "load than the bot count suggests. Spread the bots over more processes "
    "with --bot-processes, or run the test from a computer with more CPU cores."
)


def format_capacity_summary(results, limits=CapacityLimits(), time_factor=1.0):
    """Describe the capacity that ``results`` imply and suggest a participant cap.

    Returns list[str].
    """
    if not results:
        return []
    limit = limits.describe(
        include_queue=any(
            queue_wait_p95(r) is not None or r.get("q_delay_median") is not None
            for r in results
        )
    )
    causes = [(r, _capacity_failure_causes(r, limits)) for r in results]
    passed = [r["n_bots"] for r, result_causes in causes if not result_causes]
    failed = [(r, result_causes) for r, result_causes in causes if result_causes]
    first_fail, first_causes = (
        min(failed, key=lambda f: f[0]["n_bots"]) if failed else (None, [])
    )
    first_reasons = "; ".join(reason for reason, _ in first_causes)
    unmeasured = not any(server_limit for _, server_limit in first_causes)
    below_fail = [n for n in passed if first_fail is None or n < first_fail["n_bots"]]
    capacity = max(below_fail, default=None)
    if capacity is None:
        if unmeasured:
            lines = [
                f"  Capacity unknown: {first_fail['n_bots']:,} bots could not "
                f"be tested ({first_reasons})."
            ]
        else:
            lines = [
                f"  Even {first_fail['n_bots']:,} bots did not keep {limit} "
                f"({first_reasons}); fix any errors or test fewer bots."
            ]
        if passed:
            lines.append(
                f"  {max(passed):,} bots passed, so the results are "
                "inconsistent; rerun to confirm."
            )
    elif first_fail is None:
        lines = [
            f"  Capacity: at least {capacity:,} concurrent bots kept {limit}. "
            "Test more bots to find the limit."
        ]
    elif unmeasured:
        lines = [
            f"  Capacity: at least {capacity:,} concurrent bots kept {limit}; "
            f"{first_fail['n_bots']:,} could not be tested ({first_reasons}).",
        ]
    else:
        lines = [
            f"  Capacity: about {capacity:,} concurrent bots kept {limit}; "
            f"{first_fail['n_bots']:,} did not ({first_reasons}).",
            f"  Cap concurrent participants at about "
            f"{max(1, int(capacity * _CAPACITY_HEADROOM)):,} "
            f"({_CAPACITY_HEADROOM:.0%} of {capacity:,}).",
        ]
        if max(passed) > first_fail["n_bots"]:
            lines.append(
                f"  {max(passed):,} bots also passed, so the results are "
                "inconsistent; rerun to confirm."
            )
    if "async queue" in first_reasons:
        lines.append(_QUEUE_ADVICE)
    if first_fail is not None and _start_rate_limits(first_fail):
        lines.append(_START_RATE_ADVICE)
    if first_fail is not None and _tester_lagged(first_fail):
        lines.append(_TESTER_LAG_ADVICE)
    if any(_POSTGRES_FULL in (r.get("bot_error_kinds") or {}) for r in results):
        lines.append(_POSTGRES_ADVICE)
    if capacity is None:
        return lines + [""]
    capacity_result = next(r for r in results if r["n_bots"] == capacity)
    tolerated = []
    if capacity_result.get("request_errors"):
        tolerated.append(_plural(capacity_result["request_errors"], "request error"))
    if capacity_result.get("busy_responses"):
        tolerated.append(
            _plural(capacity_result["busy_responses"], "busy/stale response")
        )
    if capacity_result.get("bot_errors"):
        tolerated.append(_describe_bot_errors(capacity_result))
    if tolerated:
        found = " and ".join(filter(None, [", ".join(tolerated[:-1]), tolerated[-1]]))
        lines.append(
            f"  The {capacity:,}-bot test had {found}, within "
            "the limits; check the logs in case they point to a bug."
        )
    ramp_up = capacity_result.get("ramp_up_s")
    test_length = capacity_result.get("actual_duration")
    if ramp_up and test_length and ramp_up > _RAMP_UP_WARNING_SHARE * test_length:
        lines.append(
            f"  Starting all {capacity:,} bots took {ramp_up:.0f} s of the "
            f"{test_length:.0f} s test, so the server ran fully loaded for only "
            f"{1 - ramp_up / test_length:.0%} of it; use a longer "
            "--duration-minutes to confirm the capacity."
        )
    if not time_factor:
        lines.append(
            "  These bots ran without pauses (--time-factor 0) and load the server "
            "far more than people do; use --time-factor 1 to size a participant cap."
        )
    lines.append("")
    return lines


def capacity_advice(capacity_search=False):
    """Return advice on getting participant numbers that apply to a deployment.

    The audit shows it beside the results. ``performance.json`` doesn't record
    where the test ran, so the advice always includes the local caveat.

    Parameters
    ----------
    capacity_search : bool
        Whether the test already searched for capacity with ``--n-bots auto``.

    Returns
    -------
    list[str]
    """
    advice = [
        "Local results only show how the experiment copes on this computer. "
        "For numbers that apply to your study, launch the experiment on its "
        "deployment server (psynet debug ssh) and run psynet performance-test "
        "ssh there; the server's CPU, memory and worker settings set the real "
        "capacity.",
        "Bots fetch pages and submit answers without a browser, so the results "
        "leave out the static files, media and JavaScript requests that "
        "participants' browsers make.",
    ]
    if not capacity_search:
        advice.append(
            "To find the largest number of concurrent participants the server "
            "handles, add --n-bots auto."
        )
    return advice

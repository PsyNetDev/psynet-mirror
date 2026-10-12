"""Run single performance tests: drive bots against a server and collect a result.

:class:`PerformanceTester` runs one test. It runs bots as threads (each a
:class:`~psynet.bot.BotDriver` making real HTTP requests), keeps a fixed
number of them taking the experiment at once, then reads the test's
measurements with :mod:`psynet.perf_test.measure` into a
:class:`~psynet.perf_test.results.PerformanceTestResult`.

One Python process can only run so many bot threads: they share its
interpreter lock, and at a few hundred requests per second the process runs
out of CPU and every bot slows down, so the server gets less load than the bot
count suggests. Large tests therefore spread their bot threads over several
child processes (:class:`_BotProcesses`). The children only run bots; they
report each bot's progress to this process, which keeps all the bookkeeping
and reads all the results, exactly as with bot threads of its own. Bots share
their process, so experiment code they run must not rely on per-process state.

The children are spawned, so they start by importing :func:`_run_bot_process`
from this module by name: keep it a module-level function here.

This module also pre-fills the database with bot data
(:func:`prefill_database`), raises the process limits that many bots need, and
keeps bot output off the console (:func:`log_to_console`).
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
from dataclasses import dataclass, field
from functools import partial

from psynet.log import bold, warning
from psynet.perf_test.measure import (
    async_process_stats,
    bot_duration_stats,
    bot_outcome_stats,
    count_rq_workers,
    database_rows,
    request_stats,
    wait_for_async_processes,
)
from psynet.perf_test.report import (
    format_test_results,
)
from psynet.perf_test.results import (
    PerformanceTestResult,
    describe_bot_error,
    plural,
    quantile,
)

logger = logging.getLogger(__name__)

_SERVER_CHECK_INTERVAL_S = 5
_BACKLOG_DRAIN_TIMEOUT_S = 120
_BOT_THREAD_PREFIX = "psynet-bot-"
_PREFILL_BOTS = 50
_OPEN_FILE_TARGET = 65536
_MACOS_OPEN_FILE_MAX = 10240
_BOT_PROCESS_START_TIMEOUT_S = 300
# How much longer than the bots' stop timeout to wait for bot processes to reply.
_BOT_PROCESS_REPLY_GRACE_S = 10
_LAG_PROBE_INTERVAL_S = 0.05
_BOT_PROCESS_EXIT_JOIN_S = 5
# Return to the start of the terminal line and erase it, however wide its
# characters were.
_ERASE_LINE = "\r\033[K"


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


@dataclass(kw_only=True)
class _BotState:
    """What the bots of one test have done so far, for the live status and results.

    Bot threads and the thread applying bot process events update it under
    ``lock``; the monitoring loop and :meth:`PerformanceTester._stop_bots`
    set the rest.
    """

    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Bot ID -> time the bot was created, for bots taking the experiment.
    running: dict = field(default_factory=dict)
    total_bots_started: int = 0
    bots_completed_during_test: int = 0
    # Bots that finished during the test after the experiment failed them.
    bots_failed_during_test: int = 0
    total_bot_errors: int = 0
    errored_bot_ids: set = field(default_factory=set)
    # Short description of each failure, e.g. "HTTP 500 on /response".
    bot_error_kinds: Counter = field(default_factory=Counter)
    # (bot_id, duration_s, stopped_by_test_end) of each finished bot.
    bot_durations: list = field(default_factory=list)
    initialization_times: list = field(default_factory=list)
    first_bot_initialized: bool = False
    server_stopped: bool = False
    slots_started: int = 0
    # Most bots that were taking part at the same moment.
    peak_running: int = 0
    # Seconds from the test start until the last bot slot started.
    ramp_up_s: float | None = None
    # (CPU share, p95 lag in s) of each process running bots.
    process_loads: list = field(default_factory=list)
    # Why a bot process stopped during the test, if one did.
    bot_process_failure: str | None = None
    # Numbers of bot processes that didn't report their load.
    unreported_bot_processes: list = field(default_factory=list)
    last_status_update: float = field(default_factory=time.time)


def prefill_database(n_participants, bot_log_file=None):
    """Add ``n_participants`` participants' data by running bots through the experiment.

    Up to 50 bots run at once, as threads, without pauses (time factor 0),
    until ``n_participants`` bots have taken the experiment. The bots go
    through the same routes as participants, so the data is what the
    experiment itself stores.

    Raises
    ------
    RuntimeError
        If any bot raised, because the data would then differ from what
        participants leave. Participants that the experiment fails, for
        example at a prescreen, are only reported.
    """
    import itertools

    from dallinger import db

    from psynet.bot import BotDriver
    from psynet.experiment import get_experiment

    n_bots = min(_PREFILL_BOTS, n_participants)
    logger.info("")
    logger.info(
        bold(f"PRE-FILL: {n_participants:,} participants, {n_bots:,} bots at once")
    )
    experiment = get_experiment()
    _fit_redis_pool_to_bots(n_bots)
    raise_open_file_limit()
    taken = itertools.count()
    done = Counter()
    lock = threading.Lock()

    def run_bots():
        while next(taken) < n_participants:
            outcome = "finished"
            try:
                experiment.run_bot(BotDriver(), time_factor=0)
            except BaseException as err:
                logger.exception("Bot failed.")
                outcome = describe_bot_error(err)
            finally:
                db.session.remove()
            with lock:
                done[outcome] += 1

    threads = [
        threading.Thread(
            target=run_bots, name=f"{_BOT_THREAD_PREFIX}prefill-{i + 1}", daemon=True
        )
        for i in range(n_bots)
    ]
    with _bot_logs_to(bot_log_file):
        for thread in threads:
            thread.start()
        while _join_threads(threads, timeout_s=30):
            logger.info(f"Pre-fill: {done.total():,} of {n_participants:,} bots done")
    errors = done.total() - done["finished"]
    if errors:
        del done["finished"]
        kinds = ", ".join(f"{n:,} {kind}" for kind, n in done.most_common())
        raise RuntimeError(
            f"{plural(errors, 'pre-fill bot')} raised errors ({kinds}), so the "
            "pre-filled data is not what participants would leave; see the bot "
            "log. No snapshot was taken."
        )
    from psynet.participant import Participant

    n_failed = Participant.query.filter(Participant.failed.is_(True)).count()
    db.session.rollback()
    logger.info(
        f"Pre-fill: {done.total():,} bots done; the experiment failed "
        f"{plural(n_failed, 'participant')}."
    )


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
        lag_p95_ms = quantile(sorted(self._lags_ms.elements()), 0.95)
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


# At realistic pacing a process runs about this many bots on well under a core.
_BOTS_PER_PROCESS = 250


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


class PerformanceTester:
    """Run single performance tests against a server; see :class:`~psynet.perf_test.suite.PerformanceSuite`."""

    def __init__(
        self,
        authenticated_session,
        base_url,
        duration_minutes=1,
        stagger_interval_s=0.1,
        time_factor=0.0,
        bot_processes=1,
        estimated_duration_minutes=None,
    ):
        """Set up a performance tester.

        Parameters
        ----------
        bot_processes : int or "auto"
            Number of processes to run the bots in. With 1 they run as threads
            in this process; ``"auto"`` chooses from the most bots a suite
            runs and the CPU count (see :func:`_choose_bot_processes`).
        estimated_duration_minutes : float, optional
            The experiment's estimated duration
            (``Experiment.estimated_duration_in_minutes``), for the suite header.
        """
        self.authenticated_session = authenticated_session
        self.base_url = base_url
        self.duration_minutes = duration_minutes
        self.stagger_interval_s = stagger_interval_s
        self.time_factor = time_factor
        self.bot_processes = bot_processes
        self.estimated_duration_minutes = estimated_duration_minutes
        self._n_bot_processes = 1
        # Runs the bots: _ThreadBots, or _BotProcesses during a suite that
        # needs several processes.
        self._bots = _ThreadBots(self)
        # Experiment code shares this process and may call random.seed().
        self._random = random.Random()

    @property
    def session_minutes(self):
        """Return about how long a bot takes the experiment, or ``None`` if unknown."""
        if self.estimated_duration_minutes is None:
            return None
        return self.estimated_duration_minutes * self.time_factor

    @contextmanager
    def bot_runner(self, max_bots, bot_log_file):
        """Start the bot processes a suite of up to ``max_bots`` bots needs, if any.

        They last for the whole suite, because each one imports the
        experiment, which can take seconds and much memory.
        """
        raise_open_file_limit()
        self._suite_started_at = datetime.datetime.now()
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

    def pause_between_tests(self):
        """Pause, then let async processes queued by earlier tests start.

        Otherwise they would hold up the next test's processes and count
        against its queue wait.
        """
        time.sleep(5)
        queued = wait_for_async_processes(
            since=self._suite_started_at, timeout_s=_BACKLOG_DRAIN_TIMEOUT_S
        )
        if queued:
            logger.warning(
                warning(
                    f"{queued:,} async processes from earlier tests are still "
                    "queued, so they may slow the next test's processes."
                )
            )

    def release_database_connections(self):
        """Close the bots' pooled database connections, for example before a reset."""
        self._bots.release_database_connections()

    def run_test(self, label, n_bots, bot_log_file):
        """Run one test of ``n_bots`` bots, print its results and return them."""
        logger.info("")
        logger.info(bold("=" * 80))
        logger.info(bold(f"TEST {label}: Running with {n_bots:,} concurrent bots"))
        return self._test_performance(n_bots, bot_log_file=bot_log_file)

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
        bot_state = _BotState()
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

        db_rows = database_rows()
        # Don't hold locks on the growing tables, which would block
        # autovacuum, for the whole test.
        db.session.rollback()
        return {
            "max_request_id": max_request_id,
            "max_process_id": max_process_id,
            "max_participant_id": max_participant_id,
            "db_rows": db_rows,
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
        from psynet.participant import DriverStopped, Participant

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
                failed = (
                    db.session.query(Participant.failed).filter_by(id=bot_id).scalar()
                )
                outcome = "failed" if failed else "completed"
            except DriverStopped:
                outcome = "stopped"
            except BaseException as err:
                logger.exception("Bot %s failed.", bot_id)
                outcome = "error"
                error_kind = describe_bot_error(err)
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
        ``outcome`` is ``"completed"``, ``"failed"`` (finished, but the
        experiment failed the participant), ``"stopped"`` or ``"error"``.
        """
        if kind == "attempt":
            with bot_state.lock:
                bot_state.total_bots_started += 1
        elif kind == "start":
            cls._record_bot_start(bot_state, *args)
        else:
            bot_id, outcome, error_kind = args
            cls._record_bot_end(bot_state, bot_id, outcome, end_time, error_kind)

    @staticmethod
    def _record_bot_start(bot_state, bot_id, init_time):
        """Record that a bot started, for the live status and results."""
        now = time.time()
        with bot_state.lock:
            bot_state.initialization_times.append(init_time)
            bot_state.first_bot_initialized = True
            bot_state.running[bot_id] = now
            bot_state.peak_running = max(bot_state.peak_running, len(bot_state.running))

    @staticmethod
    def _record_bot_end(bot_state, bot_id, outcome, end_time, error_kind=None):
        """Record how and when a bot finished."""
        now = time.time()
        with bot_state.lock:
            start = bot_state.running.pop(bot_id, None)
            if outcome == "error":
                bot_state.total_bot_errors += 1
                bot_state.bot_error_kinds[error_kind] += 1
                if bot_id is not None:
                    bot_state.errored_bot_ids.add(bot_id)
            elif outcome == "completed" and now < end_time:
                bot_state.bots_completed_during_test += 1
            elif outcome == "failed" and now < end_time:
                bot_state.bots_failed_during_test += 1
            if start is not None:
                bot_state.bot_durations.append(
                    (bot_id, now - start, outcome == "stopped")
                )

    def _stop_bots(self, bot_state, timeout_s=30):
        """Stop the bots that are still running and wait for their threads."""
        process_loads, unreported, n_alive = self._bots.end_test(timeout_s)
        bot_state.process_loads += process_loads
        bot_state.unreported_bot_processes = unreported
        if unreported:
            logger.warning(
                f"Bot process(es) {', '.join(map(str, unreported))} did not report "
                "after the test, so the suite stops here."
            )
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
        if not force and current_time - bot_state.last_status_update < interval:
            return

        bot_state.last_status_update = current_time

        # Calculate stats
        running = len(bot_state.running)
        completed = bot_state.bots_completed_during_test
        errors = bot_state.total_bot_errors

        # Calculate average response time from recent bot durations
        recent_durations = [d for _, d, _ in bot_state.bot_durations[-5:]]
        avg_duration = (
            sum(recent_durations) / len(recent_durations) if recent_durations else 0
        )

        # Time remaining
        time_left = max(0, end_time - current_time)
        mins_left = int(time_left / 60)
        secs_left = int(time_left % 60)

        # Build status line
        failed = bot_state.bots_failed_during_test
        status = f"\U0001f916 Running: {running} | \u2713 Completed: {completed:,} | \u2717 Failed by experiment: {failed:,} | \u2717 Errors: {errors} | \u23f1 Avg: {avg_duration:.1f}s | \u23f3 {mins_left}:{secs_left:02d} left"

        if not interactive:
            print(status, flush=True)
            return

        sys.stdout.write(_ERASE_LINE + status)
        sys.stdout.flush()

    def _clear_realtime_status(self):
        """Clear the status line when progress is complete."""
        is_debug = logger.getEffectiveLevel() <= logging.DEBUG
        if not is_debug and sys.stdout.isatty():
            sys.stdout.write(_ERASE_LINE)
            sys.stdout.flush()

    def _run_monitoring_loop(self, n, bot_state, start_bot_slot, start_time, end_time):
        """Start ``n`` staggered bot slots and watch the server until the test ends."""
        # The first bot waits for the experiment launch; the rest follow it.
        start_bot_slot()
        n_started = bot_state.slots_started = 1
        if n_started >= n:
            bot_state.ramp_up_s = 0.0
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
                    bot_state.server_stopped = True
                    return
                failure = self._bots.failure()
                if failure:
                    self._clear_realtime_status()
                    logger.warning(warning(f"The test ends early: {failure}."))
                    bot_state.bot_process_failure = failure
                    return

            if n_started < n and bot_state.first_bot_initialized:
                if next_slot_time is None:
                    next_slot_time = current_time
                while n_started < n and current_time >= next_slot_time:
                    start_bot_slot()
                    n_started = bot_state.slots_started = n_started + 1
                    next_slot_time += self._bounded_random_stagger()
                if n_started >= n:
                    bot_state.ramp_up_s = time.time() - start_time

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

        request_summary = request_stats(
            initial_state["max_request_id"], last_request_id
        )
        process_stats = async_process_stats(initial_state["max_process_id"], ended_at)
        outcomes, bot_stats = bot_outcome_stats(
            initial_state["max_participant_id"], bot_state.errored_bot_ids
        )
        total_requests = request_summary["total_requests"]
        init_times = sorted(bot_state.initialization_times)
        result = PerformanceTestResult(
            n_bots=n,
            duration_minutes=duration_minutes,
            actual_duration=actual_duration,
            server_stopped=bot_state.server_stopped,
            bot_process_failure=bot_state.bot_process_failure,
            unreported_bot_processes=bot_state.unreported_bot_processes,
            bot_processes=self._n_bot_processes,
            slots_started=bot_state.slots_started,
            peak_running=bot_state.peak_running,
            ramp_up_s=bot_state.ramp_up_s,
            tester_cpu_share=_worst(bot_state.process_loads, 0),
            tester_lag_p95_s=_worst(bot_state.process_loads, 1),
            total_bots_started=bot_state.total_bots_started,
            db_rows_before=initial_state["db_rows"],
            db_rows_after=database_rows(),
            requests_per_sec=(
                total_requests / actual_duration if actual_duration > 0 else None
            ),
            bot_errors=bot_state.total_bot_errors,
            bot_error_kinds=dict(bot_state.bot_error_kinds.most_common()),
            median_init_time=quantile(init_times, 0.5),
            p95_init_time=quantile(init_times, 0.95),
            max_init_time=quantile(init_times, 1),
            n_init_samples=len(init_times),
            **request_summary,
            **process_stats,
            **bot_stats,
            **bot_duration_stats(bot_state.bot_durations, outcomes),
        )
        result.n_rq_workers, result.n_rq_job_slots = count_rq_workers()
        # Release the locks the counts took before the next test starts.
        db.session.rollback()
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

    @staticmethod
    def release_database_connections():
        """Close this process's pooled database connections."""
        from psynet.db import release_local_database_connections

        release_local_database_connections()

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
        if command == "release":
            bots.release_database_connections()
            events.put((test_id, "released", index))
        elif command == "test":
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


_REPLY_KINDS = frozenset({"ready", "failed", "finished", "released"})


class _BotProcesses:
    """Run bot slots in spawned child processes, each using :class:`_ThreadBots`.

    The parent keeps all the bookkeeping. It sends each child commands on the
    child's own queue: ``("test", test_id, end_time, n_slots)`` before a test,
    ``("slot",)`` to start one bot slot, ``("stop", timeout_s)`` to stop the
    test's bots, ``("release",)`` to close its database connections before a
    database reset, and ``("exit",)`` to stop them and exit. Children send
    messages on one shared queue, each tagged with the test it belongs to
    (0 before the first test): ``(test_id, kind, *args)`` for each bot's
    progress, which a thread here applies to the test's ``bot_state`` with
    :meth:`PerformanceTester._record_bot_event` just as a bot thread in the
    parent would, and ``(test_id, kind, index, *payload)`` replies:
    ``"ready"``, ``"released"``, ``"failed"`` with a traceback, and
    ``"finished"`` with the child's load (see :class:`_LoadMonitor`) and how
    many of its bots were still running. Messages from an earlier test are dropped, so bots that
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
            target=self._apply_events, name="psynet-perf-events", daemon=True
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

    def release_database_connections(self, timeout_s=30):
        """Have the children close their pooled database connections, and wait for them."""
        for commands in self._commands:
            commands.put(("release",))
        replies = self._collect_replies("released", timeout_s)
        silent = [i + 1 for i in range(len(self._processes)) if i not in replies]
        if silent:
            logger.warning(
                warning(
                    f"Bot processes {silent} did not confirm within {timeout_s} s "
                    "that they closed their database connections; the reset "
                    "terminates any that remain."
                )
            )

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
        from psynet.experiment import get_experiment
        from psynet.utils import load_runtime_server_config

        load_runtime_server_config()
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

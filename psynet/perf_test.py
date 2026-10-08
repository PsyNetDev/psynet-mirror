import datetime
import logging
import random
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal

from tabulate import tabulate

from psynet.log import bold, error, success, warning

logger = logging.getLogger(__name__)

_SERVER_CHECK_INTERVAL_S = 5
_BOT_THREAD_PREFIX = "psynet-bot-"

DEFAULT_MAX_P95_S = 0.5
DEFAULT_MAX_QUEUE_P95_S = 5.0
_CAPACITY_SEARCH_START = 10
_CAPACITY_SEARCH_MAX = 2000
# The search stops once the gap between the largest passing and smallest
# failing bot counts is within this fraction of the passing count.
_CAPACITY_RESOLUTION = 0.1
_CAPACITY_HEADROOM = 0.8


def _is_bot_thread_record(record):
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


def _hide_bot_thread_records(record):
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


# ---------------------------------------------------------------------------
# PerformanceTester (moved from Experiment perf methods)
# ---------------------------------------------------------------------------


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
    ):
        self.authenticated_session = authenticated_session
        self.base_url = base_url
        self.n_bots = n_bots
        self.duration_minutes = duration_minutes
        self.stagger_interval_s = stagger_interval_s
        self.time_factor = time_factor
        self.limits = limits or CapacityLimits()
        # Experiment code shares this process and may call random.seed().
        self._random = random.Random()

    def run(self, bot_counts=None, bot_log_file=None):
        """Run performance tests for one or more bot count values."""
        if bot_counts is None:
            bot_counts = [self.n_bots]

        self._print_suite_header(", ".join(str(n) for n in bot_counts))
        all_results = []
        for i, n_bots in enumerate(bot_counts, 1):
            if i > 1:
                time.sleep(5)
            result = self._run_one_test(f"{i}/{len(bot_counts)}", n_bots, bot_log_file)
            all_results.append(result)
            if result["server_stopped"]:
                break

        self._print_performance_summary(all_results)
        return all_results

    def find_capacity(self, bot_log_file=None):
        """Search for the largest bot count the server handles within limits.

        Doubles the bot count from 10 until a test fails
        :func:`within_capacity`, then bisects between the largest passing and
        smallest failing counts until they are within 10% of each other.

        Returns
        -------
        list[dict]
            One result per test, in the order they ran.
        """
        self._print_suite_header(
            f"automatic (from {_CAPACITY_SEARCH_START}, while keeping "
            f"{self.limits.describe()})"
        )
        all_results = []
        highest_pass = lowest_fail = None
        while True:
            n_bots = next_capacity_probe(highest_pass, lowest_fail)
            if n_bots is None:
                break
            if all_results:
                time.sleep(5)
            result = self._run_one_test(f"{len(all_results) + 1}", n_bots, bot_log_file)
            all_results.append(result)
            if result["server_stopped"]:
                break
            failures = capacity_failures(result, self.limits)
            if failures:
                logger.info(
                    warning(f"{n_bots:,} bots exceeded limits: {', '.join(failures)}")
                )
                lowest_fail = n_bots
            else:
                highest_pass = n_bots

        self._print_performance_summary(all_results)
        return all_results

    def _print_suite_header(self, bots_description):
        logger.info(bold("=" * 80))
        logger.info(bold("\u26a1 PERFORMANCE TEST SUITE"))
        logger.info(f"Bots per test:        {bots_description}")
        logger.info(f"Test duration:        {self.duration_minutes:.1f} min")
        logger.info(f"Bot start stagger:    ~{self.stagger_interval_s:.1f}s")
        logger.info(f"Bot time factor:      {self.time_factor:.1f}")

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
        start_bot_slot = self._create_bot_launcher(bot_state, end_time)

        with _bot_logs_to(bot_log_file):
            try:
                self._run_monitoring_loop(
                    n, bot_state, start_bot_slot, start_time, end_time
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
            "stop_event": threading.Event(),
            "threads": [],
            # Bot ID -> time the bot was created, for bots taking the experiment.
            "running": {},
            "total_bots_started": 0,
            "bots_completed_during_test": 0,
            "total_bot_errors": 0,
            "bot_durations": [],
            "initialization_times": [],
            "first_bot_initialized": False,
            "server_stopped": False,
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

    def _create_bot_launcher(self, bot_state, end_time):
        """Return a function that starts one bot slot in a new thread."""

        def start_bot_slot():
            thread = threading.Thread(
                target=self._run_bot_slot,
                args=(bot_state, end_time),
                name=f"{_BOT_THREAD_PREFIX}{len(bot_state['threads']) + 1}",
                daemon=True,
            )
            bot_state["threads"].append(thread)
            thread.start()

        return start_bot_slot

    def _run_bot_slot(self, bot_state, end_time):
        """Run bots one after another until the test ends.

        Each slot stands for one participant at a time, so ``n`` slots keep
        ``n`` participants active. Bots share this process: threads cost far
        less memory and start-up CPU than a process per bot, and the bots
        spend most of their time waiting on the server.
        """
        from dallinger import db

        from psynet.bot import BotDriver
        from psynet.experiment import get_experiment
        from psynet.participant import DriverStopped

        experiment = get_experiment()
        stop_event = bot_state["stop_event"]
        while not stop_event.is_set() and time.time() < end_time:
            create_time = time.time()
            bot_id = None
            try:
                bot = BotDriver()
                bot.stop_event = stop_event
                bot_id = bot.id
                self._record_bot_start(bot_state, bot_id, create_time)
                if stop_event.is_set():
                    raise DriverStopped()
                experiment.run_bot(
                    bot,
                    time_factor=self.time_factor * self._bounded_random_multiplier(),
                )
                outcome = "completed"
            except DriverStopped:
                outcome = "stopped"
            except BaseException:
                logger.exception("Bot %s failed.", bot_id)
                outcome = "error"
            finally:
                db.session.remove()
            self._record_bot_end(bot_state, bot_id, outcome, end_time)
            stop_event.wait(self._bounded_random_stagger())

    @staticmethod
    def _record_bot_start(bot_state, bot_id, create_time):
        now = time.time()
        with bot_state["lock"]:
            bot_state["total_bots_started"] += 1
            bot_state["initialization_times"].append(now - create_time)
            bot_state["first_bot_initialized"] = True
            bot_state["running"][bot_id] = now

    @staticmethod
    def _record_bot_end(bot_state, bot_id, outcome, end_time):
        now = time.time()
        with bot_state["lock"]:
            start = bot_state["running"].pop(bot_id, None)
            if outcome == "error":
                bot_state["total_bot_errors"] += 1
            elif outcome == "completed" and now < end_time:
                bot_state["bots_completed_during_test"] += 1
            if start is not None:
                bot_state["bot_durations"].append(
                    (bot_id, now - start, outcome == "stopped")
                )

    def _stop_bots(self, bot_state, timeout_s=30):
        """Stop the bots that are still running and wait for their threads."""
        bot_state["stop_event"].set()
        deadline = time.time() + timeout_s
        for thread in bot_state["threads"]:
            thread.join(max(0.0, deadline - time.time()))
        n_alive = sum(thread.is_alive() for thread in bot_state["threads"])
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

        # Update every 2 seconds, or immediately if forced
        if not force and current_time - bot_state["last_status_update"] < 2:
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

        # Clear previous line and print new status
        sys.stdout.write("\r" + " " * bot_state["status_line_length"] + "\r")
        sys.stdout.write(status)
        sys.stdout.flush()
        bot_state["status_line_length"] = len(status)

    def _clear_realtime_status(self):
        """Clear the status line when progress is complete."""
        is_debug = logger.getEffectiveLevel() <= logging.DEBUG
        if not is_debug:
            sys.stdout.write("\r" + " " * 150 + "\r")
            sys.stdout.flush()

    def _server_is_reachable(self):
        """Return whether the experiment server still accepts connections."""
        import requests

        try:
            self.authenticated_session.head(self.base_url, timeout=10)
        except requests.Timeout:
            # Includes ConnectTimeout: a full connection backlog under load
            # still means the server is up.
            return True
        except requests.ConnectionError:
            return False
        return True

    def _run_monitoring_loop(self, n, bot_state, start_bot_slot, start_time, end_time):
        """Start ``n`` staggered bot slots and watch the server until the test ends."""
        # The first bot waits for the experiment launch; the rest follow it.
        start_bot_slot()
        n_started = 1
        next_slot_time = None
        next_server_check = start_time
        while time.time() < end_time:
            current_time = time.time()

            if current_time >= next_server_check:
                next_server_check = current_time + _SERVER_CHECK_INTERVAL_S
                if not self._server_is_reachable():
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

            if n_started < n and bot_state["first_bot_initialized"]:
                if next_slot_time is None:
                    next_slot_time = current_time
                while n_started < n and current_time >= next_slot_time:
                    start_bot_slot()
                    n_started += 1
                    next_slot_time += self._bounded_random_stagger()

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

        request_errors = (
            db.session.query(func.count(Request.id))
            .filter(
                *request_window,
                Request.endpoint.in_(key_endpoints),
                Request.status_code >= 400,
            )
            .scalar()
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
            .filter(
                AsyncProcess.id > initial_state["max_process_id"],
                AsyncProcess.finished == True,  # noqa: E712
            )
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

        q_delay_median = (
            db.session.query(
                func.percentile_cont(0.5).within_group(AsyncProcess.queue_delay)
            )
            .filter(
                AsyncProcess.id > initial_state["max_process_id"],
                AsyncProcess.finished == True,  # noqa: E712
            )
            .scalar()
        )

        q_delay_p95 = (
            db.session.query(
                func.percentile_cont(0.95).within_group(AsyncProcess.queue_delay)
            )
            .filter(
                AsyncProcess.id > initial_state["max_process_id"],
                AsyncProcess.finished == True,  # noqa: E712
            )
            .scalar()
        )

        oldest_enqueued = (
            db.session.query(func.min(AsyncProcess.time_enqueued))
            .filter(
                AsyncProcess.id > initial_state["max_process_id"],
                AsyncProcess.time_enqueued <= ended_at,
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
        bots_succeeded = bots_failed = bots_incomplete = 0
        for bot in bots:
            if bot.status in {"approved", "submitted"}:
                bots_succeeded += 1
            elif bot.status == "working":
                bots_incomplete += 1
            else:
                bots_failed += 1

        succeeded_statuses = {"approved", "submitted"}
        succeeded_bots = [b for b in bots if b.status in succeeded_statuses]
        wait_page_times = [
            b.total_wait_page_time
            for b in succeeded_bots
            if b.total_wait_page_time is not None
        ]
        if wait_page_times:
            wait_page_times_sorted = sorted(wait_page_times)
            median_wait_page_time = wait_page_times_sorted[
                len(wait_page_times_sorted) // 2
            ]
            p95_wait_page_time = wait_page_times_sorted[
                int(len(wait_page_times_sorted) * 0.95)
            ]
            max_wait_page_time = wait_page_times_sorted[-1]
        else:
            median_wait_page_time = p95_wait_page_time = max_wait_page_time = None

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
            return counts[0], counts[len(counts) // 2], counts[-1]

        succeeded_bot_ids = [b.id for b in bots if b.status in succeeded_statuses]
        (
            min_trial_count,
            median_trial_count,
            max_trial_count,
        ) = _trial_count_stats(succeeded_bot_ids)
        bot_status_map = {b.id: b.status for b in bots}
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

        avg_bot_duration = (
            sum(all_durations) / len(all_durations) if all_durations else None
        )
        avg_succeeded_duration = (
            sum(succeeded_durations) / len(succeeded_durations)
            if succeeded_durations
            else None
        )
        avg_failed_duration = (
            sum(failed_durations) / len(failed_durations) if failed_durations else None
        )
        avg_incomplete_duration = (
            sum(incomplete_durations) / len(incomplete_durations)
            if incomplete_durations
            else None
        )

        avg_init_time = (
            sum(bot_state["initialization_times"])
            / len(bot_state["initialization_times"])
            if bot_state["initialization_times"]
            else None
        )

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
            "total_bots_started": bot_state["total_bots_started"],
            "completed_during_test": bot_state["bots_completed_during_test"],
            "bots_succeeded": bots_succeeded,
            "bots_failed": bots_failed,
            "bots_incomplete": bots_incomplete,
            "total_requests": requests_during_test,
            "requests_per_sec": requests_per_sec,
            "bot_errors": bot_state["total_bot_errors"],
            "avg_response_time": avg_response_time,
            "median_response_time": median_response_time,
            "p95_response_time": p95_response_time,
            "p99_response_time": p99_response_time,
            "stddev_response_time": stddev_response_time,
            "max_response_time": max_response_time,
            "avg_bot_duration": avg_bot_duration,
            "avg_init_time": avg_init_time,
            "initialization_times": initialization_times,
            "request_errors": request_errors,
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

            result["n_rq_workers"] = len(Worker.all(connection=redis_conn))
        except Exception:
            pass

        self._report_test_results(result)
        return result

    def _report_test_results(self, result):
        """Print detailed results after a single test completes."""
        for line in format_test_results(result):
            logger.info(line)


# ---------------------------------------------------------------------------
# Formatting helpers (already existed in this file)
# ---------------------------------------------------------------------------


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
    if runtime_rows:
        _table_lines(runtime_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    # Bot initialization time distribution (sub-section)
    init_times = result.get("initialization_times", [])
    if init_times:
        init_sorted = sorted(init_times)
        init_median = init_sorted[len(init_sorted) // 2]
        init_p95 = init_sorted[int(len(init_sorted) * 0.95)]
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
        ["Request errors", result["request_errors"]],
    ]
    if result.get("requests_per_sec") is not None:
        request_rows.append(["Throughput", f"{result['requests_per_sec']:.2f} req/s"])
    _table_lines(request_rows, headers=[], colalign=("left", "right"))
    lines.append("")

    # RESPONSE TIMES
    n_req = result.get("total_requests", "?")
    _section(f"RESPONSE TIMES (n={n_req})")
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
        n_workers = result.get("n_rq_workers")
        worker_info = f" via {n_workers} workers" if n_workers else ""
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
        n_workers = result.get("n_rq_workers")
        worker_info = f", {n_workers} workers" if n_workers else ""
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


def format_performance_summary(results):
    """Format cross-test comparison table. Returns list[str]."""
    lines = []

    show_scaling = (
        len(results) > 1 and results[0].get("median_response_time") is not None
    )
    baseline_response_median = (
        results[0].get("median_response_time") if show_scaling else None
    )
    baseline_q_median = results[0].get("q_delay_median") if show_scaling else None

    summary_headers = [
        "|| Bots",
        "Succeeded",
        "Requests",
        "Req/s",
        "Resp P95 (s)",
        "Resp Med (s)",
    ]
    if show_scaling:
        summary_headers.append("vs base")
    summary_headers.append("Q Med all (s)")
    if show_scaling:
        summary_headers.append("vs base")
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
            if i == 0:
                row.append("\u2014")
            elif (
                response_median is not None
                and baseline_response_median
                and baseline_response_median > 0
            ):
                row.append(f"{response_median / baseline_response_median:.1f}x")
            else:
                row.append("N/A")
        row.append(_fmt(q_median))
        if show_scaling:
            if i == 0:
                row.append("\u2014")
            elif q_median is not None and baseline_q_median and baseline_q_median > 0:
                row.append(f"{q_median / baseline_q_median:.1f}x")
            else:
                row.append("N/A")
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
    lines.append(
        "  vs base — ratio to the first (lowest bot-count) row, if multiple counts are run"
    )
    lines.append("")
    table = tabulate(summary_rows, headers=summary_headers, tablefmt="simple")
    for line in table.splitlines():
        lines.append(f"  {line}")
    lines.append("")

    return lines


@dataclass(frozen=True)
class CapacityLimits:
    """Thresholds a performance test must stay within to count as within capacity.

    Parameters
    ----------
    max_p95_s : float
        Largest acceptable 95th-percentile response time for ``/timeline``
        and ``/response``.
    max_queue_p95_s : float
        Largest acceptable time async processes spend waiting for a worker,
        measured by :func:`queue_wait_p95`.
    """

    max_p95_s: float = DEFAULT_MAX_P95_S
    max_queue_p95_s: float = DEFAULT_MAX_QUEUE_P95_S

    def describe(self):
        return (
            f"p95 response time under {self.max_p95_s * 1000:.0f} ms, "
            f"p95 async queue wait under {self.max_queue_p95_s:g} s and no errors"
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


def capacity_failures(result, limits=CapacityLimits()):
    """Return the reasons a test result exceeded ``limits`` (empty if it did not)."""
    reasons = []
    if result.get("server_stopped"):
        reasons.append("server stopped")
    if result.get("request_errors"):
        reasons.append(f"{result['request_errors']} request errors")
    if result.get("bot_errors"):
        reasons.append(f"{result['bot_errors']} bot errors")
    p95 = result.get("p95_response_time")
    if p95 is None:
        reasons.append("no responses recorded")
    elif float(p95) > limits.max_p95_s:
        reasons.append(f"p95 response time {float(p95) * 1000:.0f} ms")
    queue_wait = queue_wait_p95(result)
    if queue_wait is not None and queue_wait > limits.max_queue_p95_s:
        reasons.append(f"p95 async queue wait {queue_wait:.2f} s")
    return reasons


def within_capacity(result, limits=CapacityLimits()):
    """Return whether a test result stayed within ``limits``."""
    return not capacity_failures(result, limits)


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


def format_capacity_summary(results, limits=CapacityLimits(), time_factor=1.0):
    """Describe the capacity that ``results`` imply and suggest a participant cap.

    Returns list[str].
    """
    limit = limits.describe()
    passed = [r["n_bots"] for r in results if within_capacity(r, limits)]
    if not passed:
        return [f"  No tested bot count kept {limit}.", ""]

    capacity = max(passed)
    failed_above = [
        r for r in results if r["n_bots"] > capacity and not within_capacity(r, limits)
    ]
    if failed_above:
        first_fail = min(failed_above, key=lambda r: r["n_bots"])
        lines = [
            f"  Capacity: about {capacity:,} concurrent bots kept {limit}; "
            f"{first_fail['n_bots']:,} did not "
            f"({', '.join(capacity_failures(first_fail, limits))})."
        ]
    else:
        lines = [
            f"  Capacity: at least {capacity:,} concurrent bots kept {limit}. "
            "Test more bots to find the limit."
        ]
    suggested = int(capacity * _CAPACITY_HEADROOM)
    lines.append(
        f"  Suggested max_concurrent_participants: {suggested:,} "
        f"({_CAPACITY_HEADROOM:.0%} of {capacity:,})"
    )
    if not time_factor:
        lines.append(
            "  These bots ran without pauses (--time-factor 0) and load the server "
            "far more than people do; use --time-factor 1 to size a participant cap."
        )
    lines.append("")
    return lines

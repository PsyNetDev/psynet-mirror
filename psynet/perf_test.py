import datetime
import logging
import math
import os
import random
import re
import signal
import sys
import time
from decimal import Decimal
from statistics import mean

import pexpect
from sqlalchemy.exc import SQLAlchemyError
from tabulate import tabulate

from psynet.log import bold, error, success, warning

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# TestingStats / TestingStatDefinition (moved from Experiment inner classes)
# ---------------------------------------------------------------------------


class TestingStatDefinition:
    def __init__(self, key, label, regex, suffix, decimal_places=3):
        self.key = key
        self.label = label
        self.regex = regex
        self.suffix = suffix
        self.decimal_places = decimal_places

    def extract_stat(self, line):
        match = re.search(self.regex, line)
        if match:
            return float(match.group(1))

    def report(self, values):
        values_not_none = [value for value in values if value is not None]

        if len(values_not_none) > 0:
            _mean = mean(values_not_none)
            template = f"Mean %s = %.{self.decimal_places}f%s"
            logger.info(template % (self.label, _mean, self.suffix))
        else:
            logger.info(f"Didn't find any values for {self.label} to report.")


class TestingStats:
    def __init__(self, stat_definitions):
        self.stat_definitions = stat_definitions
        self.data = {stat_definition.key: {} for stat_definition in stat_definitions}

    def update_from_line(self, bot_id, line):
        for stat_definition in self.stat_definitions:
            stat = stat_definition.extract_stat(line)
            if stat is not None:
                self.update_from_stat(stat_definition.key, bot_id, stat)

    def update_from_stat(self, stat_key, bot_id, value):
        self.data[stat_key][bot_id] = value

    def report(self):
        logger.info("BOT TESTING STATISTICS:")
        for stat_definition in self.stat_definitions:
            values = self.data[stat_definition.key].values()
            stat_definition.report(values)


TESTING_STAT_DEFINITIONS = [
    TestingStatDefinition(
        "progress",
        label="progress through experiment",
        regex="progress = ([0-9]*)%",
        suffix="%",
        decimal_places=0,
    ),
    TestingStatDefinition(
        "total_wait_page_time",
        label="total wait page time per bot",
        regex="total WaitPage time = ([0-9]*\\.[0-9]*) seconds",
        suffix=" seconds",
        decimal_places=2,
    ),
    TestingStatDefinition(
        "total_experiment_time",
        label="time taken to complete experiment",
        regex="total experiment time = ([0-9]*\\.[0-9]*) seconds",
        suffix=" seconds",
    ),
]


# ---------------------------------------------------------------------------
# run_parallel_test (moved from Experiment._test_experiment_parallel)
# ---------------------------------------------------------------------------


def run_parallel_test(n_bots, time_factor, stagger_interval_s, check_bots):
    """Run n_bots in parallel subprocesses and report stats."""
    from psynet.utils import get_config

    from .bot import Bot

    logger.info(f"Testing experiment with {n_bots} parallel bots...")

    config = get_config()
    dashboard_user = config.get("dashboard_user")
    dashboard_password = config.get("dashboard_password")

    n_processes = n_bots

    processes = []
    process_ids = list(range(n_processes))
    bot_ids = [process_id + 1 for process_id in process_ids]

    cmd = f"psynet run-bot --dashboard-user {dashboard_user} --dashboard-password {dashboard_password}"
    cmd += f" --time-factor {time_factor}"

    for bot_id in bot_ids:
        if bot_id > 0:
            time.sleep(stagger_interval_s)

        logger.info(f"Creating and running bot {bot_id}...")
        p = pexpect.spawn(cmd, timeout=None, cwd=None)
        processes.append(p)

    waiting_for_processes = True
    finished_processes = set()

    testing_stats = TestingStats(TESTING_STAT_DEFINITIONS)

    while waiting_for_processes:
        for process, process_id, bot_id in zip(processes, process_ids, bot_ids):
            try:
                while True:
                    output = (
                        process.read_nonblocking(size=100000, timeout=0)
                        .decode()
                        .strip()
                        .split("\n")
                    )
                    for line in output:
                        line = line.replace("INFO:root:", "")
                        logger.info(f"(Bot {bot_id}) " + line)

                        testing_stats.update_from_line(bot_id, line)

                    time.sleep(0.01)
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                assert process.exitstatus == 0
                finished_processes.add(process_id)

        if len(finished_processes) == n_processes:
            waiting_for_processes = False

    bots = Bot.query.all()
    check_bots(bots)

    testing_stats.report()


# ---------------------------------------------------------------------------
# PerformanceTester (moved from Experiment perf methods)
# ---------------------------------------------------------------------------


class PerformanceTester:
    def __init__(
        self,
        authenticated_session,
        base_url,
        duration_minutes=1,
        stagger_interval_s=0.1,
        time_factor=0.0,
    ):
        self.authenticated_session = authenticated_session
        self.base_url = base_url
        self.duration_minutes = duration_minutes
        self.stagger_interval_s = stagger_interval_s
        self.time_factor = time_factor

    def run(self, bot_counts, bot_log_file=None):
        """Run performance tests for one or more bot count values.

        Returns a list of result dicts, one per bot count.
        """
        all_results = []

        logger.info(bold("=" * 80))
        logger.info(bold("\u26a1 PERFORMANCE TEST SUITE"))
        logger.info(f"Bots per test:        {', '.join(str(n) for n in bot_counts)}")
        logger.info(f"Test duration:        {self.duration_minutes:.1f} min")
        logger.info(f"Bot start stagger:    ~{self.stagger_interval_s:.1f}s")
        logger.info(f"Bot time factor:      {self.time_factor:.1f}")

        for i, n_bots in enumerate(bot_counts, 1):
            logger.info("")
            logger.info(bold("=" * 80))
            logger.info(
                bold(
                    f"TEST {i}/{len(bot_counts)}: Running with {n_bots:,} concurrent bots"
                )
            )

            result = self._test_performance(n_bots, bot_log_file=bot_log_file)
            all_results.append(result)

            if i < len(bot_counts):
                logger.debug("")
                logger.debug("Waiting 5 seconds before next test...")
                time.sleep(5)

        return all_results

    def _test_performance(self, n, bot_log_file):
        """Run a load test with n concurrent bots for configured duration."""
        duration_minutes = self.duration_minutes
        logger.info("")
        logger.info(
            "\u25b6 Starting load test with {n:,} concurrent bots for {duration_minutes} minutes...".format(
                n=n, duration_minutes=duration_minutes
            )
        )

        # Setup
        initial_state = self._capture_initial_state()
        bot_state = self._initialize_bot_tracking()
        bot_state["bot_log_file"] = bot_log_file
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        # Create bot launcher
        start_new_bot = self._create_bot_launcher(bot_state)

        # Launch first bot and wait for initialization
        logger.debug("Launching first bot and waiting for initialization...")
        start_new_bot()

        # Show initial status immediately
        self._show_realtime_status(bot_state, time.time(), end_time, force=True)

        # Main monitoring loop
        self._run_monitoring_loop(n, bot_state, start_new_bot, start_time, end_time)
        self._clear_realtime_status()

        # Calculate and report results
        actual_duration = time.time() - start_time
        return self._calculate_and_report_results(
            n, duration_minutes, actual_duration, initial_state, bot_state
        )

    def _capture_initial_state(self):
        """Capture initial database state before test."""
        from dallinger import db
        from sqlalchemy import func

        from psynet.experiment import Request
        from psynet.participant import Participant
        from psynet.process import AsyncProcess

        url = self.base_url + "/request_statistics"
        resp = self.authenticated_session.get(url)
        if resp.status_code != 200:
            raise RuntimeError(
                f"GET {url} returned status {resp.status_code}: {resp.text[:200]}"
            )
        try:
            initial_stats = resp.json()
        except Exception:
            raise RuntimeError(
                f"GET {url} returned non-JSON (status {resp.status_code}): "
                f"{resp.text[:200]}"
            )

        # Ensure fresh DB connection (previous may have been terminated by server restart)
        try:
            db.session.remove()
        except SQLAlchemyError:
            db.session.registry.clear()
        db.engine.dispose()

        max_request_id = db.session.query(func.max(Request.id)).scalar() or 0
        max_process_id = db.session.query(func.max(AsyncProcess.id)).scalar() or 0
        max_participant_id = db.session.query(func.max(Participant.id)).scalar() or 0

        return {
            "initial_requests": initial_stats["total_requests"],
            "max_request_id": max_request_id,
            "max_process_id": max_process_id,
            "max_participant_id": max_participant_id,
        }

    def _initialize_bot_tracking(self):
        """Initialize tracking structures for bots."""
        return {
            "processes": {},
            "next_bot_id": 1,
            "next_process_id": 0,
            "total_bots_started": 0,
            "total_bots_completed": 0,
            "bots_completed_during_test": 0,
            "total_bot_errors": 0,
            "bot_durations": [],
            "initialization_times": [],
            "bot_exit_failures": {},
            "bot_monitor_errors": {},
            "first_bot_initialized": False,
            "bots_to_launch": 0,
            "testing_stats": TestingStats(TESTING_STAT_DEFINITIONS),
            "last_status_update": time.time(),
            "status_line_length": 0,
            "bot_ids": set(),
            "bot_log_file": None,
        }

    @staticmethod
    def _bounded_random_multiplier(max_multiplier=3.0):
        """Bounded lognormal distribution for user completion times"""
        sigma = 0.6
        mu = -0.5 * sigma * sigma
        while True:
            x = math.exp(random.gauss(mu, sigma))
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
            x = random.gammavariate(k, theta)
            if x <= max_stagger:
                return x

    def _create_bot_launcher(self, bot_state):
        """Create a function to launch new bot processes."""
        from psynet.utils import get_config

        config = get_config()
        dashboard_user = config.get("dashboard_user")
        dashboard_password = config.get("dashboard_password")
        time_factor = self.time_factor

        def start_new_bot():
            bot_id = bot_state["next_bot_id"]
            process_id = bot_state["next_process_id"]
            bot_state["next_bot_id"] += 1
            bot_state["next_process_id"] += 1

            randomized_time_factor = time_factor * self._bounded_random_multiplier()
            cmd = (
                f"psynet run-bot --dashboard-user {dashboard_user} "
                f"--dashboard-password {dashboard_password} "
                f"--time-factor {randomized_time_factor}"
            )

            logger.debug(
                f"Starting bot {bot_id} (time_factor={randomized_time_factor:.2f})..."
            )

            try:
                env = os.environ.copy()
                # Disable colors in log output, so it can be read with any tool
                env["PYTHON_COLORS"] = "0"
                # Ensure venv bin dir is on PATH so psynet is found
                bin_dir = os.path.dirname(sys.executable)
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
                p = pexpect.spawn(cmd, timeout=None, cwd=None, env=env)
                bot_state["processes"][process_id] = {
                    "process": p,
                    "bot_id": bot_id,
                    "spawn_time": time.time(),
                    "start_time": None,
                    "next_start_time": None,
                    "recent_output": [],
                }
                if bot_state["bot_log_file"]:
                    p.logfile_read = bot_state["bot_log_file"]
                bot_state["total_bots_started"] += 1
                bot_state["bot_ids"].add(bot_id)

                return True
            except Exception as e:
                logger.error(f"Failed to start bot {bot_id}: {e}")
                return False

        return start_new_bot

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
        running = len(
            [p for p in bot_state["processes"].values() if p["next_start_time"] is None]
        )
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

    def _run_monitoring_loop(self, n, bot_state, start_new_bot, start_time, end_time):
        """Main loop to monitor bot processes."""
        while time.time() < end_time or len(bot_state["processes"]) > 0:
            current_time = time.time()

            # Show real-time status update
            self._show_realtime_status(bot_state, current_time, end_time)

            # Start new bots after bots have completed
            if self._start_scheduled_bots(
                bot_state, start_new_bot, current_time, end_time
            ):
                # Force status update after starting a bot
                self._show_realtime_status(
                    bot_state, current_time, end_time, force=True
                )

            # Launch n-1 bots after first one initializes
            if bot_state["first_bot_initialized"] and bot_state["bots_to_launch"] > 0:
                logger.debug(
                    f"First bot initialized. Launching remaining {bot_state['bots_to_launch']} bots..."
                )
                for i in range(bot_state["bots_to_launch"]):
                    if i > 0:
                        random_stagger = self._bounded_random_stagger()
                        logger.debug(
                            f"Waiting {random_stagger:.2f}s before launching next bot..."
                        )
                        time.sleep(random_stagger)
                    start_new_bot()
                    # Force status update after each bot
                    self._show_realtime_status(
                        bot_state, time.time(), end_time, force=True
                    )
                bot_state["bots_to_launch"] = 0

            self._monitor_all_processes(bot_state, current_time, end_time, n)

            # Terminate running bots once time is up to ensure consistent stats
            if current_time >= end_time and len(bot_state.get("processes", {})) > 0:
                logger.debug(
                    "End time reached \u2014 terminating remaining bot processes"
                )
                for proc_id, proc_info in list(bot_state.get("processes", {}).items()):
                    # Only target running processes
                    if proc_info.get("next_start_time") is not None:
                        continue
                    proc_info["terminated_by_test"] = True
                    p = proc_info.get("process")
                    if p is None:
                        continue
                    pidnum = getattr(p, "pid", None)
                    try:
                        if pidnum:
                            os.kill(pidnum, signal.SIGTERM)
                        else:
                            try:
                                p.kill(signal.SIGTERM)
                            except Exception:
                                try:
                                    p.close(force=True)
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.debug(f"Failed to terminate bot process {proc_id}: {e}")

                # Give processes a short grace period to exit
                time.sleep(0.2)

            time.sleep(0.1)

    def _start_scheduled_bots(self, bot_state, start_new_bot, current_time, end_time):
        """Start bots that are scheduled to start. Returns True if any bots were started."""
        to_start = [
            pid
            for pid, info in list(bot_state["processes"].items())
            if info["next_start_time"] is not None
            and current_time >= info["next_start_time"]
        ]

        for process_id in to_start:
            del bot_state["processes"][process_id]
            if current_time < end_time:
                start_new_bot()

        return len(to_start) > 0

    def _monitor_all_processes(self, bot_state, current_time, end_time, n):
        """Monitor all running bot processes."""
        for process_id, process_info in list(bot_state["processes"].items()):
            if process_info["next_start_time"] is not None:
                continue  # Wait to start

            self._monitor_single_process(
                bot_state, process_id, process_info, current_time, end_time, n
            )

    def _monitor_single_process(
        self, bot_state, process_id, process_info, current_time, end_time, n
    ):
        """Monitor a single bot process."""
        p = process_info["process"]
        bot_id = process_info["bot_id"]

        try:
            while True:
                output = (
                    p.read_nonblocking(size=100000, timeout=0)
                    .decode()
                    .strip()
                    .split("\n")
                )
                for line in output:
                    line = line.replace("INFO:root:", "")
                    logger.debug(f"(Bot {bot_id}) " + line)
                    bot_state["testing_stats"].update_from_line(bot_id, line)
                    recent = process_info["recent_output"]
                    recent.append(line)
                    # Keep just the most recent 10 lines. Remove overflow from
                    # the front of the list
                    recent[:] = recent[-10:]

                    # Detect bot initialization
                    if process_info["start_time"] is None and "Initializing" in line:
                        process_info["start_time"] = time.time()
                        init_time = (
                            process_info["start_time"] - process_info["spawn_time"]
                        )
                        logger.debug(f"Bot {bot_id} initialized in {init_time:.1f}s")

                        bot_state["initialization_times"].append(init_time)

                        if not bot_state["first_bot_initialized"]:
                            bot_state["first_bot_initialized"] = True
                            bot_state["bots_to_launch"] = n - 1

                time.sleep(0.01)

        except pexpect.TIMEOUT:
            pass
        except pexpect.EOF:
            self._handle_bot_completion(
                bot_state, process_info, process_id, current_time, end_time
            )
        except Exception as e:
            self._handle_bot_error(
                bot_state, process_info, process_id, e, current_time, end_time
            )

    def _handle_bot_completion(
        self, bot_state, process_info, process_id, current_time, end_time
    ):
        """Handle a bot process completion."""
        p = process_info["process"]
        bot_id = process_info["bot_id"]

        # Calculate duration
        if process_info["start_time"] is not None:
            bot_duration = current_time - process_info["start_time"]
        else:
            bot_duration = current_time - process_info["spawn_time"]

        # Record duration for all exits
        terminated = process_info.get("terminated_by_test", False)
        if process_info["start_time"] is not None:
            bot_state["bot_durations"].append((bot_id, bot_duration, terminated))

        if p.exitstatus == 0:
            logger.debug(f"Bot {bot_id} completed successfully in {bot_duration:.1f}s")
            if current_time < end_time:
                bot_state["bots_completed_during_test"] += 1
        else:
            if p.exitstatus is not None:
                bot_state["bot_exit_failures"][bot_id] = {
                    "exitstatus": p.exitstatus,
                    "output": process_info["recent_output"],
                }
                bot_state["total_bot_errors"] += 1

        # Schedule bot replacement or cleanup
        if current_time < end_time:
            random_delay = self._bounded_random_stagger()
            process_info["next_start_time"] = current_time + random_delay
            logger.debug(f"Will start replacement bot in {random_delay:.2f} seconds")
        else:
            del bot_state["processes"][process_id]

    def _handle_bot_error(
        self, bot_state, process_info, process_id, error, current_time, end_time
    ):
        """Handle a bot process error."""
        bot_id = process_info["bot_id"]
        bot_state["bot_monitor_errors"][bot_id] = error
        bot_state["total_bot_errors"] += 1

        if current_time < end_time:
            random_delay = self._bounded_random_stagger()
            process_info["next_start_time"] = current_time + random_delay
            logger.debug(f"Will start replacement bot in {random_delay:.2f} seconds")
        else:
            del bot_state["processes"][process_id]

    def _calculate_and_report_results(
        self, n, duration_minutes, actual_duration, initial_state, bot_state
    ):
        """Calculate final metrics and report results."""
        from dallinger import db
        from sqlalchemy import case, func

        from psynet.bot import Bot
        from psynet.experiment import Request
        from psynet.process import AsyncProcess

        # Get final request state from DB
        final_stats = self.authenticated_session.get(
            self.base_url + "/request_statistics"
        ).json()
        final_requests = final_stats["total_requests"]

        requests_during_test = final_requests - initial_state["initial_requests"]

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
                Request.id > initial_state["max_request_id"],
                Request.endpoint.in_(key_endpoints),
            )
            .one()
        )

        request_errors = (
            db.session.query(func.count(Request.id))
            .filter(
                Request.id > initial_state["max_request_id"],
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

    # EXPORT
    if result.get("export_duration_s") is not None:
        _section("EXPORT")
        export_rows = [
            ["Duration", f"{result['export_duration_s']:.1f}s"],
        ]
        if result.get("export_error"):
            export_rows.append(["Error", result["export_error"]])
        _table_lines(export_rows, headers=[], colalign=("left", "right"))
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

    has_export = any(r.get("export_duration_s") is not None for r in results)
    baseline_export = results[0].get("export_duration_s") if show_scaling else None

    summary_headers = [
        "|| Bots",
        "Succeeded",
        "Requests",
        "Req/s",
        "Resp Med (s)",
    ]
    if show_scaling:
        summary_headers.append("vs base")
    summary_headers.append("Q Med all (s)")
    if show_scaling:
        summary_headers.append("vs base")
    if has_export:
        summary_headers.append("Export (s)")
        if show_scaling:
            summary_headers.append("vs base")

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
        if has_export:
            export_dur = result.get("export_duration_s")
            row.append(_fmt(export_dur))
            if show_scaling:
                if i == 0:
                    row.append("\u2014")
                elif export_dur is not None and baseline_export and baseline_export > 0:
                    row.append(f"{export_dur / baseline_export:.1f}x")
                else:
                    row.append("N/A")
        summary_rows.append(row)

    lines.append("")
    lines.append(bold("CUMULATIVE PERFORMANCE TEST SUMMARY\n"))
    lines.append(
        "  Resp Med — median HTTP response time for key endpoints (/timeline, /response)"
    )
    lines.append("  Q Med all — median queue delay across all async processes")
    if has_export:
        lines.append("  Export — time to run psynet export local")
    lines.append(
        "  vs base — ratio to the first (lowest bot-count) row, if multiple counts are run"
    )
    lines.append("")
    table = tabulate(summary_rows, headers=summary_headers, tablefmt="simple")
    for line in table.splitlines():
        lines.append(f"  {line}")
    lines.append("")

    return lines

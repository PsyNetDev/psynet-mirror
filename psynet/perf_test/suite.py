"""Run performance tests one after another, then summarize them.

:class:`PerformanceSuite` chooses each test's bot count, from a list or by
searching for capacity, and stops early when a test ends early. Its
``before_test`` hook can reset the database before each test (see
:mod:`psynet.perf_reset`).

The tester that runs each test is passed in, so this module does not import
:mod:`psynet.perf_test.runtime`; tests can give the suite a fake tester.
"""

import logging

from psynet.log import bold, warning
from psynet.perf_test.report import (
    format_capacity_summary,
    format_performance_summary,
)
from psynet.perf_test.results import (
    CAPACITY_SEARCH_MAX,
    CAPACITY_SEARCH_MAX_TESTS,
    CAPACITY_SEARCH_START,
    CapacityLimits,
    capacity_failure_causes,
    next_capacity_probe,
    short_test_warning,
)

logger = logging.getLogger(__name__)


def _ended_early(result):
    """Return whether a test ended in a way that stops its suite.

    That includes a bot process not reporting after the test, because it may
    be stuck and would be sent the next test's bots as well.
    """
    return bool(
        result.server_stopped
        or result.bot_process_failure
        or result.unreported_bot_processes
    )


class PerformanceSuite:
    """Run performance tests one after another, then summarize them.

    The suite chooses each test's bot count, from a list (:meth:`run`) or by
    searching for capacity (:meth:`find_capacity`), and stops early when a
    test ends early. ``tester`` runs each test.

    Parameters
    ----------
    tester : PerformanceTester
        Runs the tests.
    limits : CapacityLimits, optional
        The limits that the capacity search and summary judge tests by.
    before_test : callable, optional
        Called before each test, including the first, instead of the pause
        between tests, once the bots have closed their database connections;
        for example a :class:`psynet.perf_reset.DatabaseReset`.
    """

    def __init__(self, tester, limits=None, before_test=None):
        self.tester = tester
        self.limits = limits or CapacityLimits()
        self.before_test = before_test

    def run(self, bot_counts, bot_log_file=None):
        """Run a test for each of ``bot_counts``, in order."""
        self._print_suite_header(", ".join(str(n) for n in bot_counts))

        def next_bot_count(results):
            return bot_counts[len(results)] if len(results) < len(bot_counts) else None

        return self._run_suite(
            max(bot_counts), next_bot_count, bot_log_file, n_tests=len(bot_counts)
        )

    def find_capacity(self, bot_log_file=None):
        """Search for the largest bot count the server handles within limits.

        Doubles the bot count from 10 until a test fails
        :func:`~psynet.perf_test.results.capacity_failures`, then bisects between the largest passing and
        smallest failing counts until they are within 10% of each other.

        Returns
        -------
        list[PerformanceTestResult]
            One result per test, in the order they ran.
        """
        self._print_suite_header(
            f"automatic (from {CAPACITY_SEARCH_START}, while keeping "
            f"{self.limits.describe()}; a test in which bots can't start fast "
            "enough, or run late because their process is too busy, "
            "could not be tested)"
        )
        max_tests = CAPACITY_SEARCH_MAX_TESTS
        between = (
            "a database reset before each test"
            if self.before_test is not None
            else "pauses between tests"
        )
        logger.info(
            f"Expected run time:    up to {max_tests} tests, about "
            f"{max_tests * self.tester.duration_minutes:g} min plus {between}"
        )
        highest_pass = lowest_fail = None

        def next_bot_count(results):
            nonlocal highest_pass, lowest_fail
            if results:
                n_bots = results[-1].n_bots
                causes = capacity_failure_causes(results[-1], self.limits)
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

        return self._run_suite(CAPACITY_SEARCH_MAX, next_bot_count, bot_log_file)

    def _run_suite(self, max_bots, next_bot_count, bot_log_file, n_tests=None):
        """Run tests until ``next_bot_count(results_so_far)`` returns ``None``.

        Stops early if a test ends early, then prints the summary. ``max_bots``
        is the most bots any test may run, which sets the bot processes.

        Returns
        -------
        list[PerformanceTestResult]
            One result per test, in the order they ran.
        """
        all_results = []
        with self.tester.bot_runner(max_bots, bot_log_file):
            while (n_bots := next_bot_count(all_results)) is not None:
                if self.before_test is not None:
                    self.tester.release_database_connections()
                    self.before_test()
                elif all_results:
                    self.tester.pause_between_tests()
                label = f"{len(all_results) + 1}" + (f"/{n_tests}" if n_tests else "")
                result = self.tester.run_test(label, n_bots, bot_log_file)
                all_results.append(result)
                if _ended_early(result):
                    break
        for line in format_performance_summary(all_results):
            logger.info(line)
        for line in format_capacity_summary(
            all_results, self.limits, self.tester.time_factor
        ):
            logger.info(line)
        return all_results

    def _print_suite_header(self, bots_description):
        tester = self.tester
        logger.info(bold("=" * 80))
        logger.info(bold("\u26a1 PERFORMANCE TEST SUITE"))
        logger.info(f"Bots per test:        {bots_description}")
        logger.info(f"Test duration:        {tester.duration_minutes:g} min")
        if tester.estimated_duration_minutes is not None:
            paced = (
                ""
                if tester.time_factor == 1
                else f", {tester.session_minutes:.1f} min at the bots' time factor"
            )
            logger.info(
                "Estimated session:    "
                f"{tester.estimated_duration_minutes:.1f} min (from the timeline's "
                f"time estimates){paced}"
            )
        logger.info(f"Bot start stagger:    ~{tester.stagger_interval_s:g}s")
        logger.info(f"Bot time factor:      {tester.time_factor:g}")
        short = short_test_warning(tester.duration_minutes, tester.session_minutes)
        if short:
            logger.warning(warning(short))

"""Run performance tests one after another, then summarize them.

:class:`PerformanceSuite` chooses each test's bot count, from a list or by
searching for capacity, and stops early when a test ends early. A capacity
search's tests are short, so it ends with one longer confirmation test, with
spread-out arrivals, at the cap it suggests. Its
``before_test`` hook can reset the database before each test (see
:class:`psynet.perf_ssh.DatabaseReset`).

The tester that runs each test is passed in, so this module does not import
:mod:`psynet.perf_test.runtime`; tests can give the suite a fake tester.
"""

import logging
import time

from rich.text import Text

from psynet.perf_test.report import (
    format_performance_summary,
    format_text,
    stopped_early_lines,
    warning,
)
from psynet.perf_test.results import (
    CAPACITY_SEARCH_MAX,
    CAPACITY_SEARCH_MAX_TESTS,
    CAPACITY_SEARCH_START,
    CapacityLimits,
    capacity_failure_causes,
    capacity_outcome,
    confirmation_timing,
    next_capacity_probe,
    short_test_warning,
)

logger = logging.getLogger(__name__)

_NO_CAP = "the search found no number of participants to recommend"


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
        between tests; for example a :class:`psynet.perf_ssh.DatabaseReset`.
    label : str, optional
        The experiment's label, for the summary.
    after_test : callable, optional
        Called with the list of results so far after each test, for example
        to save them.
    local : bool
        Whether the bots and the server run on this computer, which the
        summary then says.
    """

    def __init__(
        self,
        tester,
        limits=None,
        before_test=None,
        label=None,
        after_test=None,
        local=False,
    ):
        self.tester = tester
        self.local = local
        self.limits = limits or CapacityLimits()
        self.before_test = before_test
        self.label = label
        self.after_test = after_test
        # Why find_capacity skipped its confirmation test, or None.
        self.confirmation_skipped = None
        # Why a database reset between tests failed and stopped the suite, or None.
        self.reset_error = None

    def run(self, bot_counts, bot_log_file=None):
        """Run a test for each of ``bot_counts``, in order."""
        self._print_suite_header(", ".join(str(n) for n in bot_counts))
        tester = self.tester

        def next_test(results):
            if len(results) < len(bot_counts):
                n_bots = bot_counts[len(results)]
                return n_bots, tester.duration_minutes, tester.arrival_minutes, False
            return None

        return self._run_suite(
            max(bot_counts), next_test, bot_log_file, n_tests=len(bot_counts)
        )

    def find_capacity(self, bot_log_file=None, confirm=True):
        """Search for the largest bot count the server handles within limits.

        Doubles the bot count from 10 until a test fails
        :func:`~psynet.perf_test.results.capacity_failures`, then bisects between the largest passing and
        smallest failing counts until they are within 10% of each other.
        Then, if the search suggests a participant cap, a confirmation test
        runs that many bots arriving over about one session, for about two
        (see :func:`~psynet.perf_test.results.confirmation_timing`), and
        decides whether the summary reports the cap as confirmed.

        Parameters
        ----------
        bot_log_file : file, optional
            Where the bots log.
        confirm : bool
            Whether to run the confirmation test. It never runs with a time
            factor of 0, whose pace isn't realistic.

        Returns
        -------
        list[PerformanceTestResult]
            One result per test, in the order they ran; the confirmation
            test, if it ran, is last and has ``confirmation`` set.
        """
        tester = self.tester
        self._print_suite_header(
            f"automatic (from {CAPACITY_SEARCH_START}, while keeping "
            f"{self.limits.describe()}; a test in which bots can't start fast "
            "enough, or run late because their process is too busy, "
            "could not be tested)",
            search=True,
        )
        if not confirm:
            self.confirmation_skipped = "--no-confirm"
        elif not tester.time_factor:
            self.confirmation_skipped = (
                "--time-factor 0, at which bots don't keep a participant's pace"
            )
        elif not tester.session_minutes:
            self.confirmation_skipped = (
                "the experiment's estimated session length is unknown, so the "
                "test can't be timed to reach the steady state"
            )
        else:
            self.confirmation_skipped = None
        confirm_minutes, confirm_arrival = confirmation_timing(
            tester.session_minutes, tester.duration_minutes
        )
        max_tests = CAPACITY_SEARCH_MAX_TESTS
        between = (
            "a database reset before each test"
            if self.before_test is not None
            else "pauses between tests"
        )
        search_minutes = max_tests * tester.duration_minutes
        if self.confirmation_skipped:
            confirming = f"no validation test ({self.confirmation_skipped})"
        else:
            arriving = (
                f", bots arriving over {confirm_arrival:g} min"
                if confirm_arrival
                else ""
            )
            confirming = (
                f"then a {confirm_minutes:g}-min validation test at the recommended "
                f"number of participants{arriving}; up to "
                f"{search_minutes + confirm_minutes:g} min in all"
            )
        logger.info(
            f"Expected run time:    up to {max_tests} tests of "
            f"{tester.duration_minutes:g} min ({search_minutes:g} min), "
            f"{confirming}, plus {between}"
        )
        highest_pass = lowest_fail = None
        confirming_cap = None

        def next_test(results):
            nonlocal highest_pass, lowest_fail, confirming_cap
            if confirming_cap is not None:
                return None
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
            n_bots = next_capacity_probe(highest_pass, lowest_fail)
            if n_bots is not None:
                return n_bots, tester.duration_minutes, None, False
            if self.confirmation_skipped:
                return None
            confirming_cap = capacity_outcome(results, self.limits).cap
            if confirming_cap is None:
                self.confirmation_skipped = _NO_CAP
                return None
            return confirming_cap, confirm_minutes, confirm_arrival, True

        results = self._run_suite(
            CAPACITY_SEARCH_MAX,
            next_test,
            bot_log_file,
            confirmation_planned=not self.confirmation_skipped,
        )
        if self.reset_error and not any(r.confirmation for r in results):
            self.confirmation_skipped = (
                self.confirmation_skipped or "resetting the database failed"
            )
        elif confirming_cap is None and results and _ended_early(results[-1]):
            self.confirmation_skipped = (
                self.confirmation_skipped or "a test ended early"
            )
        if self.confirmation_skipped and results:
            unconfirmed = (
                ""
                if self.confirmation_skipped == _NO_CAP
                else "; any recommendation above comes from short tests in which "
                "the bots arrived together"
            )
            for line in format_text(
                f"Validation test skipped: {self.confirmation_skipped}{unconfirmed}.",
                None,
            ):
                logger.info(line)
        return results

    def _run_suite(
        self,
        max_bots,
        next_test,
        bot_log_file,
        n_tests=None,
        confirmation_planned=False,
    ):
        """Run tests until ``next_test(results_so_far)`` returns ``None``.

        ``next_test`` returns the next test's bot count, length and arrival
        window in minutes, and whether it is the confirmation test, and the
        suite records them in the test's result. Stops early if a
        test ends early, then prints the summary. If a test raises, prints
        the summary of the tests before it and re-raises. ``max_bots`` is the most
        bots any test may run, which sets the bot processes.
        ``confirmation_planned`` says a capacity search meant to end with a
        confirmation test.

        Returns
        -------
        list[PerformanceTestResult]
            One result per test, in the order they ran.
        """
        all_results = []
        started = time.monotonic()
        with self.tester.bot_runner(max_bots, bot_log_file):
            while (test := next_test(all_results)) is not None:
                n_bots, duration_minutes, arrival_minutes, confirmation = test
                if self.before_test is not None:
                    try:
                        self.before_test()
                    except Exception as e:
                        self.reset_error = str(e) or type(e).__name__
                        logger.debug("Resetting the database failed", exc_info=True)
                        break
                elif all_results:
                    self.tester.pause_between_tests()
                if confirmation:
                    title = "VALIDATION TEST"
                else:
                    title = f"TEST {len(all_results) + 1}" + (
                        f"/{n_tests}" if n_tests else ""
                    )
                try:
                    result = self.tester.run_test(
                        title, n_bots, bot_log_file, duration_minutes, arrival_minutes
                    )
                except Exception as e:
                    if all_results:
                        self._log_summary(all_results, started, confirmation_planned)
                        error = (str(e).strip().splitlines() or [type(e).__name__])[0]
                        for line in stopped_early_lines(error[:300], len(all_results)):
                            logger.info(line)
                    raise
                result.duration_minutes = duration_minutes
                result.arrival_minutes = arrival_minutes
                result.session_minutes = self.tester.session_minutes
                result.confirmation = confirmation
                all_results.append(result)
                if self.after_test is not None:
                    self.after_test(all_results)
                if _ended_early(result):
                    break
        if not all_results:
            # No test ran, as when the first reset failed; the caller reports it.
            return all_results
        self._log_summary(all_results, started, confirmation_planned)
        if self.reset_error:
            for line in stopped_early_lines(
                self.reset_error,
                len(all_results),
                step="resetting the database before",
            ):
                logger.info(line)
        return all_results

    def _log_summary(self, all_results, started, confirmation_planned):
        """Log the summary of ``all_results``, the tests that completed."""
        for line in format_performance_summary(
            all_results,
            self.limits,
            self.tester.time_factor,
            label=self.label,
            elapsed_s=time.monotonic() - started,
            confirmation_planned=confirmation_planned,
            local=self.local,
        ):
            logger.info(line)

    def _print_suite_header(self, bots_description, search=False):
        tester = self.tester
        for line in format_text(
            Text("=" * 80, style="bold"),
            Text("\u26a1 PERFORMANCE TEST SUITE", style="bold"),
        ):
            logger.info(line)
        logger.info(f"Bots per test:        {bots_description}")
        logger.info(
            f"Test duration:        {tester.duration_minutes:g} min"
            + (" per search test" if search else "")
        )
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
        if tester.arrival_minutes:
            logger.info(
                f"Bot arrivals:         evenly over {tester.arrival_minutes:g} min"
            )
            logger.info(
                f"Bot start stagger:    ~{tester.stagger_interval_s:g}s, "
                "after a bot finishes"
            )
        else:
            logger.info(f"Bot start stagger:    ~{tester.stagger_interval_s:g}s")
        logger.info(f"Bot time factor:      {tester.time_factor:g}")
        if search:
            # Search tests are short on purpose; the confirmation test sees
            # the steady state.
            return
        short = short_test_warning(tester.duration_minutes, tester.session_minutes)
        if short:
            logger.warning(warning(short))

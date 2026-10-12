"""Load tests that run simulated participants against a PsyNet server.

:class:`PerformanceSuite` and :class:`PerformanceTester` back ``psynet
performance-test``. The tester runs one test: it keeps a fixed number of bots
taking the experiment at once, then reads the server's ``Request`` and
``AsyncJob`` tables to measure response times and async queue waits. The
suite runs a test per bot count, or with :meth:`PerformanceSuite.find_capacity`
searches for the largest bot count that stays within :class:`CapacityLimits`.
Its ``before_test`` hook can reset the database before each test (see
:mod:`psynet.perf_reset`).

The package is split by what each part needs to import:

- :mod:`~psynet.perf_test.results`: the result dataclass, capacity limits and
  the capacity search step; no bots or database.
- :mod:`~psynet.perf_test.report`: terminal reports of results; imports only
  ``results``.
- :mod:`~psynet.perf_test.measure`: database queries that turn a test window
  into measurements.
- :mod:`~psynet.perf_test.runtime`: the tester, its bot threads and bot
  processes.
- :mod:`~psynet.perf_test.suite`: series of tests and capacity searches.

Import the public names below from :mod:`psynet.perf_test` itself. Names that
the submodules share with each other are not part of this API.
"""

from psynet.perf_test.measure import (
    count_non_bot_participants,
    wait_for_async_jobs,
)
from psynet.perf_test.report import (
    capacity_advice,
    format_capacity_summary,
    format_performance_summary,
    format_test_results,
)
from psynet.perf_test.results import (
    DEFAULT_MAX_P95_S,
    DEFAULT_MAX_QUEUE_P95_S,
    CapacityLimits,
    PerformanceTestResult,
    capacity_failures,
    default_duration_minutes,
    next_capacity_probe,
    queue_wait_p95,
)
from psynet.perf_test.runtime import (
    PerformanceTester,
    log_to_console,
    prefill_database,
    raise_open_file_limit,
    server_is_reachable,
)
from psynet.perf_test.suite import PerformanceSuite

__all__ = [
    "DEFAULT_MAX_P95_S",
    "DEFAULT_MAX_QUEUE_P95_S",
    "CapacityLimits",
    "PerformanceSuite",
    "PerformanceTestResult",
    "PerformanceTester",
    "capacity_advice",
    "capacity_failures",
    "count_non_bot_participants",
    "default_duration_minutes",
    "format_capacity_summary",
    "format_performance_summary",
    "format_test_results",
    "log_to_console",
    "next_capacity_probe",
    "prefill_database",
    "queue_wait_p95",
    "raise_open_file_limit",
    "server_is_reachable",
    "wait_for_async_jobs",
]

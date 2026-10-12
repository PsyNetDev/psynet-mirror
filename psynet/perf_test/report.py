"""Format performance test results for the terminal.

:func:`format_test_results` reports one test, :func:`format_performance_summary`
compares the tests of a suite, and :func:`format_capacity_summary` explains
where a capacity search stopped and what to try next.

These are pure functions of saved results and limits from
:mod:`psynet.perf_test.results`; they don't import bots or the database, so
they can format results that were read back from JSON. The wording is what
users read, and tests pin much of it, so change it deliberately.
"""

from tabulate import tabulate

from psynet.log import bold, error, success, warning
from psynet.perf_test.results import (
    CAPACITY_HEADROOM,
    MIN_STEADY_STATE_S,
    POSTGRES_FULL,
    PROCESS_STAT_KEYS,
    CapacityLimits,
    capacity_failure_causes,
    capacity_outcome,
    count_wait_timeouts,
    describe_bot_errors,
    overshoot,
    phase_limit_reasons,
    plural,
    queue_wait_p95,
    retry_bot_count,
    start_rate_limits,
    tester_lagged,
    top_counts,
    wait_timeout_cause,
    wait_timeout_reasons,
)


def _fmt(value, suffix=""):
    return f"{value:.3f}{suffix}" if value is not None else "N/A"


def _describe_workers(result):
    """Describe the async worker processes and how many jobs they can run at once."""
    n_workers = result.n_rq_workers
    if not n_workers:
        return ""
    text = f"{n_workers} worker process{'es' if n_workers != 1 else ''}"
    n_slots = result.n_rq_job_slots
    if n_slots and n_slots != n_workers:
        text += f", up to {n_slots} jobs at once"
    return text


def format_test_results(result):
    """Format detailed results after a single test completes. Returns list[str]."""
    return [
        "",
        success("\u2713 Test completed"),
        bold(f"TEST RESULTS (n={result.n_bots:,} bots)"),
        "",
        *_bot_outcome_lines(result),
        *_runtime_lines(result),
        *_init_time_lines(result),
        *_request_lines(result),
        *_async_process_lines(result),
        *_phase_lines(result),
        *_database_row_lines(result),
    ]


def _phase_lines(result):
    """Return the START-UP VS STEADY STATE section."""
    lines = _section("START-UP VS STEADY STATE")
    first = result.first_completion_s
    length = result.actual_duration or 0
    if first is None:
        return lines + [
            "  No bot completed the experiment during the test, so it only saw "
            "the start-up, when every bot was in its first session.",
            "",
        ]
    startup, steady = result.startup_phase, result.steady_state_phase
    if not (startup and steady):
        return lines + [
            f"  The first bot completed the experiment {first:.0f} s into the "
            f"{length:.0f} s test, leaving less than {MIN_STEADY_STATE_S} s of "
            "steady state to report separately.",
            "",
        ]
    rows = [
        ["Requests", f"{startup['key_requests']:,}", f"{steady['key_requests']:,}"],
        [
            "p95 response time",
            _fmt(startup["p95_response_time"], "s"),
            _fmt(steady["p95_response_time"], "s"),
        ],
        [
            "Request errors",
            f"{startup['request_errors']:,}",
            f"{steady['request_errors']:,}",
        ],
    ]
    steady_queue = [
        w for w in (steady["q_delay_p95"], result.oldest_queued_s) if w is not None
    ]
    if startup["q_delay_p95"] is not None or steady_queue:
        rows.append(
            [
                "p95 async queue wait",
                _fmt(startup["q_delay_p95"], "s"),
                _fmt(max(steady_queue, default=None), "s"),
            ]
        )
    return [
        *lines,
        f"  Start-up: the first {first:.0f} s, until the first bot completed the "
        f"experiment. Steady state: the other {length - first:.0f} s.",
        *_table_lines(
            rows,
            headers=["", "Start-up", "Steady state"],
            min_label_width=0,
            colalign=("left", "right", "right"),
        ),
        "",
    ]


def _section(title):
    """Return the heading lines of a report section."""
    return [bold(f"  {title}"), f"  {'-' * 36}"]


def _table_lines(rows, headers=(), indent="  ", min_label_width=28, **kwargs):
    """Return ``rows`` as indented table lines.

    Without ``headers``, the first column is padded to ``min_label_width``
    so that consecutive tables line up.
    """
    kwargs.setdefault("tablefmt", "plain")
    if min_label_width and rows and not headers:
        rows = [[r[0].ljust(min_label_width)] + r[1:] for r in rows]
    table = tabulate(rows, headers=headers, **kwargs)
    return [f"{indent}{line}" for line in table.splitlines()]


def _label_table(rows):
    """Return ``[label, value]`` rows as table lines with right-aligned values."""
    return _table_lines(rows, colalign=("left", "right"))


def _bot_outcome_lines(result):
    """Return the BOT OUTCOMES section and, if any, why participants failed and bot errors."""
    bots_in_db = (
        result.bots_succeeded
        + result.bots_failed
        + result.bots_incomplete
        + result.participants_failed
    )
    bots_not_in_db = result.total_bots_started - bots_in_db
    outcome_rows = [
        ["Bots started", result.total_bots_started],
        ["Completed successfully", result.bots_succeeded],
        ["Failed by the experiment", result.participants_failed],
        ["Bot error or other status", result.bots_failed],
        ["Stopped at the end of the test", result.bots_incomplete],
    ]
    if bots_not_in_db > 0:
        outcome_rows.append(["Never reached DB", bots_not_in_db])
    lines = [*_section("BOT OUTCOMES"), *_label_table(outcome_rows), ""]

    if result.failed_reasons:
        waits = wait_timeout_reasons(result)
        # Wait timeouts count against capacity, so they are never folded away.
        shown = [
            (reason, n)
            for i, (reason, n) in enumerate(result.failed_reasons.items())
            if i < 5 or reason in waits
        ]
        reason_rows = [
            [reason + (" (waited too long)" if reason in waits else ""), n]
            for reason, n in shown
        ]
        others = sum(result.failed_reasons.values()) - sum(n for _, n in shown)
        if others:
            reason_rows.append(["Other reasons", others])
        lines += [
            *_section("WHY THE EXPERIMENT FAILED PARTICIPANTS"),
            *_label_table(reason_rows),
            "",
        ]

    if result.bot_error_kinds:
        lines += [
            *_section("BOT ERRORS"),
            *_label_table([[kind, n] for kind, n in result.bot_error_kinds.items()]),
            "",
        ]
    return lines


def _runtime_lines(result):
    """Return the BOT RUNTIMES section: test length, bot runtimes and bot process load."""
    rows = []
    if result.actual_duration is not None:
        rows.append(["Test duration", f"{result.actual_duration:.1f}s"])
    for label, value in [
        ("Avg runtime", result.avg_bot_duration),
        ("Avg runtime (succeeded)", result.avg_succeeded_duration),
        (
            "Avg runtime (failed by the experiment)",
            result.avg_experiment_failed_duration,
        ),
        ("Avg runtime (bot error or other status)", result.avg_failed_duration),
        ("Avg runtime (stopped at the end)", result.avg_incomplete_duration),
    ]:
        if value is not None:
            rows.append([label, f"{value:.1f}s"])
    if result.tester_lag_p95_s is not None:
        lag = f"{result.tester_lag_p95_s * 1000:.0f} ms"
        rows.append(
            [
                "Bot lag (p95, worst process)",
                warning(lag) if tester_lagged(result) else lag,
            ]
        )
    if result.tester_cpu_share is not None:
        rows.append(
            ["Bot process CPU (busiest)", f"{result.tester_cpu_share:.0%} of a core"]
        )
    return [*_section("BOT RUNTIMES"), *(_label_table(rows) if rows else []), ""]


def _init_time_lines(result):
    """Return the BOT INIT TIMES section, or nothing if no bot started."""
    if not result.n_init_samples:
        return []
    rows = [
        ["Median", _fmt(result.median_init_time, "s")],
        ["95th percentile", _fmt(result.p95_init_time, "s")],
        ["Max", _fmt(result.max_init_time, "s")],
    ]
    return [
        *_section(f"BOT INIT TIMES (n={result.n_init_samples}):"),
        *_label_table(rows),
        "",
    ]


def _request_lines(result):
    """Return the request, response time, wait page and trials-per-bot sections."""
    request_rows = [
        ["Total requests", result.total_requests],
        # Requests that fail before the server can log them appear only
        # under BOT ERRORS.
        ["Request errors (logged)", result.request_errors],
    ]
    if result.busy_responses:
        request_rows.append(["Busy/stale responses (409/503)", result.busy_responses])
    if result.requests_per_sec is not None:
        request_rows.append(["Throughput", f"{result.requests_per_sec:.2f} req/s"])
    lines = [*_section("REQUEST METRICS"), *_label_table(request_rows), ""]

    lines += _section(
        f"RESPONSE TIMES (n={result.key_requests} /timeline and /response requests)"
    )
    lines += _label_table(
        [
            ["Median", _fmt(result.median_response_time, "s")],
            ["95th percentile", _fmt(result.p95_response_time, "s")],
            ["99th percentile", _fmt(result.p99_response_time, "s")],
            ["Max", _fmt(result.max_response_time, "s")],
            ["Mean", _fmt(result.avg_response_time, "s")],
            ["Std dev", _fmt(result.stddev_response_time, "s")],
        ]
    )
    lines.append("")

    if result.median_wait_page_time is not None:
        n_wait = result.n_wait_page_samples
        bot_word = "bot" if n_wait == 1 else "bots"
        lines += _section(
            f"TIME ON WAIT PAGES PER BOT (n={n_wait} {bot_word} that completed "
            "or were failed by the experiment)"
        )
        lines += _label_table(
            [
                ["Median", f"{result.median_wait_page_time:.1f}s"],
                ["95th percentile", f"{result.p95_wait_page_time:.1f}s"],
                ["Max", f"{result.max_wait_page_time:.1f}s"],
            ]
        )
        lines.append("")

    n_succeeded = result.bots_succeeded
    bot_word = "bot" if n_succeeded == 1 else "bots"
    lines += _section(
        f"TRIALS PER BOT (n={n_succeeded} {bot_word} that completed successfully)"
    )
    lines += _label_table(
        [
            ["Min", result.min_trial_count or 0],
            ["Median", result.median_trial_count or 0],
            ["Max", result.max_trial_count or 0],
        ]
    )
    lines.append("")
    return lines


_ASYNC_TABLE_LEGEND = [
    "  Avg/Med/P95/Max — statistics on actual execution time",
    "  Q Avg/Q Med/Q P95 — statistics on queue delay (time waiting in RQ queue)",
    "  Q Share — avg of per-process queue_delay / (queue_delay + exec_time),",
    "    i.e. avg percentage of total time spent queuing rather than executing",
    "  Colors: yellow = Q Share > 20% and Q P95 > 0.2s (moderate contention)",
    "          red = Q Share > 20% and Q P95 > 0.5s (significant contention)",
    "\n",
]


def _async_process_lines(result):
    """Return the ASYNC PROCESS TIMES section and any backlog left at the end."""
    worker_info = _describe_workers(result)
    if result.process_stats:
        n_procs = sum(ps["count"] for ps in result.process_stats)
        worker_info = f", {worker_info}" if worker_info else ""
        proc_rows = [
            [
                ps["trial_maker_id"],
                ps["label"],
                ps["count"],
                *(_fmt(ps[key]) for key in PROCESS_STAT_KEYS if key != "q_share"),
                _q_share_text(ps["q_share"], ps["q_p95"]),
            ]
            for ps in result.process_stats
        ]
        lines = [
            *_section(f"ASYNC PROCESS TIMES ({n_procs} completed{worker_info})"),
            *_ASYNC_TABLE_LEGEND,
            *_table_lines(
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
                colalign=("left", "left") + ("right",) * 8,
            ),
            "",
        ]
    else:
        worker_info = f" ({worker_info})" if worker_info else ""
        lines = [
            *_section(f"ASYNC PROCESS TIMES{worker_info}"),
            "  No completed async processes.",
            "",
        ]

    if result.oldest_queued_s is not None:
        lines += [
            warning(
                "  Still queued when the test ended: oldest process had waited "
                f"{result.oldest_queued_s:.1f}s for a worker."
            ),
            "",
        ]
    return lines


def _q_share_text(q_share, q_p95):
    """Format an async process's queue share, colored by how much it queued."""
    if q_share is None or q_p95 is None:
        return "N/A"
    text = f"{q_share:.0%}"
    if q_share > 0.2 and q_p95 > 0.5:
        return error(text)
    if q_share > 0.2 and q_p95 > 0.2:
        return warning(text)
    return text


def _database_row_lines(result):
    """Return the DATABASE ROWS section, or nothing if the result has no row counts."""
    before, after = result.db_rows_before or {}, result.db_rows_after or {}
    if not (before or after):
        return []
    rows = [
        [table, f"{before.get(table, 0):,}", f"{after.get(table, 0):,}"]
        for table in {**before, **after}
    ]
    return [
        *_section("DATABASE ROWS"),
        *_table_lines(
            rows,
            headers=["Table", "Before", "After"],
            min_label_width=0,
            colalign=("left", "right", "right"),
        ),
        "",
    ]


def _ratio(value, baseline, is_baseline):
    """Format ``value / baseline`` for the summary's "vs base" columns."""
    if is_baseline:
        return "\u2014"
    if value is None or not baseline or baseline <= 0:
        return "N/A"
    return f"{value / baseline:.1f}x"


_NOT_MEASURED = (
    "  Not measured: uploads over participants' own networks (bots upload from "
    "next to the server), media downloads and bandwidth, the front door (web "
    "proxy or Cloudflare tunnel) and browser rendering. Check these separately "
    "if your study plays or records a lot of media."
)


def format_performance_summary(results):
    """Format cross-test comparison table.

    ``results`` are in the order the tests ran. Returns list[str].
    """
    lines = []
    database_growth = _describe_database_growth(results)
    # The confirmation test is longer than the others, so it comes last
    # rather than serving as the baseline.
    results = sorted(results, key=lambda r: (r.confirmation, r.n_bots))

    show_scaling = len(results) > 1 and results[0].median_response_time is not None
    baseline_response_median = results[0].median_response_time if show_scaling else None
    baseline_q_median = results[0].q_delay_median if show_scaling else None

    show_failed = any(r.participants_failed for r in results)
    summary_headers = ["Bots", "Succeeded"]
    if show_failed:
        summary_headers.append("Failed by exp.")
    summary_headers += [
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
        response_median = result.median_response_time
        q_median = result.q_delay_median
        row = [
            f"{result.n_bots} (confirmation)" if result.confirmation else result.n_bots,
            result.bots_succeeded,
        ]
        if show_failed:
            row.append(result.participants_failed)
        row += [
            result.total_requests,
            (
                f"{result.requests_per_sec:.1f}"
                if result.requests_per_sec is not None
                else "N/A"
            ),
            _fmt(result.p95_response_time),
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
    if database_growth:
        lines.append(
            f"  Database rows from the first test to the last: {database_growth}."
        )
        lines.append("")
    lines += [_NOT_MEASURED, ""]
    return lines


def _describe_database_growth(results):
    """Describe how the growing tables changed over ``results``, in the order run.

    Returns e.g. ``"participant 0 to 120, trial 0 to 4,300"``, naming only
    tables that have rows, or ``""`` if the results don't record rows.
    """
    if not results:
        return ""
    before = results[0].db_rows_before or {}
    after = results[-1].db_rows_after or {}
    return ", ".join(
        f"{table} {before.get(table, 0):,} to {after.get(table, 0):,}"
        for table in {**before, **after}
        if before.get(table) or after.get(table)
    )


_POSTGRES_ADVICE = (
    "  Some bots failed because PostgreSQL ran out of connections. The bots "
    "open their own database connections in the processes running them, which "
    "participants don't, so this limits the test rather than the experiment. "
    "Run fewer bots at once, stop other experiments that share the database "
    "server, or raise max_connections."
)
_QUEUE_ADVICE = (
    "  Async processes waited too long for a worker: add worker processes "
    "with num_dynos_worker, or make the processes faster."
)
_WAIT_ADVICE = (
    "  Participants waited too long and the experiment failed them. Design "
    "experiments to avoid this, for example with a longer max_wait_time or "
    "enough participants to fill groups and chains; at high bot counts it can "
    "also mean the server is too slow."
)
_START_RATE_ADVICE = (
    "  Bots that cannot start fast enough limit the test rather than the "
    "server, because the processes running the bots create each bot's "
    "participant themselves. Bots that take longer, in a longer experiment or "
    "with a larger --time-factor, give a better measure of the server."
)
_TESTER_LAG_ADVICE = (
    "  A process running bots was so busy that its bots ran late and made "
    "requests more slowly than participants would, so the server got less "
    "load than the bot count suggests. Spread the bots over more processes "
    "with --bot-processes, or run the test from a computer with more CPU cores."
)


# Tables whose row counts differ by at least this factor, and by at least
# this many rows, make tests hard to compare. A capacity search on a static
# rating study that ran from 65k to 103k trials (1.6 times) suggested a cap
# that failed once the study held twice as many.
_DB_GROWTH_RATIO = 1.5
_DB_GROWTH_MIN_ROWS = 10_000


def _tables_that_differ(rows_a, rows_b):
    """Return ``"table a and b"`` descriptions of the tables whose row counts differ a lot."""
    differ = []
    for table in {**rows_a, **rows_b}:
        a, b = rows_a.get(table, 0), rows_b.get(table, 0)
        low, high = sorted((a, b))
        if high - low >= _DB_GROWTH_MIN_ROWS and high >= _DB_GROWTH_RATIO * low:
            differ.append(f"{table} {a:,} and {b:,}")
    return differ


def _database_growth_warnings(
    results, capacity_result, first_fail, confirmation=None, limits=CapacityLimits()
):
    """Warn when the tests in ``results`` (in the order run) saw very different amounts of data.

    ``confirmation`` is a capacity search's confirmation test, which runs on
    the data the search tests left unless the database is reset.
    """
    lines = []
    if not results:
        return lines
    grew = _tables_that_differ(
        results[0].db_rows_before or {}, results[-1].db_rows_after or {}
    )
    if grew:
        lines.append(
            "  The database grew a lot during these tests (rows before the first "
            f"and after the last: {'; '.join(grew)}). Capacity can fall as a "
            "study collects data, so these results hold for about this much "
            "data; see 'Database size' in the PsyNet docs on testing scalability."
        )
    if capacity_result is not None and first_fail is not None:
        differ = _tables_that_differ(
            capacity_result.db_rows_before or {}, first_fail.db_rows_before or {}
        )
        if differ:
            lines.append(
                f"  The {capacity_result.n_bots:,}-bot and {first_fail.n_bots:,}-bot "
                f"tests started with very different amounts of data ({'; '.join(differ)} "
                "rows), so the difference between them may come from the data "
                "rather than the load."
            )
    if (
        capacity_result is not None
        and confirmation is not None
        and _confirmation_exceeded(confirmation, limits)
    ):
        differ = _tables_that_differ(
            capacity_result.db_rows_before or {}, confirmation.db_rows_before or {}
        )
        if differ:
            return lines + [
                f"  The confirmation test started with very different amounts of "
                f"data from the {capacity_result.n_bots:,}-bot test "
                f"({'; '.join(differ)} rows), so its failure may come from the "
                "data the search left. Rerun with --reset-database before "
                "capping lower."
            ]
    if lines and any(r.db_rows_before != results[0].db_rows_before for r in results):
        lines.append(
            "  Rerun with --reset-database to start every test from the same data."
        )
    return lines


def _startup_only_lines(result, limits):
    """Note when ``result`` exceeded the phase limits in its start-up but not its steady state.

    The capacity still counts the start-up, because participants often
    arrive together when a study opens.
    """
    if not (result.startup_phase and result.steady_state_phase):
        return []
    startup = phase_limit_reasons(result.startup_phase, limits)
    steady = phase_limit_reasons(
        result.steady_state_phase, limits, result.oldest_queued_s
    )
    if not startup or steady:
        return []
    return [
        f"  In the {result.n_bots:,}-bot test, the start-up exceeded the limits "
        f"({'; '.join(startup)}) but the steady state kept its response times, "
        "request errors and queue waits within them. The capacity counts the "
        "start-up, because participants often arrive together when a study "
        "opens; if yours will arrive gradually, rerun with --arrival-minutes "
        "to match."
    ]


_RAMP_UP_WARNING_SHARE = 0.25


def _capacity_headline(outcome, first_reasons, limit, *, show_cap=True):
    """Return the capacity summary's first lines: the capacity, and a cap if the server set it.

    Only a server limit sets the capacity, so a first failure that could not
    be tested (``outcome.unmeasured``) or that only had wait timeouts
    (``outcome.waits_only``) leaves it a lower bound, without a cap. Pass
    ``show_cap=False`` when a confirmation test reports the cap instead.
    """
    capacity, passed, first_fail = outcome.capacity, outcome.passed, outcome.first_fail
    unmeasured, waits_only = outcome.unmeasured, outcome.waits_only
    if first_fail is None:
        return [
            f"  Capacity: at least {capacity:,} concurrent bots kept {limit}. "
            "Test more bots to find the limit."
        ]
    n_failed = f"{first_fail.n_bots:,}"
    if capacity is None:
        if unmeasured:
            lines = [
                f"  Capacity unknown: {n_failed} bots could not be tested "
                f"({first_reasons})."
            ]
        else:
            advice = "" if waits_only else "; fix any errors or test fewer bots"
            lines = [
                f"  Even {n_failed} bots did not keep {limit} ({first_reasons}){advice}."
            ]
    else:
        lower_bound = unmeasured or waits_only
        verdict = "could not be tested" if unmeasured else "did not"
        lines = [
            f"  Capacity: {'at least' if lower_bound else 'about'} {capacity:,} "
            f"concurrent bots kept {limit}; {n_failed} {verdict} ({first_reasons})."
        ]
        if show_cap and outcome.cap is not None:
            lines.append(
                f"  Cap concurrent participants at about {outcome.cap:,} "
                f"({CAPACITY_HEADROOM:.0%} of {capacity:,})."
            )
    above_fail = [n for n in passed if capacity is None or n > first_fail.n_bots]
    if above_fail and (capacity is None or not unmeasured):
        also = "" if capacity is None else "also "
        lines.append(
            f"  {max(above_fail):,} bots {also}passed, so the results are "
            "inconsistent; rerun to confirm."
        )
    return lines


def _confirmation_exceeded(result, limits):
    """Return whether a confirmation test measured the server exceeding ``limits``.

    A server that stopped, or a test that recorded no responses, leaves it
    unmeasured, like the test's own limits.
    """
    return any(
        server_limit and reason not in ("server stopped", "no responses recorded")
        for reason, server_limit in capacity_failure_causes(result, limits)
    )


def _confirmation_lines(result, limits):
    """Report whether the confirmation test that ended a capacity search kept the limits.

    Only a test that kept the limits and reached the steady state confirms
    the cap.
    """
    n = result.n_bots
    arriving = (
        f"bots arriving over {result.arrival_minutes:g} min"
        if result.arrival_minutes
        else "bots starting together"
    )
    test = (
        f"the {n:,}-bot confirmation test ({arriving}, "
        f"{result.duration_minutes or 0:g} min long)"
    )
    unconfirmed = (
        f"The search's cap of about {n:,} concurrent participants is unconfirmed."
    )
    causes = capacity_failure_causes(result, limits)
    if not causes:
        if result.first_completion_s is None or not result.steady_state_phase:
            return [
                f"  Not confirmed: {test} kept the limits but never reached the "
                f"steady state, so it only saw the start-up. {unconfirmed}"
            ]
        return [
            f"  Confirmed: {test} kept the same limits. Cap concurrent "
            f"participants at about {n:,}."
        ]
    reasons = "; ".join(reason for reason, _ in causes)
    if not _confirmation_exceeded(result, limits):
        return [
            f"  Not confirmed: {test} could not be tested ({reasons}). {unconfirmed}"
        ]
    lines = [f"  Not confirmed: {test} exceeded the limits ({reasons})."]
    if result.startup_phase and result.steady_state_phase:
        startup = phase_limit_reasons(result.startup_phase, limits)
        steady = phase_limit_reasons(
            result.steady_state_phase, limits, result.oldest_queued_s
        )
        lines.append(
            "  Response times, request errors and queue waits: start-up "
            f"{'; '.join(startup) or 'within the limits'}, steady state "
            f"{'; '.join(steady) or 'within the limits'}."
        )
    else:
        lines.append(
            "  The test reached too little steady state to judge it separately."
        )
    retry = retry_bot_count(result, limits)
    ratio = overshoot(result, limits)
    why = f", as the worst measure reached {ratio:.1f} times its limit" if ratio else ""
    rerun = f"--n-bots {retry} --duration-minutes {result.duration_minutes or 0:g}"
    if result.arrival_minutes:
        rerun += f" --arrival-minutes {result.arrival_minutes:g}"
    lines.append(
        f"  Try capping concurrent participants at about {retry:,}{why}, and "
        f"check it with {rerun}."
    )
    return lines


def format_capacity_summary(results, limits=CapacityLimits(), time_factor=1.0):
    """Describe the capacity that ``results`` imply and suggest a participant cap.

    Returns list[str].
    """
    confirmation = next((r for r in results if r.confirmation), None)
    run_order, results = results, [r for r in results if not r.confirmation]
    if not results:
        return []
    limit = limits.describe(
        include_queue=any(
            queue_wait_p95(r) is not None or r.q_delay_median is not None
            for r in results
        )
    )
    outcome = capacity_outcome(results, limits)
    capacity, first_fail = outcome.capacity, outcome.first_fail
    first_reasons = "; ".join(reason for reason, _ in outcome.first_causes)
    lines = _capacity_headline(
        outcome, first_reasons, limit, show_cap=confirmation is None
    )
    if confirmation is not None:
        lines += _confirmation_lines(confirmation, limits)
    if first_fail is not None:
        lines += _startup_only_lines(first_fail, limits)
    # Advice covers the search's first failing test and the confirmation test.
    advised = [r for r in (first_fail, confirmation) if r is not None]
    advised_reasons = [
        reason for r in advised for reason, _ in capacity_failure_causes(r, limits)
    ]
    if any(wait_timeout_cause(r, limits) for r in advised):
        lines.append(_WAIT_ADVICE)
    if any("async queue" in reason for reason in advised_reasons):
        lines.append(_QUEUE_ADVICE)
    if any(start_rate_limits(r) for r in advised):
        lines.append(_START_RATE_ADVICE)
    if any(tester_lagged(r) for r in advised):
        lines.append(_TESTER_LAG_ADVICE)
    if any(POSTGRES_FULL in (r.bot_error_kinds or {}) for r in run_order):
        lines.append(_POSTGRES_ADVICE)
    capacity_result = next((r for r in results if r.n_bots == capacity), None)
    lines += _database_growth_warnings(
        run_order, capacity_result, first_fail, confirmation, limits
    )
    if capacity is None:
        return lines + [""]
    tolerated = []
    if capacity_result.request_errors:
        tolerated.append(plural(capacity_result.request_errors, "request error"))
    if capacity_result.busy_responses:
        tolerated.append(plural(capacity_result.busy_responses, "busy/stale response"))
    if capacity_result.bot_errors:
        tolerated.append(describe_bot_errors(capacity_result))
    if wait_timeouts := count_wait_timeouts(capacity_result):
        tolerated.append(
            f"{plural(wait_timeouts, 'participant')} failed for waiting too long"
        )
    if tolerated:
        found = " and ".join(filter(None, [", ".join(tolerated[:-1]), tolerated[-1]]))
        lines.append(
            f"  The {capacity:,}-bot test had {found}, within "
            "the limits; check the logs in case they point to a bug."
        )
    other_failures = {
        reason: n
        for reason, n in (capacity_result.failed_reasons or {}).items()
        if reason not in wait_timeout_reasons(capacity_result)
    }
    if other_failures:
        also, why = ("also ", " for other reasons") if wait_timeouts else ("", "")
        lines.append(
            f"  In the {capacity:,}-bot test the experiment {also}failed "
            f"{plural(sum(other_failures.values()), 'participant')}{why} "
            f"({top_counts(other_failures)}). These don't "
            "count against capacity; check that the design expects them."
        )
    ramp_up = capacity_result.ramp_up_s
    test_length = capacity_result.actual_duration
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

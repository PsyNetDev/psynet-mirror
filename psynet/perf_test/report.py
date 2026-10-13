"""Format performance test results for the terminal.

:func:`format_test_results` reports one test, :func:`format_performance_summary`
summarizes the tests of a suite in a table followed by a verdict, and
:func:`format_capacity_summary` gives that verdict alone: where a capacity
search stopped and what to try next.

These are pure functions of saved results and limits from
:mod:`psynet.perf_test.results`; they don't import bots or the database, so
they can format results that were read back from JSON. The wording is what
users read, and tests pin much of it, so change it deliberately.

The summary is rendered with rich into lines of text, so that callers can
log or save it. It is coloured only for a terminal, and rendered wide enough
that no table cell is cut, so that log files stay readable.
"""

import os
import sys
from io import StringIO

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text
from tabulate import tabulate

from psynet.log import bold, error, success, warning
from psynet.perf_test.results import (
    ASYNC_JOB_STAT_KEYS,
    CAPACITY_HEADROOM,
    CORES_FOR_OTHERS,
    MAX_WORKER_UTILIZATION,
    MIN_STEADY_STATE_S,
    PGBOUNCER_FULL,
    POSTGRES_FULL,
    PRIORITIES,
    SATURATED_UTILIZATION,
    CapacityLimits,
    busy_early_finish_cause,
    capacity_failure_causes,
    capacity_outcome,
    connection_limit_kind,
    count_wait_timeouts,
    describe_bot_errors,
    describe_busy_early_finish,
    exceeded_error_limits,
    missing_workers,
    overshoot,
    phase_limit_reasons,
    phase_queue_wait_p95,
    plural,
    queue_wait_p95,
    recommend_workers,
    retry_bot_count,
    start_rate_limits,
    tester_lagged,
    top_counts,
    wait_timeout_cause,
    wait_timeout_reasons,
    worker_utilization,
    workers_falling_behind,
)


def _fmt(value, suffix="", digits=3):
    return f"{value:.{digits}f}{suffix}" if value is not None else "N/A"


def _describe_workers(result):
    """Describe the async worker processes and how many jobs they can run at once."""
    n_workers = result.n_rq_workers
    if n_workers is None:
        return ""
    if n_workers == 0:
        return "no worker processes"
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
        *_async_job_lines(result),
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
    phases = (startup, steady)
    for priority in PRIORITIES:
        if not any(priority in (p.get("queue_waits") or {}) for p in phases):
            continue
        rows.append(
            [
                f"p95 {priority}-priority queue wait",
                *(_fmt(phase_queue_wait_p95(p, priority), "s") for p in phases),
            ]
        )
    if any("low" in (p.get("queue_waits") or {}) for p in phases):
        rows.append(
            [
                "Low-priority jobs queued at the end",
                *(f"{_backlog(p.get('queue_waits'), 'low'):,}" for p in phases),
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


def _backlog(queue_waits, priority):
    """Return how many ``priority`` async jobs ``queue_waits`` says were still queued."""
    return ((queue_waits or {}).get(priority) or {}).get("backlog", 0)


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
        outcome_rows.append(["Bot error before joining", bots_not_in_db])
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
            *_section(f"BOT ERRORS (n={result.bot_errors:,})"),
            "  Every bot that raised an error, including those counted above as "
            "failed by the experiment or as a bot error before joining.",
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
    lines += [
        f"  {describe_busy_early_finish(result, trial_maker_id, detail=True)}."
        for trial_maker_id in result.busy_early_finishes or {}
    ]
    lines.append("")
    return lines


_ASYNC_TABLE_LEGEND = [
    "  Avg/Med/P95/Max — statistics on actual execution time",
    "  CPU Avg — mean CPU time of the job's own thread",
    "  Q Avg/Q Med/Q P95 — statistics on queue delay (time waiting in RQ queue)",
    "  Q Share — avg of per-job queue_delay / (queue_delay + exec_time),",
    "    i.e. avg percentage of total time spent queuing rather than executing",
    "  Colors: yellow = Q Share > 20% and Q P95 > 0.2s (moderate contention)",
    "          red = Q Share > 20% and Q P95 > 0.5s (significant contention)",
    "\n",
]


def _async_job_lines(result):
    """Return the ASYNC JOB TIMES section and any backlog left at the end."""
    worker_info = _describe_workers(result)
    if result.async_job_stats:
        n_procs = sum(ps["count"] for ps in result.async_job_stats)
        worker_info = f", {worker_info}" if worker_info else ""
        proc_rows = [
            [
                ps["trial_maker_id"],
                ps["label"],
                ps.get("priority") or "",
                ps["count"],
                *(_fmt(ps.get(key)) for key in ASYNC_JOB_STAT_KEYS if key != "q_share"),
                _q_share_text(ps["q_share"], ps["q_p95"]),
            ]
            for ps in result.async_job_stats
        ]
        lines = [
            *_section(f"ASYNC JOB TIMES ({n_procs} completed{worker_info})"),
            *_ASYNC_TABLE_LEGEND,
            *_table_lines(
                proc_rows,
                headers=[
                    "Trial Maker",
                    "Label",
                    "Priority",
                    "Count",
                    "Avg (s)",
                    "Med (s)",
                    "P95 (s)",
                    "Max (s)",
                    "CPU Avg (s)",
                    "Q Avg (s)",
                    "Q Med (s)",
                    "Q P95 (s)",
                    "Q Share",
                ],
                indent="    ",
                tablefmt="simple",
                colalign=("left", "left", "left") + ("right",) * 9,
            ),
            "",
        ]
    else:
        worker_info = f" ({worker_info})" if worker_info else ""
        lines = [
            *_section(f"ASYNC JOB TIMES{worker_info}"),
            "  No completed async jobs.",
            "",
        ]
    if missing := _missing_workers_text(result):
        lines += [warning(missing), ""]
    if (utilization := worker_utilization(result)) is not None:
        lines += [
            f"  Worker processes busy in the steady state: {utilization:.0%}.",
            "",
        ]

    for priority in PRIORITIES:
        waits = (result.queue_waits or {}).get(priority) or {}
        if not waits.get("backlog"):
            continue
        text = (
            f"  Still queued when the test ended: {waits['backlog']:,} "
            f"{priority}-priority jobs; the oldest had waited "
            f"{waits['oldest_queued_s']:.1f}s for a worker."
        )
        if priority == "high":
            lines += [warning(text), ""]
        else:
            lines += [
                text + " Participants don't wait for these, so they don't "
                "count against the limits.",
                "",
            ]
    return lines


def _missing_workers_text(result):
    """Warn if fewer async worker processes ran in ``result`` than ``worker_processes`` configures."""
    missing = missing_workers(result)
    if missing is None:
        return None
    running, configured = missing
    return (
        f"  Only {running:,} of the {configured:,} async worker processes that "
        "worker_processes configures were running at the end of the "
        f"{result.n_bots:,}-bot test, so the server had less capacity for async "
        "jobs than configured. Check the server log for worker processes that "
        "failed or hung at start-up, and restart them. (psynet debug local "
        "without --legacy always starts one.)"
    )


def _q_share_text(q_share, q_p95):
    """Format an async job's queue share, colored by how much it queued."""
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


_NOT_MEASURED = (
    "Not measured: uploads over participants' own networks (bots upload from "
    "next to the server), media downloads and bandwidth, the front door (web "
    "proxy or Cloudflare tunnel) and browser rendering. Check these separately "
    "if your study plays or records a lot of media."
)

_PASS = "bright_green"
_FAIL = "bold bright_red"
_UNTESTED = "bright_yellow"
_ALERT = "bright_red"
_WARNING = "bright_yellow"
_HIGHLIGHT_ROW = "on grey15"
_RECOMMENDED = "bold bright_green"
_UNCONFIRMED = "bold bright_yellow"
_QUIET = "dim"
# Wide enough for any summary table, so that rich never cuts a cell; the
# prose isn't wrapped at all.
_RENDER_WIDTH = 1000
# box.SIMPLE_HEAD with an ASCII rule, for output that isn't UTF-8.
_ASCII_SIMPLE_HEAD = box.Box(
    "    \n    \n -- \n    \n    \n    \n    \n    \n", ascii=True
)


def _stdout_encoding():
    return getattr(sys.stdout, "encoding", None) or "utf-8"


class _Capture(StringIO):
    """A text buffer that reports the encoding of standard output, so that rich keeps to it."""

    @property
    def encoding(self):
        return _stdout_encoding()


def _render(renderables, color=None):
    """Render rich ``renderables`` as lines of text.

    Parameters
    ----------
    renderables : list
        Rich renderables, such as :class:`rich.text.Text` and
        :class:`rich.table.Table`; ``None`` prints a blank line.
    color : bool, optional
        Whether to colour the text. By default, only if standard output is a
        terminal. Rich also honours ``NO_COLOR``.

    Returns
    -------
    list[str]
    """
    if color is None:
        color = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    file = _Capture()
    console = Console(
        file=file,
        # Rich ignores the width without a height, falling back to 80 columns
        # on a dumb terminal.
        width=_RENDER_WIDTH,
        height=25,
        force_terminal=color,
        color_system="256" if color else None,
        highlight=False,
        markup=False,
        emoji=False,
        soft_wrap=True,
    )
    for renderable in renderables:
        console.print(*([] if renderable is None else [renderable]))
    return [line.rstrip() for line in file.getvalue().splitlines()]


def _percent(share):
    """Format ``share`` as a percentage with about two significant digits, e.g. ``1.2%`` or ``13%``."""
    percent = share * 100
    if 0 < percent < 0.05:
        return "<0.1%"
    return f"{percent:.1f}%" if percent < 9.95 else f"{percent:.0f}%"


def _count(n, total, alert=False):
    """Format ``n`` of ``total`` for a table cell, e.g. ``7 (1.2%)``, in red if ``alert`` and not zero."""
    if not n:
        return Text("0")
    text = f"{n:,} ({_percent(n / total)})" if total else f"{n:,}"
    return Text(text, style=_ALERT if alert else "")


def _minutes(minutes):
    """Format a length of time, e.g. ``3 min``, ``0.25 min`` or ``1 h 02 min``."""
    if minutes >= 59.5:
        hours, rest = divmod(round(minutes), 60)
        return f"{hours} h {rest:02d} min"
    if minutes >= 9.95:
        return f"{round(minutes)} min"
    return f"{minutes:.2g} min"


def _test_minutes(result):
    """Return how long ``result``'s test was meant to last, in minutes."""
    if result.duration_minutes is not None:
        return result.duration_minutes
    return (result.actual_duration or 0) / 60


def _too_short_to_finish(result):
    """Return whether ``result``'s test was shorter than one session and no bot finished."""
    return (
        not result.bots_succeeded
        and bool(result.session_minutes)
        and _test_minutes(result) < result.session_minutes
    )


def _result_text(result, limits):
    """Return the summary table's verdict on one test: ``pass``, ``FAIL`` or ``untested``."""
    causes = capacity_failure_causes(result, limits)
    if not causes:
        return Text("pass", style=_PASS)
    if any(server_limit for _, server_limit in causes):
        return Text("FAIL", style=_FAIL)
    return Text("untested", style=_UNTESTED)


def _summary_columns(results, limits):
    """Return ``(header, cell)`` for each column of the summary table that ``results`` need.

    ``cell(result)`` returns the cell text. Columns for busy responses,
    participants the experiment failed, busy chains and queue waits only
    appear if a test had them.
    """
    columns = [
        ("Bots", lambda r: f"{r.n_bots:,}"),
        ("Length", lambda r: _minutes(_test_minutes(r))),
        ("Result", lambda r: _result_text(r, limits)),
        ("Req/s", lambda r: _fmt(r.requests_per_sec, digits=1)),
        ("p95\nresponse", lambda r: _fmt(r.p95_response_time, "s")),
        ("Median\nresponse", lambda r: _fmt(r.median_response_time, "s")),
        ("Failed\nrequests", lambda r: _count(r.request_errors, r.key_requests, True)),
    ]
    if any(r.busy_responses for r in results):
        columns.append(
            ("Busy\nresponses", lambda r: _count(r.busy_responses, r.key_requests))
        )
    columns.append(
        ("Failed\nbots", lambda r: _count(r.bot_errors, r.total_bots_started, True))
    )
    if any(r.participants_failed for r in results):
        columns.append(
            (
                "Failed by\nexperiment",
                lambda r: _count(r.participants_failed, r.total_bots_started),
            )
        )
    if any(r.busy_early_finishes for r in results):
        columns.append(
            (
                "Busy\nchains",
                lambda r: _count(_busy_early_finish_count(r), r.total_bots_started),
            )
        )
    for priority in PRIORITIES:
        if any(queue_wait_p95(r, priority) is not None for r in results):
            columns.append(
                (
                    f"{priority.capitalize()}-priority\nqueue p95",
                    lambda r, p=priority: _fmt(queue_wait_p95(r, p), "s"),
                )
            )
    columns.append(
        (
            "Bots\nfinished",
            lambda r: "-" if _too_short_to_finish(r) else f"{r.bots_succeeded:,}",
        )
    )
    return columns


def _summary_table(results, limits, capacity):
    """Return the summary table of ``results``, in the order run, labelling the capacity and check rows."""
    utf = _stdout_encoding().lower().startswith("utf")
    table = Table(
        box=box.SIMPLE_HEAD if utf else _ASCII_SIMPLE_HEAD,
        safe_box=False,
        header_style="bold",
        pad_edge=False,
    )
    columns = _summary_columns(results, limits)
    for header, _ in columns:
        table.add_column(
            header, justify="left" if header == "Result" else "right", no_wrap=True
        )
    table.add_column("", no_wrap=True)
    labelled_capacity = False
    for result in results:
        label = ""
        if result.confirmation:
            label = "check at the cap"
        elif result.n_bots == capacity and not labelled_capacity:
            label, labelled_capacity = "capacity", True
        table.add_row(
            *(cell(result) for _, cell in columns),
            label,
            style=_HIGHLIGHT_ROW if label else None,
        )
    return table


def _checked_limits(results, limits):
    """Describe the limits that apply to ``results``, leaving out those for things no test had."""

    def rate(share):
        return f"{share * 100:g}%"

    checked = [f"p95 response time under {limits.max_p95_s:g} s"]
    if any(
        queue_wait_p95(r) is not None or r.q_delay_median is not None for r in results
    ):
        checked.append(
            f"p95 high-priority queue wait under {limits.max_queue_p95_s:g} s"
        )
    checked.append(f"at most {rate(limits.max_request_error_rate)} of requests failing")
    if any(r.busy_responses for r in results):
        checked.append(
            f"at most {rate(limits.max_busy_response_rate)} of requests answered "
            "busy or stale"
        )
    checked.append(f"at most {rate(limits.max_bot_error_rate)} of bots failing")
    if any(count_wait_timeouts(r) for r in results):
        checked.append(
            f"at most {rate(limits.max_wait_timeout_rate)} of participants failed "
            "for waiting too long"
        )
    if any(r.busy_early_finishes for r in results):
        checked.append(
            f"at most {rate(limits.max_busy_early_finish_rate)} of bots getting "
            "fewer trials because every chain was busy"
        )
    return f"Limits checked: {', '.join(checked)}."


def format_performance_summary(
    results,
    limits=CapacityLimits(),
    time_factor=1.0,
    *,
    label=None,
    elapsed_s=None,
    color=None,
):
    """Summarize the tests of a suite: a table of the tests, then the verdict and notes.

    Parameters
    ----------
    results : list[PerformanceTestResult]
        The tests, in the order they ran.
    limits : CapacityLimits
        The limits that the tests were judged by.
    time_factor : float
        The bots' time factor.
    label : str, optional
        The experiment's label, for the subtitle.
    elapsed_s : float, optional
        How long the suite took, for the subtitle.
    color : bool, optional
        Whether to colour the text; by default, only if standard output is a
        terminal.

    Returns
    -------
    list[str]
    """
    if not results:
        return []
    subtitle = plural(len(results), "test")
    if elapsed_s is not None:
        subtitle += f", {_minutes(elapsed_s / 60)}"
    if label:
        subtitle = f"{label}: {subtitle}"
    measured = [r for r in results if not r.confirmation]
    capacity = capacity_outcome(measured, limits).capacity if measured else None
    renderables = [
        None,
        Text("PERFORMANCE TEST SUMMARY", style="bold"),
        Text(subtitle, style=_QUIET),
        Text(_checked_limits(results, limits), style=_QUIET),
        _summary_table(results, limits, capacity),
    ]
    short = [r.session_minutes for r in results if _too_short_to_finish(r)]
    if short:
        renderables += [
            Text(
                f"  -  The test was shorter than one participant session "
                f"({_minutes(max(short))}), so no bot could finish.",
                style=_QUIET,
            ),
            None,
        ]
    notes = []
    if database_growth := _describe_database_growth(results):
        notes.append(
            f"Database rows from the first test to the last: {database_growth}."
        )
    notes.append(_NOT_MEASURED)
    renderables += _capacity_renderables(results, limits, time_factor, notes)
    return _render(renderables, color)


def _busy_early_finish_count(result):
    """Return how many bots in ``result`` got fewer trials because every chain was busy, over all trial makers."""
    return sum(
        stats["participants"] for stats in (result.busy_early_finishes or {}).values()
    )


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
_PGBOUNCER_ADVICE = (
    "  PgBouncer, which passes the app's database connections on to "
    "PostgreSQL, refused new connections because it already had "
    "max_client_conn clients ('no more connections allowed "
    "(max_client_conn)'). Its clients are the connections that the web "
    "server's workers, the async workers and the bots open, and a web "
    "worker keeps the connections it has opened, so their number rises with "
    "the busiest moment so far. HTTP 500 errors in the same tests probably "
    "have this cause too. Raise PgBouncer's max_client_conn (Dallinger PR "
    "#10051 raises it to 2000 for docker-ssh deployments), or bound the "
    "database connection pool, then test again."
)
_WORKER_ADVICE = (
    "Raise the worker_processes config variable (worker dynos on Heroku), or "
    "make the jobs faster. A worker process runs one CPU-heavy job, such as "
    "audio analysis, at a time, so for those also set "
    "worker_greenlets_per_process = 1 and plan on one worker process per CPU "
    "core; see 'Async workers' in the PsyNet docs on testing scalability."
)


def _worker_lines(outcome, confirmation, capacity_result, limits):
    """Return the capacity summary's paragraph on async worker processes, if it applies.

    It appears when high-priority queue waits failed a test, when the workers
    fell behind, or when the measured test ran worker jobs, sized for the cap
    or, without one, for that test's bots.
    """
    first_fail = outcome.first_fail
    queue_bound = next(
        (
            r
            for r in (first_fail, confirmation)
            if r and (queue_wait_p95(r) or 0) > limits.max_queue_p95_s
        ),
        None,
    )
    candidates = [r for r in (confirmation, capacity_result, first_fail) if r]
    if not candidates:
        return []
    measured = next((r for r in candidates if r.steady_state_phase), candidates[0])
    confirmed = _confirmed(confirmation, limits)
    cap = confirmation.n_bots if confirmed else outcome.cap
    n = cap or measured.n_bots
    burst = None
    if queue_bound is not None and queue_bound is first_fail and capacity_result:
        burst = (capacity_result.n_rq_workers, capacity_result.n_bots)
    advice = recommend_workers(measured, n, burst)
    behind = workers_falling_behind(measured)
    ran_jobs = (measured.worker_load or {}).get("jobs")
    if not (queue_bound or behind or (ran_jobs and (cap or not advice.skipped))):
        return []
    text = []
    above_cap = confirmed and queue_bound not in (None, confirmation)
    if queue_bound is not None:
        if queue_bound.n_rq_workers == 0:
            return [
                "High-priority async jobs, which participants wait for, waited "
                "for a worker, but no worker processes were running, so they "
                "couldn't run. Check the server log for workers that failed to "
                "start, and check worker_processes."
            ]
        had = _describe_workers(queue_bound)
        text.append(
            f"In the {queue_bound.n_bots:,}-bot test, jobs that participants wait "
            "for waited too long for " + (f"one of the {had}." if had else "a worker.")
        )
        if above_cap and advice.skipped:
            text.append("To go above the cap, add worker processes.")
    if behind:
        text.append(
            f"During {_describe_test(measured, confirmed)}, {behind}, "
            "so the workers can't keep up in the long run. That doesn't fail the "
            "test by itself, because participants don't wait for low-priority "
            "jobs, but their results arrive later and later and the jobs keep "
            "the workers busy."
        )
    lines = []
    if advice.skipped:
        text.append(f"No estimate of worker_processes: {advice.skipped}.")
        if queue_bound is not None or behind:
            text.append(_WORKER_ADVICE)
    else:
        said_busy = behind and advice.utilization > MAX_WORKER_UTILIZATION
        test = _describe_test(measured, confirmed) if not said_busy else None
        lines = _describe_worker_advice(advice, measured, n, test, above_cap)
    if text:
        lines.insert(0, " ".join(text))
    return [Text(line, style=_WARNING if behind else "") for line in lines]


def _describe_test(result, confirmed):
    """Describe ``result``'s test by what it did, e.g. ``the 96-bot test that confirmed this cap``."""
    test = f"the {result.n_bots:,}-bot test"
    if result.confirmation:
        test += " that confirmed this cap" if confirmed else " that checked this cap"
    return test


def _describe_worker_advice(advice, result, n, test, above_cap):
    """Return the recommended settings in ``advice`` for ``n`` participants at once, and why, as lines.

    ``test`` describes the measured test, or is ``None`` if a warning already
    said how busy its workers were. ``above_cap`` says a larger test failed
    on queue waits above the confirmed cap ``n``. The reason is a sentence on
    what set the number of processes, after one on what the test measured.
    """
    workers, processes = result.n_rq_workers, advice.processes
    ran = f"{workers} worker process{'es' if workers != 1 else ''}"
    if advice.utilization >= SATURATED_UTILIZATION:
        busy = "the whole time"
    else:
        busy = f"{advice.utilization:.0%} of the time"
    were = "were" if workers != 1 else "was"
    measured = [f"In {test}, the {ran} {were} busy {busy}."] if test else []
    implied = f"would be about {advice.implied_utilization:.0%} busy"
    server = (
        f"{result.server_cores}-core server has only {processes} cores left "
        f"after {CORES_FOR_OTHERS} for the web server and database"
    )
    if advice.demand > processes:
        cores = (
            f"{n:,} participants at once would use about {advice.demand} worker "
            f"processes, but the {server}; use a larger server or cheaper jobs."
        )
    else:
        fewer = "fewer than" if processes < workers else "as many as"
        cores = f"The {server}, so this is {fewer} the {ran} the test ran; {processes} {implied}."
    source = advice.per_participant_s and (
        f", and {processes} comes from about {advice.per_participant_s:.0f} s of "
        "worker time per participant"
    )
    why = {
        "estimate": [*measured, f"{processes} worker processes {implied}."],
        "current": [*measured, f"Keep the current {workers}."],
        "behind": [
            *measured,
            f"{processes} is one more than the {ran} that fell behind.",
        ],
        "minimum": [
            f"{processes} is a minimum, not a target: the workers were busy the "
            f"whole time{source or ''}."
        ],
        "cores": [cores],
    }[advice.reason]
    if above_cap and advice.reason != "cores":
        why.append(
            f"To go above {n:,}, raise worker_processes above {processes} and test again."
        )
    note = {"minimum": " (minimum)", "cores": " (all the cores left)"}.get(
        advice.reason, ""
    )
    setting = f"worker_processes {'>=' if advice.reason == 'minimum' else '='} {processes}{note}"
    settings = [setting]
    if advice.greenlets != (result.n_rq_job_slots or 0) // workers:
        settings.append(f"worker_greenlets_per_process = {advice.greenlets}")
    return [
        f"Recommended settings for {n:,} participants at once:",
        *(f"    {line}" for line in settings),
        " ".join(why),
    ]


_WAIT_ADVICE = (
    "  Participants waited too long and the experiment failed them. Design "
    "experiments to avoid this, for example with a longer max_wait_time or "
    "enough participants to fill groups and chains; at high bot counts it can "
    "also mean the server is too slow."
)
_BUSY_CHAINS_ADVICE = (
    "  Participants got fewer trials because every chain they could join was "
    "busy, so the experiment finished their block early. Besides capping "
    "concurrent participants, you can let them wait with "
    "wait_for_networks=True or add chains, which may allow a higher cap. "
    "How participants arrive can make busy chains more or less common, so "
    "judge the cap by the confirmation test of --n-bots auto, whose bots "
    "arrive over a session."
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


def _test_name(result):
    """Name ``result``'s test, e.g. ``120-bot`` or ``96-bot confirmation``."""
    return f"{result.n_bots:,}-bot{' confirmation' if result.confirmation else ''}"


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
    same_start = len(results) > 1 and all(
        r.db_rows_before == results[0].db_rows_before for r in results
    )
    if same_start:
        # The database was reset before each test, so only growth within a
        # test matters.
        grew = [
            f"the {_test_name(r)} test {'; '.join(differ)}"
            for r in results
            if (differ := _tables_that_differ(r.db_rows_before, r.db_rows_after))
        ]
        where = "Every test started from the same data, but some grew it a lot (rows before and after"
    else:
        grew = _tables_that_differ(
            results[0].db_rows_before or {}, results[-1].db_rows_after or {}
        )
        where = "The database grew a lot during these tests (rows before the first and after the last"
    if grew:
        lines.append(
            f"  {where}: {'; '.join(grew)}). Capacity can fall as a "
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
    steady = phase_limit_reasons(result.steady_state_phase, limits)
    if not startup or steady:
        return []
    return [
        f"  In the {result.n_bots:,}-bot test, the start-up exceeded the limits "
        f"({'; '.join(startup)}) but the steady state kept its response times, "
        "request errors and high-priority queue waits within them. The "
        "capacity counts the start-up, because participants often arrive "
        "together when a study opens; if yours will arrive gradually, rerun "
        "with --arrival-minutes to match."
    ]


_RAMP_UP_WARNING_SHARE = 0.25


def _bot_failures(result):
    """Describe how many of ``result``'s bots failed, e.g. ``7 of 570 bots (1.2%) failed``."""
    n, started = result.bot_errors, result.total_bots_started
    if not started:
        return f"{plural(n, 'bot')} failed"
    return f"{n:,} of {started:,} bots ({_percent(n / started)}) failed"


def _reasons(result, causes):
    """Join the reasons in ``causes``, from :func:`capacity_failure_causes` of ``result``.

    Bot errors appear as a share of the bots; :func:`_error_kinds_lines`
    names their kinds.
    """
    bot_errors = describe_bot_errors(result)
    return "; ".join(
        _bot_failures(result) if reason == bot_errors else reason
        for reason, _ in causes
    )


def _error_kinds_lines(result, causes):
    """Name the kinds of ``result``'s bot errors, if too many bots failed, e.g. ``Errors at 560: 5 x HTTP 500 on /response.``"""
    kinds = list((result.bot_error_kinds or {}).items())
    if not kinds or describe_bot_errors(result) not in [r for r, _ in causes]:
        return []
    named = ", ".join(f"{n:,} x {kind}" for kind, n in kinds[:5])
    more = ", ..." if len(kinds) > 5 else ""
    return [f"  Errors at {result.n_bots:,}: {named}{more}."]


def _recommendation(outcome, confirmation, limits):
    """Return the verdict's first line, the recommended participant cap, if there is one.

    A confirmation test that passed confirms its cap, and one that exceeded
    the limits suggests a lower cap to check; without one, the cap is
    :data:`CAPACITY_HEADROOM` of the capacity.
    """
    if confirmation is None:
        if outcome.cap is None:
            return []
        text, style = (
            f"at most {outcome.cap:,} participants at once "
            f"({CAPACITY_HEADROOM:.0%} of {outcome.capacity:,}).",
            _RECOMMENDED,
        )
    elif _confirmed(confirmation, limits):
        text, style = (
            f"at most {confirmation.n_bots:,} participants at once.",
            _RECOMMENDED,
        )
    elif _confirmation_exceeded(confirmation, limits):
        retry = retry_bot_count(confirmation, limits)
        rerun = f"--n-bots {retry} --duration-minutes {confirmation.duration_minutes or 0:g}"
        if confirmation.arrival_minutes:
            rerun += f" --arrival-minutes {confirmation.arrival_minutes:g}"
        text, style = (
            f"try at most {retry:,} participants at once, and check it with {rerun}.",
            _UNCONFIRMED,
        )
    else:
        text, style = (
            f"at most {confirmation.n_bots:,} participants at once, but the check "
            "left this cap unconfirmed.",
            _UNCONFIRMED,
        )
    return [Text(f"Recommended: {text}", style=style)]


def _capacity_lines(outcome, limits):
    """Return the verdict's lines on the capacity: what passed, what failed first and why.

    Only a server limit sets the capacity, so a first failure that could not
    be tested (``outcome.unmeasured``) or that only had wait timeouts
    (``outcome.waits_only``) leaves it a lower bound, without a cap. Busy
    chains do set it, because fewer participants at once keep chains free.
    """
    capacity, passed, first_fail = outcome.capacity, outcome.passed, outcome.first_fail
    unmeasured, waits_only = outcome.unmeasured, outcome.waits_only
    if first_fail is None:
        return [
            f"Capacity: at least {capacity:,} bots at once; no test failed. "
            "Test more bots to find the limit."
        ]
    n_failed = f"{first_fail.n_bots:,}"
    reasons = _reasons(first_fail, outcome.first_causes)
    if capacity is None:
        if unmeasured:
            line = f"Capacity unknown. {n_failed} bots at once could not be tested: {reasons}."
        else:
            if waits_only:
                advice = ""
            elif exceeded_error_limits(first_fail, limits):
                advice = "; fix the errors or test fewer bots"
            else:
                advice = "; test fewer bots"
            line = f"No test passed. {n_failed} bots at once failed: {reasons}{advice}."
    elif unmeasured or waits_only:
        verdict = "could not be tested" if unmeasured else "failed"
        line = (
            f"Capacity: at least {capacity:,} bots at once. "
            f"{n_failed} {verdict}: {reasons}."
        )
    else:
        line = (
            f"Capacity: {capacity:,} bots at once passed. {n_failed} failed: {reasons}."
        )
    lines = [line, *_error_kinds_lines(first_fail, outcome.first_causes)]
    above_fail = [n for n in passed if capacity is None or n > first_fail.n_bots]
    if above_fail and (capacity is None or not unmeasured):
        also = "" if capacity is None else "also "
        lines.append(
            f"  {max(above_fail):,} bots {also}passed, so the results are "
            "inconsistent; rerun to confirm."
        )
    return lines


def _low_priority_lines(result, limits):
    """Report low-priority async jobs of ``result`` that waited longer than the queue limit.

    The limit doesn't apply to them, so this is for information.
    """
    wait = queue_wait_p95(result, "low") if result is not None else None
    if wait is None or wait <= limits.max_queue_p95_s:
        return []
    return [
        f"  Low-priority async jobs in {_describe_test(result, _confirmed(result, limits))}: p95 queue "
        f"wait {wait:.2f} s, {_backlog(result.queue_waits, 'low'):,} still "
        "queued at the end. Participants don't wait for these, so they don't "
        "count against the limits."
    ]


def _confirmation_exceeded(result, limits):
    """Return whether a confirmation test measured the server exceeding ``limits``.

    A server that stopped, or a test that recorded no responses, leaves it
    unmeasured, like the test's own limits.
    """
    return any(
        server_limit and reason not in ("server stopped", "no responses recorded")
        for reason, server_limit in capacity_failure_causes(result, limits)
    )


def _confirmed(result, limits):
    """Return whether ``result``, a confirmation test, kept ``limits`` and reached the steady state."""
    return (
        result is not None
        and not capacity_failure_causes(result, limits)
        and result.first_completion_s is not None
        and bool(result.steady_state_phase)
    )


def _check_lines(result, outcome, limits):
    """Report whether the confirmation test that ended a capacity search kept the limits.

    Only a test that kept the limits and reached the steady state confirms
    the cap.
    """
    n = result.n_bots
    share = ""
    if outcome.capacity and outcome.cap == n:
        share = f" ({CAPACITY_HEADROOM:.0%} of {outcome.capacity:,})"
    arriving = (
        f"arriving over {_minutes(result.arrival_minutes)}"
        if result.arrival_minutes
        else "starting together"
    )
    ran = _minutes(
        result.actual_duration / 60 if result.actual_duration else _test_minutes(result)
    )
    test = f"Check: {n:,} bots{share}, {arriving}, ran for {ran}"
    causes = capacity_failure_causes(result, limits)
    if not causes:
        if not _confirmed(result, limits):
            return [
                f"{test} and kept the limits but never reached the steady "
                "state, so it only saw the start-up."
            ]
        return [f"{test} and passed."]
    reasons = _reasons(result, causes)
    if not _confirmation_exceeded(result, limits):
        return [f"{test} but could not be tested: {reasons}."]
    lines = [f"{test} and failed: {reasons}.", *_error_kinds_lines(result, causes)]
    if result.startup_phase and result.steady_state_phase:
        startup = phase_limit_reasons(result.startup_phase, limits)
        steady = phase_limit_reasons(result.steady_state_phase, limits)
        lines.append(
            "  Response times, request errors and high-priority queue waits: "
            f"start-up {'; '.join(startup) or 'within the limits'}, steady state "
            f"{'; '.join(steady) or 'within the limits'}."
        )
    else:
        lines.append(
            "  The test reached too little steady state to judge it separately."
        )
    if ratio := overshoot(result, limits):
        lines.append(f"  The worst measure reached {ratio:.1f} times its limit.")
    return lines


def _notes(items):
    """Return the summary's notes, ``items`` of text or :class:`~rich.text.Text`, under a heading."""
    if not items:
        return []
    return [
        None,
        Text("Notes", style="bold"),
        *(
            Text.assemble("  - ", item if isinstance(item, Text) else item.strip())
            for item in items
        ),
    ]


def format_capacity_summary(
    results, limits=CapacityLimits(), time_factor=1.0, color=None
):
    """Describe the capacity that ``results`` imply and suggest a participant cap.

    This is the verdict that ends :func:`format_performance_summary`, with
    any worker settings and notes.

    Parameters
    ----------
    results : list[PerformanceTestResult]
        The tests, in the order they ran.
    limits : CapacityLimits
        The limits that the tests were judged by.
    time_factor : float
        The bots' time factor.
    color : bool, optional
        Whether to colour the text; by default, only if standard output is a
        terminal.

    Returns
    -------
    list[str]
    """
    return _render(_capacity_renderables(results, limits, time_factor), color)


def _capacity_renderables(results, limits, time_factor, extra_notes=()):
    """Return the verdict, worker settings and notes of :func:`format_capacity_summary` for rich.

    ``extra_notes`` follow the notes on the capacity. Returns nothing if
    ``results`` has only a confirmation test.
    """
    confirmation = next((r for r in results if r.confirmation), None)
    run_order, results = results, [r for r in results if not r.confirmation]
    if not results:
        return []
    outcome = capacity_outcome(results, limits)
    capacity, first_fail = outcome.capacity, outcome.first_fail
    verdict = _recommendation(outcome, confirmation, limits)
    capacity_lines = [Text(line) for line in _capacity_lines(outcome, limits)]
    if not verdict:
        capacity_lines[0].stylize("bold")
    verdict += capacity_lines
    if confirmation is not None:
        verdict += _check_lines(confirmation, outcome, limits)
    notes = []
    if first_fail is not None:
        notes += _startup_only_lines(first_fail, limits)
    # Advice covers the search's first failing test and the confirmation test.
    advised = [r for r in (first_fail, confirmation) if r is not None]
    if any(wait_timeout_cause(r, limits) for r in advised):
        notes.append(_WAIT_ADVICE)
    if any(busy_early_finish_cause(r, limits) for r in advised):
        notes.append(_BUSY_CHAINS_ADVICE)
    capacity_result = next((r for r in results if r.n_bots == capacity), None)
    workers = _worker_lines(outcome, confirmation, capacity_result, limits)
    if any(start_rate_limits(r) for r in advised):
        notes.append(_START_RATE_ADVICE)
    if any(tester_lagged(r) for r in advised):
        notes.append(_TESTER_LAG_ADVICE)
    if any(POSTGRES_FULL in (r.bot_error_kinds or {}) for r in run_order):
        notes.append(_POSTGRES_ADVICE)
    if any(PGBOUNCER_FULL in (r.bot_error_kinds or {}) for r in run_order):
        notes.append(_PGBOUNCER_ADVICE)
    if missing := next(filter(None, map(_missing_workers_text, run_order)), None):
        notes.append(Text(missing.strip(), style=_WARNING))
    notes += _low_priority_lines(confirmation or capacity_result or first_fail, limits)
    notes += _database_growth_warnings(
        run_order, capacity_result, first_fail, confirmation, limits
    )
    if capacity_result is not None:
        notes += _capacity_test_notes(capacity_result, time_factor)
    renderables = [*(Text(line) if isinstance(line, str) else line for line in verdict)]
    if workers:
        renderables += [None, *workers]
    return renderables + _notes(notes + list(extra_notes)) + [None]


def _capacity_test_notes(capacity_result, time_factor):
    """Return notes on the test that set the capacity: errors within the limits, design failures and a slow start."""
    capacity = capacity_result.n_bots
    notes = []
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
    tolerated += [
        f"{plural(stats['participants'], 'bot')} that got fewer trials in "
        f"{trial_maker_id} because every {stats.get('candidate') or 'chain'} was busy"
        for trial_maker_id, stats in (capacity_result.busy_early_finishes or {}).items()
    ]
    if tolerated:
        found = " and ".join(filter(None, [", ".join(tolerated[:-1]), tolerated[-1]]))
        notes.append(
            f"The {capacity:,}-bot test had {found}, within "
            "the limits; check the logs in case they point to a bug."
        )
    other_failures = {
        reason: n
        for reason, n in (capacity_result.failed_reasons or {}).items()
        if reason not in wait_timeout_reasons(capacity_result)
    }
    if other_failures:
        also, why = ("also ", " for other reasons") if wait_timeouts else ("", "")
        notes.append(
            f"In the {capacity:,}-bot test the experiment {also}failed "
            f"{plural(sum(other_failures.values()), 'participant')}{why} "
            f"({top_counts(other_failures)}). These don't "
            "count against capacity; check that the design expects them."
        )
    ramp_up = capacity_result.ramp_up_s
    test_length = capacity_result.actual_duration
    if (
        ramp_up
        and test_length
        and ramp_up > _RAMP_UP_WARNING_SHARE * test_length
        # Arrivals spread on purpose take long to start.
        and not capacity_result.arrival_minutes
    ):
        notes.append(
            f"Starting all {capacity:,} bots took {ramp_up:.0f} s of the "
            f"{test_length:.0f} s test, so the server ran fully loaded for only "
            f"{1 - ramp_up / test_length:.0%} of it; use a longer "
            "--duration-minutes to confirm the capacity."
        )
    if not time_factor:
        notes.append(
            "These bots ran without pauses (--time-factor 0) and load the server "
            "far more than people do; use --time-factor 1 to size a participant cap."
        )
    return notes


def reset_error_lines(reset_error, n_completed):
    """Explain that resetting the database failed after ``n_completed`` tests and stopped the run.

    Returns list[str].
    """
    lines = [
        error(
            f"  The run stopped early: resetting the database before test "
            f"{n_completed + 1} failed ({reset_error}). The summary above covers "
            f"the {plural(n_completed, 'test')} that completed."
        )
    ]
    if connection_limit_kind(reset_error) == PGBOUNCER_FULL:
        lines.append(
            "  The reset connects through PgBouncer, whose connections the "
            "last test's load had used up."
        )
        lines.append(_PGBOUNCER_ADVICE)
    return lines + [""]


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

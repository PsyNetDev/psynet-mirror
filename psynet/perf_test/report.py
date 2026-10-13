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
import shutil
import sys
from io import StringIO

from rich import box
from rich.console import Console
from rich.padding import Padding
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
    describe_test,
    exceeded_error_limits,
    limit_breaches,
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
        "worker_processes configures were running at the end of "
        f"{describe_test(result)}, so the server could run fewer async jobs "
        "at once than configured. Check the server log for worker processes that "
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
# Prose is this wide when it isn't wrapped, off a terminal.
_UNWRAPPED = 10_000
# box.SIMPLE_HEAD with an ASCII rule, for output that isn't UTF-8; rich's own
# ASCII fallback draws full borders.
_ASCII_SIMPLE_HEAD = box.Box(
    "    \n    \n -- \n    \n    \n    \n    \n    \n", ascii=True
)


def _render(renderables, terminal=None, wrap=True):
    """Render rich ``renderables`` (``None`` for a blank line) as lines of text.

    For a ``terminal`` (by default, if standard output is one), prose wraps
    at its width and is coloured unless ``NO_COLOR`` is set or ``TERM`` is
    ``dumb``; otherwise it is plain and unwrapped. With ``wrap=False``,
    tables keep their natural width, so that no cell is cut.
    """
    if terminal is None:
        terminal = sys.stdout.isatty()
    color = (
        terminal and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
    )
    file = StringIO()
    console = Console(
        file=file,
        width=(
            shutil.get_terminal_size((100, 25)).columns
            if terminal and wrap
            else _UNWRAPPED
        ),
        # Without a height, rich ignores the width on a dumb terminal.
        height=25,
        force_terminal=color,
        color_system="256" if color else None,
        highlight=False,
        markup=False,
        emoji=False,
    )
    if not wrap:
        console.width = max(console.measure(r).maximum for r in renderables)
    for renderable in renderables:
        if isinstance(renderable, (str, Text)):
            renderable = _hanging(
                Text(renderable) if isinstance(renderable, str) else renderable
            )
        console.print(*([] if renderable is None else [renderable]))
    return [line.rstrip() for line in file.getvalue().splitlines()]


def _hanging(text):
    """Indent the wrapped lines of ``text`` as far as its first line is indented."""
    indent = len(text.plain) - len(text.plain.lstrip(" "))
    return Padding(text[indent:], (0, 0, 0, indent), expand=False) if indent else text


def _percent(share):
    """Format ``share`` as a percentage with two significant digits, e.g. ``0.09%``, ``1.2%`` or ``13%``."""
    percent = share * 100
    if 0 < percent < 0.005:
        return "<0.01%"
    if percent < 0.995:
        return f"{percent:.2f}%"
    return f"{percent:.1f}%" if percent < 9.95 else f"{percent:.0f}%"


def _count(n, total, alert=False):
    """Format ``n`` and its share of ``total`` for a table cell, e.g. ``7 (1.2%)``, in red if ``alert`` and not zero."""
    if not n:
        return Text("0")
    return _alert(f"{n:,} ({_percent(n / total)})" if total else f"{n:,}", alert)


def _alert(text, alert):
    """Return ``text`` for a table cell, in red if ``alert``."""
    return Text(text, style=_ALERT if alert else "")


def _ms(seconds):
    """Format a response time in milliseconds, e.g. ``63 ms`` or ``8.5 ms``."""
    if seconds is None:
        return "N/A"
    ms = seconds * 1000
    return f"{ms:.1f} ms" if ms < 9.95 else f"{ms:.0f} ms"


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
    """Return ``pass``, ``FAIL``, or ``untested`` if only the test held it back."""
    causes = capacity_failure_causes(result, limits)
    if not causes:
        return Text("pass", style=_PASS)
    if any(server_limit for _, server_limit in causes):
        return Text("FAIL", style=_FAIL)
    return Text("untested", style=_UNTESTED)


def _measures_seen(results):
    """Return which measures that most tests lack ``results`` had, for the table and limits."""
    seen = {
        "busy": any(r.busy_responses for r in results),
        "experiment": any(r.participants_failed for r in results),
        "chains": any(r.busy_early_finishes for r in results),
        "waits": any(count_wait_timeouts(r) for r in results),
    }
    for priority in PRIORITIES:
        seen[priority] = any(queue_wait_p95(r, priority) is not None for r in results)
    return {name for name, had in seen.items() if had}


def _summary_columns(results, limits):
    """Return ``(header, cell)`` for each column of the summary table that ``results`` need."""
    seen = _measures_seen(results)

    def over(result, measure):
        return any(b.measure == measure for b in limit_breaches(result, limits))

    columns = [
        ("Bots\nat once", lambda r: f"{r.n_bots:,}"),
        ("Bots\nstarted", lambda r: f"{r.total_bots_started:,}"),
        ("Length", lambda r: _minutes(_test_minutes(r))),
        ("Result", lambda r: _result_text(r, limits)),
        ("Req/s", lambda r: _fmt(r.requests_per_sec, digits=1)),
        (
            "p95\nresponse",
            lambda r: _alert(_ms(r.p95_response_time), over(r, "p95")),
        ),
        ("Median\nresponse", lambda r: _ms(r.median_response_time)),
        (
            "Failed\nrequests",
            lambda r: _count(
                r.request_errors, r.key_requests, over(r, "request_errors")
            ),
        ),
    ]
    if "busy" in seen:
        columns.append(
            (
                "Busy\nresponses",
                lambda r: _count(
                    r.busy_responses, r.key_requests, over(r, "busy_responses")
                ),
            )
        )
    columns.append(
        (
            "Failed\nbots",
            lambda r: _count(r.bot_errors, r.total_bots_started, over(r, "bot_errors")),
        )
    )
    if "experiment" in seen:
        columns.append(
            (
                "Failed by\nexperiment",
                lambda r: _count(
                    r.participants_failed,
                    r.total_bots_started,
                    over(r, "wait_timeouts"),
                ),
            )
        )
    if "chains" in seen:
        columns.append(
            (
                "Busy\nchains",
                lambda r: _count(
                    _busy_early_finish_count(r),
                    r.total_bots_started,
                    over(r, "busy_chains"),
                ),
            )
        )
    columns += [
        (
            f"{priority.capitalize()}-priority\nqueue p95",
            lambda r, p=priority: _alert(
                _fmt(queue_wait_p95(r, p), "s"), p == "high" and over(r, "queue")
            ),
        )
        for priority in PRIORITIES
        if priority in seen
    ]
    columns.append(
        (
            "Bots\nfinished",
            lambda r: "-" if _too_short_to_finish(r) else f"{r.bots_succeeded:,}",
        )
    )
    return columns


def _summary_table(results, limits, outcome):
    """Return the table of ``results`` by bot count, validation test last, labelling the capacity and validation rows."""
    utf = (getattr(sys.stdout, "encoding", None) or "utf-8").lower().startswith("utf")
    table = Table(
        box=box.SIMPLE_HEAD if utf else _ASCII_SIMPLE_HEAD,
        safe_box=False,
        header_style="bold",
        padding=(0, 1, 0, 0),
        pad_edge=False,
    )
    columns = _summary_columns(results, limits)
    for header, _ in columns:
        table.add_column(
            header, justify="left" if header == "Result" else "right", no_wrap=True
        )
    table.add_column("", no_wrap=True)
    labelled_capacity = False
    for result in sorted(results, key=lambda r: (r.confirmation, r.n_bots)):
        label = ""
        if result.confirmation:
            label = "validation test"
        elif outcome and result.n_bots == outcome.capacity and not labelled_capacity:
            label, labelled_capacity = "largest passing test", True
        table.add_row(
            *(cell(result) for _, cell in columns),
            label,
            style=_HIGHLIGHT_ROW if label else None,
        )
    return table


def _checked_limits(results, limits):
    """Describe the limits that apply to ``results``, leaving out those for things no test had."""
    seen = _measures_seen(results)

    def rate(share):
        return f"{share * 100:g}%"

    checked = [f"p95 response time under {limits.max_p95_s * 1000:g} ms"]
    if "high" in seen:
        checked.append(
            f"p95 high-priority queue wait under {limits.max_queue_p95_s:g} s"
        )
    checked.append(f"at most {rate(limits.max_request_error_rate)} of requests failing")
    if "busy" in seen:
        checked.append(
            f"at most {rate(limits.max_busy_response_rate)} of requests answered "
            "busy or stale"
        )
    checked.append(f"at most {rate(limits.max_bot_error_rate)} of bots failing")
    if "waits" in seen:
        checked.append(
            f"at most {rate(limits.max_wait_timeout_rate)} of participants failed "
            "for waiting too long"
        )
    if "chains" in seen:
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
    terminal=None,
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
    terminal : bool, optional
        Whether to colour the text and wrap it at the terminal's width, as by
        default when standard output is a terminal.

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
    outcome = capacity_outcome(measured, limits) if measured else None
    head = [
        None,
        Text("PERFORMANCE TEST SUMMARY", style="bold"),
        Text(subtitle, style=_QUIET),
        Text(_checked_limits(results, limits), style=_QUIET),
    ]
    tail = []
    short = [r.session_minutes for r in results if _too_short_to_finish(r)]
    if short:
        tail += [
            Text(
                f"  -  The test was shorter than one participant session "
                f"({_minutes(max(short))}), so no bot could finish.",
                style=_QUIET,
            ),
            None,
        ]
    tail += _capacity_renderables(results, limits, time_factor, [_NOT_MEASURED])
    table = [_summary_table(results, limits, outcome)]
    return (
        _render(head, terminal)
        + _render(table, terminal, wrap=False)
        + _render(tail, terminal)
    )


def _busy_early_finish_count(result):
    """Return how many bots in ``result`` got fewer trials because every chain was busy, over all trial makers."""
    return sum(
        stats["participants"] for stats in (result.busy_early_finishes or {}).values()
    )


_POSTGRES_ADVICE = (
    "Some bots failed because PostgreSQL ran out of connections. The bots "
    "open their own database connections in the processes running them, which "
    "participants don't, so this limits the test rather than the experiment. "
    "Run fewer bots at once, stop other experiments that share the database "
    "server, or raise max_connections."
)
_PGBOUNCER_ADVICE = (
    "PgBouncer, which passes the app's database connections on to "
    "PostgreSQL, refused new connections because it already had "
    "max_client_conn clients ('no more connections allowed "
    "(max_client_conn)'). Its clients are the connections that the web "
    "server's workers, the async workers and the bots open, and a web "
    "worker keeps the connections it has opened, so their number rises with "
    "the busiest moment so far. HTTP 500 errors in the same tests probably "
    "have this cause too. Raise PgBouncer's max_client_conn (Dallinger PR "
    "#10051 raises it to 10,000 for docker-ssh deployments), or bound the "
    "database connection pool, then test again."
)
_WORKER_ADVICE = (
    "Raise worker_processes in config.txt (worker dynos on Heroku), or make "
    "the jobs faster. For CPU-heavy jobs, such as audio analysis, also set "
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
            f"In {describe_test(queue_bound)}, jobs that participants wait "
            "for waited too long for " + (f"one of the {had}." if had else "a worker.")
        )
        if above_cap and advice.skipped:
            text.append(
                "To go above the recommended number of participants, add worker processes."
            )
    if behind:
        text.append(
            f"During {describe_test(measured)}, {behind}, "
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
        test = describe_test(measured) if not said_busy else None
        lines = _describe_worker_advice(advice, measured, n, test, above_cap)
    if text:
        lines.insert(0, " ".join(text))
    return [Text(line, style=_WARNING if behind else "") for line in lines]


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
    # Only the cores keep the count below the test's, so no larger server is needed yet.
    trimmed = advice.demand <= processes < workers
    if advice.demand > processes:
        cores = (
            f"{n:,} participants at once would use about {advice.demand} worker "
            f"processes, but the {server}; use a larger server or cheaper jobs."
        )
    elif trimmed:
        cores = f"The {server}, so this is fewer than the {ran} the test ran; {processes} {implied}."
    else:
        cores = f"The {ran} fell behind, but the {server}; use a larger server or cheaper jobs."
    sources = ["the workers were busy the whole time"] if test else []
    if advice.per_participant_s:
        sources.append(
            f"it comes from about {advice.per_participant_s:.0f} s of worker time "
            "per participant"
        )
    minimum = f"{processes} is a minimum, not a target"
    if sources:
        minimum += ": " + ", and ".join(sources)
    why = {
        "estimate": [*measured, f"{processes} worker processes {implied}."],
        "current": [*measured, f"Keep the current {workers}."],
        "behind": [
            *measured,
            f"{processes} is one more than the {ran} that fell behind.",
        ],
        "minimum": [f"{minimum}."],
        "cores": [cores],
    }[advice.reason]
    if above_cap and not advice.all_cores:
        why.append(
            f"To go above {n:,}, raise worker_processes above {processes} and test again."
        )
    elif above_cap and (advice.reason != "cores" or trimmed):
        why.append(f"To go above {n:,}, use a larger server or cheaper jobs.")
    notes = ["minimum"] * (advice.reason == "minimum")
    notes += ["all the cores left"] * advice.all_cores
    setting = (
        f"worker_processes {'>=' if advice.reason == 'minimum' else '='} {processes}"
    )
    if notes:
        setting += f" ({'; '.join(notes)})"
    settings = [setting]
    if advice.greenlets != (result.n_rq_job_slots or 0) // workers:
        settings.append(f"worker_greenlets_per_process = {advice.greenlets}")
    return [
        f"Recommended settings for {n:,} participants at once:",
        *(f"    {line}" for line in settings),
        " ".join(why),
    ]


_WAIT_ADVICE = (
    "Participants waited too long and the experiment failed them. Design "
    "experiments to avoid this, for example with a longer max_wait_time or "
    "enough participants to fill groups and chains; at high bot counts it can "
    "also mean the server is too slow."
)
_BUSY_CHAINS_ADVICE = (
    "Participants got fewer trials because every chain they could join was "
    "busy, so the experiment finished their block early. Besides recommending "
    "fewer participants at once, you can let them wait with "
    "wait_for_networks=True or add chains, which may allow more participants at once. "
    "How participants arrive can make busy chains more or less common, so "
    "judge the recommended number by the validation test that --n-bots auto "
    "runs, whose bots arrive over a session."
)
_START_RATE_ADVICE = (
    "Bots that cannot start fast enough limit the test rather than the "
    "server, because the processes running the bots create each bot's "
    "participant themselves. Bots that take longer, in a longer experiment or "
    "with a larger --time-factor, give a better measure of the server."
)
_TESTER_LAG_ADVICE = (
    "A process running bots was so busy that its bots ran late and made "
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


def _and(items):
    """Join ``items`` as ``a, b and c``."""
    return " and ".join([", ".join(items[:-1]), items[-1]] if len(items) > 1 else items)


def _tables_that_differ(rows_a, rows_b):
    """Return ``{table: (rows in a, rows in b)}`` for the tables whose row counts differ a lot."""
    differ = {}
    for table in {**rows_a, **rows_b}:
        a, b = rows_a.get(table, 0), rows_b.get(table, 0)
        low, high = sorted((a, b))
        if high - low >= _DB_GROWTH_MIN_ROWS and high >= _DB_GROWTH_RATIO * low:
            differ[table] = (a, b)
    return differ


def _rows_went(differ):
    """Describe ``differ`` from :func:`_tables_that_differ`, e.g. ``trial rows went from 409 to 56,569``."""
    changes = [f"{table} rows from {a:,} to {b:,}" for table, (a, b) in differ.items()]
    return _and([changes[0].replace(" from ", " went from ", 1), *changes[1:]])


def _started_with(result_a, result_b, differ):
    """Say how many rows ``result_a`` and ``result_b`` started with, from :func:`_tables_that_differ`."""
    rows_a = _and([f"{a:,} {table} rows" for table, (a, _) in differ.items()])
    rows_b = _and([f"{b:,}" for _, b in differ.values()])
    joint = "; " if len(differ) > 1 else " and "
    return (
        f"{describe_test(result_a).capitalize()} started with {rows_a}{joint}"
        f"{describe_test(result_b)} with {rows_b}"
    )


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
            f"{describe_test(r).capitalize()} added a lot of data: {_rows_went(differ)}."
            for r in results
            if (differ := _tables_that_differ(r.db_rows_before, r.db_rows_after))
        ]
    else:
        differ = _tables_that_differ(
            results[0].db_rows_before or {}, results[-1].db_rows_after or {}
        )
        grew = differ and [
            f"The database grew a lot during these tests: {_rows_went(differ)}."
        ]
    if grew:
        lines.append(
            " ".join(grew)
            + " The server can handle fewer participants as a study collects data, so "
            "these results hold for a study with about this much data; see "
            "'Database size' in the PsyNet docs on testing scalability."
        )
    if capacity_result is not None and first_fail is not None:
        differ = _tables_that_differ(
            capacity_result.db_rows_before or {}, first_fail.db_rows_before or {}
        )
        if differ:
            lines.append(
                f"{_started_with(capacity_result, first_fail, differ)}, so the "
                "difference between them may come from the data rather than the load."
            )
    if (
        capacity_result is not None
        and confirmation is not None
        and _confirmation_exceeded(confirmation, limits)
    ):
        differ = _tables_that_differ(
            confirmation.db_rows_before or {}, capacity_result.db_rows_before or {}
        )
        if differ:
            return lines + [
                f"{_started_with(confirmation, capacity_result, differ)}, so the "
                "validation test's failure may come from the data the search left. Rerun "
                "with --reset-database before recommending a lower number."
            ]
    if lines and any(r.db_rows_before != results[0].db_rows_before for r in results):
        lines.append(
            "Rerun with --reset-database to start every test from the same data."
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
        f"In the {result.n_bots:,}-bot test, the start-up exceeded the limits "
        f"({'; '.join(startup)}) but the steady state kept its response times, "
        "request errors and high-priority queue waits within them. The "
        "limits apply to the start-up too, because participants often arrive "
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


def _reasons(result, causes, limits):
    """Join the reasons in ``causes``, from :func:`capacity_failure_causes` of ``result``.

    A measured limit is named with its value and limit, e.g. ``the p95
    response time was 900 ms, over the 500 ms limit``. Bot errors appear as
    a share of the bots; :func:`_error_kinds_lines` names their kinds.
    """
    breaches = {b.reason: b for b in limit_breaches(result, limits)}
    return "; ".join(
        _breach_clause(result, breaches[reason]) if reason in breaches else reason
        for reason, _ in causes
    )


def _breach_clause(result, breach):
    """Describe ``breach`` of ``result`` as a clause, with its limit."""
    requests = result.key_requests or 0
    if breach.measure == "bot_errors":
        what = _bot_failures(result)
    elif breach.measure in ("request_errors", "busy_responses") and requests:
        n = (
            result.request_errors
            if breach.measure == "request_errors"
            else result.busy_responses
        )
        how = (
            "failed"
            if breach.measure == "request_errors"
            else "were answered busy or stale"
        )
        what = f"{n:,} of {requests:,} requests ({_percent(n / requests)}) {how}"
    elif breach.measure in ("p95", "queue"):
        name, value, unit = breach.reason.rsplit(" ", 2)
        what = f"the {name} was {value} {unit}"
    else:
        what = breach.reason
    return f"{what}, over the {breach.limit} limit"


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
            f"try at most {retry:,} participants at once, and validate it with {rerun}.",
            _UNCONFIRMED,
        )
    else:
        text, style = (
            f"at most {confirmation.n_bots:,} participants at once, but the validation "
            "test didn't confirm it.",
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
            f"Largest passing test: {capacity:,} bots at once; no test failed, so "
            "the limit wasn't reached. Test more bots to find it."
        ]
    n_failed = f"{first_fail.n_bots:,}"
    reasons = _reasons(first_fail, outcome.first_causes, limits)
    if capacity is None:
        if unmeasured:
            line = f"No limit found. {n_failed} bots at once could not be tested: {reasons}."
        else:
            if waits_only:
                advice = ""
            elif exceeded_error_limits(first_fail, limits):
                advice = "; fix the errors or test fewer bots"
            else:
                advice = "; test fewer bots"
            line = f"No test passed. At {n_failed} bots at once, {reasons}{advice}."
    else:
        passing = f"Largest passing test: {capacity:,} bots at once."
        if unmeasured:
            line = f"{passing} {n_failed} could not be tested: {reasons}, so the limit wasn't found."
        elif waits_only:
            line = f"{passing} At {n_failed}, {reasons}, so the limit wasn't found."
        else:
            line = f"{passing} At {n_failed}, {reasons}."
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
        f"Low-priority async jobs in {describe_test(result)}: p95 queue "
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
    test = f"Validation test: {n:,} bots{share}, {arriving}, ran for {ran}"
    causes = capacity_failure_causes(result, limits)
    if not causes:
        if not _confirmed(result, limits):
            return [
                f"{test} and kept the limits but never reached the steady "
                "state, so it only saw the start-up."
            ]
        return [f"{test} and passed."]
    reasons = _reasons(result, causes, limits)
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
            "  The validation test reached too little steady state to judge it separately."
        )
    if ratio := overshoot(result, limits):
        lines.append(f"  The worst measure reached {ratio:.1f} times its limit.")
    return lines


def _notes(items):
    """Return the summary's notes, text or :class:`~rich.text.Text`, as bullets under a heading."""
    if not items:
        return []
    bullets = Table.grid()
    bullets.add_column(no_wrap=True)
    bullets.add_column()
    for item in items:
        bullets.add_row("  - ", item)
    return [None, Text("Notes", style="bold"), bullets]


def format_capacity_summary(
    results, limits=CapacityLimits(), time_factor=1.0, terminal=None
):
    """Return the verdict, worker settings and notes that end :func:`format_performance_summary`, as lines.

    ``terminal`` is as for :func:`format_performance_summary`.
    """
    return _render(_capacity_renderables(results, limits, time_factor), terminal)


def _capacity_renderables(results, limits, time_factor, extra_notes=()):
    """Return what :func:`format_capacity_summary` renders, with ``extra_notes`` last.

    Returns nothing if ``results`` has only a confirmation test.
    """
    confirmation = next((r for r in results if r.confirmation), None)
    run_order, results = results, [r for r in results if not r.confirmation]
    if not results:
        return []
    outcome = capacity_outcome(results, limits)
    capacity, first_fail = outcome.capacity, outcome.first_fail
    verdict = _recommendation(outcome, confirmation, limits)
    capacity_lines = _capacity_lines(outcome, limits)
    if not verdict:
        capacity_lines[0] = Text(capacity_lines[0], style="bold")
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
        notes += _capacity_test_notes(
            capacity_result, time_factor, _confirmed(confirmation, limits)
        )
    if workers:
        verdict += [None, *workers]
    return verdict + _notes(notes + list(extra_notes)) + [None]


def _capacity_test_notes(capacity_result, time_factor, validated=False):
    """Return notes on the test that set the capacity: errors within the limits, design failures and a slow start.

    A validation test that passed (``validated``) makes the note on a slow start moot.
    """
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
            "count against the limits; check that the design expects them."
        )
    ramp_up = capacity_result.ramp_up_s
    test_length = capacity_result.actual_duration
    if (
        ramp_up
        and test_length
        and ramp_up > _RAMP_UP_WARNING_SHARE * test_length
        # Arrivals spread on purpose take long to start.
        and not capacity_result.arrival_minutes
        and not validated
    ):
        notes.append(
            f"Starting all {capacity:,} bots took {ramp_up:.0f} s of the "
            f"{test_length:.0f} s test, so the server ran fully loaded for only "
            f"{1 - ramp_up / test_length:.0%} of it; use a longer "
            "--duration-minutes to confirm this result."
        )
    if not time_factor:
        notes.append(
            "These bots ran without pauses (--time-factor 0) and load the server "
            "far more than people do; use --time-factor 1 to size the number of participants."
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
        lines.append(f"  {_PGBOUNCER_ADVICE}")
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
        "ssh there; the server's CPU, memory and worker settings decide how "
        "many participants it can handle.",
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

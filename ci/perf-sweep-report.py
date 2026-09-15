#!/usr/bin/env python3
"""Summarise `psynet performance-test` sweep JSON as ASV-style benchmark
metrics.

This script recomputes the current ASV derived metrics for every sweep point, so
a sweep run shows directly what the regression gate would see at each
concurrency level -- which is the number to tune n_bots / duration against.

The derived-metric formulas below MUST stay in sync with the ``track_*`` methods
in ``benchmarks/slow/experiment_performance.py``.

Usage: perf-sweep-report.py <sweep-json> [<sweep-json> ...] Prints a
GitHub-flavoured Markdown table per input file to stdout.
"""

import json
import sys
from pathlib import Path

from tabulate import tabulate

_HEADERS = [
    "n_bots",
    "started",
    "succeeded",
    "failed",
    "incomplete",
    "req/s",
    "p95 (s)",
    "ms/req",
    "s/bot",
    "failure %",
    "incomplete %",
]


def derived_metrics(result):
    """Derived ASV metrics for one sweep result entry.

    Mirrors the ``track_*`` methods in ``benchmarks/slow/experiment_performance.py``;
    keep the two in sync. Unlike the benchmark, a zero request rate yields
    ``None`` (rendered "n/a") here rather than raising -- this is a report.
    """
    completed = result["bots_succeeded"] + result["bots_failed"]
    requests_per_sec = result.get("requests_per_sec")
    return {
        "ms_per_request": 1000.0 / requests_per_sec if requests_per_sec else None,
        "sec_per_bot": result["duration_minutes"] * 60.0 / max(completed, 1),
        "failure_rate": 100.0 * result["bots_failed"] / max(completed, 1),
        "incomplete_rate": (
            100.0 * result["bots_incomplete"] / max(result["total_bots_started"], 1)
        ),
    }


def _fmt(value, spec=".1f"):
    return "n/a" if value is None else format(value, spec)


def _row(result):
    d = derived_metrics(result)
    return [
        result["n_bots"],
        result["total_bots_started"],
        result["bots_succeeded"],
        result["bots_failed"],
        result["bots_incomplete"],
        _fmt(result.get("requests_per_sec"), ".2f"),
        _fmt(result.get("p95_response_time"), ".3f"),
        _fmt(d["ms_per_request"]),
        _fmt(d["sec_per_bot"]),
        _fmt(d["failure_rate"]),
        _fmt(d["incomplete_rate"]),
    ]


def print_report(path):
    with open(path) as handle:
        payload = json.load(handle)

    # Identify each demo by its file's stem -- `experiment_label` is not unique
    # across demos (e.g. static and static_big share one).
    name = Path(path).stem.removeprefix("sweep-")
    print(f"\n### {name}  (`{path}`)\n")
    rows = [_row(result) for result in payload["results"]]
    # `github` tablefmt keeps the artifact (sweep-report.md) valid Markdown;
    # perf_test.py uses `simple` because its output is terminal-only.
    print(tabulate(rows, headers=_HEADERS, tablefmt="github"))
    print()


def main(paths):
    print("# Load sweep — ASV-style derived metrics\n")
    print(
        "Derived columns (ms/req, s/bot, failure %, incomplete %) are what the "
        "`asv_regression` gate compares; the rest are raw `psynet "
        "performance-test` counters. All derived metrics are lower-is-better."
    )
    for path in paths:
        print_report(path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: perf-sweep-report.py <sweep-json> [<sweep-json> ...]")
    main(sys.argv[1:])

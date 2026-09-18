from unittest.mock import Mock, patch

from psynet.perf_test import (
    PerformanceTester,
    colorize_success_rate,
    format_performance_summary,
    format_test_results,
)


def _base_result(**overrides):
    """Minimal valid result dict for format_test_results."""
    result = {
        "n_bots": 2,
        "duration_minutes": 0.1,
        "actual_duration": 6.3,
        "total_bots_started": 2,
        "completed_during_test": 2,
        "bot_errors": 0,
        "bots_succeeded": 2,
        "bots_failed": 0,
        "bots_incomplete": 0,
        "total_requests": 10,
        "successful_requests": 10,
        "request_errors": 0,
        "avg_response_time": 0.05,
        "median_response_time": 0.04,
        "p95_response_time": 0.1,
        "p99_response_time": 0.12,
        "stddev_response_time": 0.02,
        "max_response_time": 0.15,
        "avg_bot_duration": 6.3,
        "avg_init_time": 0.5,
        "requests_per_sec": 1.6,
        "min_trial_count": 3,
        "median_trial_count": 4,
        "max_trial_count": 5,
        "n_succeeded_bots": 2,
        "n_rq_workers": 2,
        "q_delay_median": 0.02,
    }
    result.update(overrides)
    return result


def _join(lines):
    return "\n".join(lines)


def test_random_stagger_is_bounded_relative_to_configured_interval():
    tester = PerformanceTester(
        authenticated_session=Mock(),
        base_url="http://localhost",
        stagger_interval_s=0.1,
    )

    with patch("psynet.perf_test.random.gammavariate", side_effect=[0.6, 0.4]):
        assert tester._bounded_random_stagger() == 0.4


# --- colorize_success_rate ---


def test_colorize_success_rate_100():
    result = colorize_success_rate("100%")
    assert "100%" in result


def test_colorize_success_rate_partial():
    result = colorize_success_rate("50%")
    assert "50%" in result


def test_colorize_success_rate_zero():
    result = colorize_success_rate("0%")
    assert "0%" in result


def test_colorize_success_rate_na():
    assert colorize_success_rate("N/A") == "N/A"


# --- format_test_results ---


def test_format_test_results_basic():
    lines = format_test_results(_base_result())
    text = _join(lines)
    assert "TEST RESULTS" in text
    assert "BOT OUTCOMES" in text
    assert "BOT RUNTIMES" in text
    assert "REQUEST METRICS" in text
    assert "RESPONSE TIMES" in text
    assert "TRIALS PER BOT" in text


def test_format_test_results_none_response_times():
    lines = format_test_results(
        _base_result(
            avg_response_time=None,
            median_response_time=None,
            p95_response_time=None,
            p99_response_time=None,
            stddev_response_time=None,
            max_response_time=None,
            total_requests=0,
        )
    )
    text = _join(lines)
    assert "N/A" in text
    assert "RESPONSE TIMES" in text


def test_format_test_results_bots_not_in_db():
    lines = format_test_results(
        _base_result(
            total_bots_started=5, bots_succeeded=1, bots_failed=1, bots_incomplete=1
        )
    )
    text = _join(lines)
    assert "Never reached DB" in text


def test_format_test_results_no_bots_started():
    lines = format_test_results(
        _base_result(total_bots_started=0, completed_during_test=0)
    )
    text = _join(lines)
    assert "N/A" in text


def test_format_test_results_init_times():
    lines = format_test_results(_base_result(initialization_times=[0.1, 0.2, 0.3, 0.5]))
    text = _join(lines)
    assert "BOT INIT TIMES" in text
    assert "Median" in text
    assert "95th percentile" in text


def test_format_test_results_wait_page_times():
    lines = format_test_results(
        _base_result(
            median_wait_page_time=1.5,
            p95_wait_page_time=3.0,
            max_wait_page_time=5.0,
            n_wait_page_samples=10,
        )
    )
    text = _join(lines)
    assert "WAIT PAGE TIMES" in text


def test_format_test_results_process_stats():
    lines = format_test_results(
        _base_result(
            process_stats=[
                {
                    "trial_maker_id": "tm1",
                    "label": "create_trial",
                    "count": 5,
                    "avg": 0.1,
                    "median": 0.09,
                    "p95": 0.2,
                    "max": 0.3,
                    "q_avg": 0.01,
                    "q_median": 0.015,
                    "q_p95": 0.02,
                    "q_share": 0.05,
                }
            ]
        )
    )
    text = _join(lines)
    assert "ASYNC PROCESS TIMES" in text
    assert "2 workers" in text
    assert "tm1" in text
    assert "create_trial" in text
    assert "Q Med" in text


def test_format_test_results_no_process_stats():
    lines = format_test_results(_base_result(process_stats=None))
    text = _join(lines)
    assert "No completed async processes" in text
    assert "2 workers" in text


def test_format_test_results_returns_list():
    lines = format_test_results(_base_result())
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)


# --- format_performance_summary ---


def test_format_performance_summary_single_result():
    lines = format_performance_summary([_base_result()])
    text = _join(lines)
    assert "CUMULATIVE PERFORMANCE TEST SUMMARY" in text
    assert "Req/s" in text
    assert "1.6" in text
    assert "Resp Med (s)" in text
    assert "0.04" in text


def test_format_performance_summary_none_metrics():
    result = _base_result(
        p95_response_time=None,
        requests_per_sec=None,
    )
    lines = format_performance_summary([result])
    text = _join(lines)
    assert "N/A" in text


def test_format_performance_summary_scaling():
    r1 = _base_result(n_bots=1, median_response_time=0.1, q_delay_median=0.05)
    r2 = _base_result(n_bots=2, median_response_time=0.2, q_delay_median=0.1)
    lines = format_performance_summary([r1, r2])
    text = _join(lines)
    assert "2.0x" in text
    assert "\u2014" in text  # baseline marker


def test_format_performance_summary_returns_list():
    lines = format_performance_summary([_base_result()])
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)


def test_performance_summary_handles_missing_response_metrics():
    """Ported from original mock-based test."""
    result = {
        "n_bots": 2,
        "duration_minutes": 0.1,
        "actual_duration": 6.3,
        "total_bots_started": 1,
        "completed_during_test": 1,
        "bot_errors": 0,
        "bots_succeeded": 1,
        "bots_failed": 0,
        "bots_incomplete": 0,
        "total_requests": 0,
        "successful_requests": 0,
        "request_errors": 0,
        "avg_response_time": None,
        "median_response_time": None,
        "p95_response_time": None,
        "p99_response_time": None,
        "stddev_response_time": None,
        "max_response_time": None,
        "avg_bot_duration": 6.3,
        "avg_init_time": 0.5,
    }
    lines = format_performance_summary([result])
    assert any("N/A" in line for line in lines)


def test_performance_summary_handles_no_completed_or_failed_bots():
    """Ported from original mock-based test."""
    result = {
        "n_bots": 2,
        "duration_minutes": 0.1,
        "actual_duration": 0.8,
        "total_bots_started": 1,
        "completed_during_test": 0,
        "bot_errors": 0,
        "bots_succeeded": 1,
        "bots_failed": 0,
        "bots_incomplete": 0,
        "total_requests": 0,
        "successful_requests": 0,
        "request_errors": 0,
        "avg_response_time": 0.0,
        "median_response_time": None,
        "p95_response_time": 0.0,
        "p99_response_time": None,
        "stddev_response_time": None,
        "max_response_time": None,
        "avg_bot_duration": None,
        "avg_init_time": None,
    }
    lines = format_performance_summary([result])
    assert isinstance(lines, list)


def test_resolve_performance_json_output_prefers_explicit_path(tmp_path, monkeypatch):
    from pathlib import Path

    import click
    import pytest

    from psynet.command_line import resolve_performance_json_output

    assert resolve_performance_json_output("results.json") == "results.json"
    assert resolve_performance_json_output() is None

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "audit.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    resolved = resolve_performance_json_output(audit=True)
    assert (
        Path(resolved).resolve()
        == (audit_dir / "artifacts" / "performance.json").resolve()
    )
    assert (audit_dir / "artifacts").is_dir()

    with pytest.raises(click.UsageError):
        resolve_performance_json_output("results.json", audit=True)


def test_resolve_performance_json_output_requires_manifest(tmp_path, monkeypatch):

    import click
    import pytest

    from psynet.command_line import resolve_performance_json_output

    audit_dir = tmp_path / "attempt"
    audit_dir.mkdir()
    monkeypatch.chdir(audit_dir)
    with pytest.raises(click.UsageError, match="No audit packet found"):
        resolve_performance_json_output(audit=True)


def test_resolve_performance_json_output_autodetects_nested_audit(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from psynet.command_line import resolve_performance_json_output

    experiment = tmp_path / "exp"
    audit_dir = experiment / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(experiment)

    resolved = resolve_performance_json_output(audit=True)
    assert (
        Path(resolved).resolve()
        == (audit_dir / "artifacts" / "performance.json").resolve()
    )

from unittest.mock import Mock, patch

import pytest

from psynet.perf_test import (
    CapacityLimits,
    PerformanceTester,
    capacity_failures,
    colorize_success_rate,
    format_capacity_summary,
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
        "n_rq_job_slots": 40,
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

    with patch.object(tester._random, "gammavariate", side_effect=[0.6, 0.4]):
        assert tester._bounded_random_stagger() == 0.4


def test_monitoring_loop_ends_early_when_server_stops():
    import time

    import requests

    session = Mock()
    session.head.side_effect = requests.ConnectionError()
    tester = PerformanceTester(authenticated_session=session, base_url="http://x")
    bot_state = tester._initialize_bot_tracking()
    start = time.time()

    tester._run_monitoring_loop(1, bot_state, Mock(), start, start + 600)

    assert bot_state["server_stopped"]
    assert time.time() - start < 5


def test_bots_still_taking_the_experiment_stop_when_the_test_ends(monkeypatch):
    import itertools
    import time

    from dallinger import db

    from psynet.participant import ParticipantDriver

    ids = itertools.count(1)

    class FakeDriver(ParticipantDriver):
        def __init__(self):
            self.id = next(ids)

    experiment = Mock()
    experiment.run_bot.side_effect = lambda bot, time_factor: bot._sleep(60)
    monkeypatch.setattr("psynet.bot.BotDriver", FakeDriver)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(db, "session", Mock())
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    bot_state = tester._initialize_bot_tracking()
    start_bot_slot = tester._create_bot_launcher(bot_state, time.time() + 60)

    for _ in range(3):
        start_bot_slot()
    deadline = time.time() + 5
    while len(bot_state["running"]) < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert len(bot_state["running"]) == 3
    tester._stop_bots(bot_state, timeout_s=5)

    assert not any(thread.is_alive() for thread in bot_state["threads"])
    assert [terminated for _, _, terminated in bot_state["bot_durations"]] == [True] * 3
    assert bot_state["total_bot_errors"] == 0


def test_parallel_test_reraises_a_bot_error_after_all_bots_finish(monkeypatch):
    import threading

    import pytest
    from dallinger import db

    from psynet.perf_test import run_parallel_test

    finished = []

    def run_bot(bot, time_factor):
        finished.append(bot)
        if threading.current_thread().name.endswith("-1"):
            pytest.fail("bot failed")

    experiment = Mock(run_bot=run_bot)
    monkeypatch.setattr("psynet.bot.BotDriver", Mock)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(db, "session", Mock())
    check_bots = Mock()

    with pytest.raises(pytest.fail.Exception, match="bot failed"):
        run_parallel_test(
            n_bots=3, time_factor=0, stagger_interval_s=0, check_bots=check_bots
        )

    assert len(finished) == 3
    check_bots.assert_not_called()


@pytest.mark.parametrize(
    "capacity, expected_probes",
    [
        (150, [10, 20, 40, 80, 160, 120, 140, 150]),
        (5, [10, 5, 7, 6]),
    ],
)
def test_capacity_search_brackets_then_bisects(capacity, expected_probes):
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")

    def fake_test(n_bots, bot_log_file):
        p95 = 0.1 if n_bots <= capacity else 0.9
        return _base_result(n_bots=n_bots, p95_response_time=p95, server_stopped=False)

    with (
        patch.object(tester, "_test_performance", side_effect=fake_test),
        patch("psynet.perf_test.time.sleep"),
    ):
        results = tester.find_capacity()

    assert [r["n_bots"] for r in results] == expected_probes


def test_capacity_limits_from_options_keeps_zero_and_defaults_none():
    limits = CapacityLimits.from_options(max_p95_s=0, max_queue_p95_s=None)

    assert limits == CapacityLimits(max_p95_s=0.0)


def test_capacity_summary_suggests_a_cap_below_the_measured_capacity():
    results = [
        _base_result(n_bots=100, p95_response_time=0.2),
        _base_result(n_bots=150, p95_response_time=0.4),
        _base_result(n_bots=200, p95_response_time=0.3, request_errors=3),
    ]

    text = _join(format_capacity_summary(results))

    assert "about 150 concurrent bots" in text
    assert "200 did not (3 request errors)" in text
    assert "Suggested max_concurrent_participants: 120" in text


def test_async_queue_backlog_limits_capacity():
    results = [
        _base_result(n_bots=100, p95_response_time=0.2, q_delay_p95=1.0),
        _base_result(
            n_bots=200, p95_response_time=0.2, q_delay_p95=2.0, oldest_queued_s=40.0
        ),
    ]

    text = _join(format_capacity_summary(results, CapacityLimits(max_queue_p95_s=5)))

    assert "about 100 concurrent bots" in text
    assert "200 did not (p95 async queue wait 40.00 s)" in text


def test_capacity_summary_says_when_no_limit_was_reached():
    results = [_base_result(n_bots=50, p95_response_time=0.1)]

    text = _join(format_capacity_summary(results, time_factor=0))

    assert "at least 50" in text
    assert "Suggested" not in text
    assert "--time-factor 1" in text


def test_capacity_summary_uses_counts_below_the_first_failure():
    results = [
        _base_result(n_bots=10, p95_response_time=0.1),
        _base_result(n_bots=20, p95_response_time=0.1, bot_errors=1),
        _base_result(n_bots=40, p95_response_time=0.1),
    ]

    text = _join(format_capacity_summary(results))

    assert "about 10 concurrent bots" in text
    assert "inconsistent" in text


def test_a_test_whose_bots_did_not_all_start_is_not_within_capacity():
    result = _base_result(n_bots=640, p95_response_time=0.1, slots_started=590)

    assert capacity_failures(result) == [
        "only 590 of 640 bots started (use a longer --duration-minutes)"
    ]


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
    assert "2 worker processes, up to 40 jobs at once" in text
    assert "tm1" in text
    assert "create_trial" in text
    assert "Q Med" in text


def test_format_test_results_no_process_stats():
    lines = format_test_results(_base_result(process_stats=None))
    text = _join(lines)
    assert "No completed async processes" in text
    assert "2 worker processes, up to 40 jobs at once" in text


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

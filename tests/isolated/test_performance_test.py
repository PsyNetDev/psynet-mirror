import os
import re
import sys
from unittest.mock import Mock, patch

import pytest

from psynet.perf_test import (
    CapacityLimits,
    PerformanceSuite,
    PerformanceTester,
    PerformanceTestResult,
    capacity_failures,
    default_duration_minutes,
    format_capacity_summary,
    format_performance_summary,
    format_test_results,
)
from psynet.perf_test.measure import (
    _split_failed_requests,
    async_job_stats,
    phase_stats,
    worker_load,
)
from psynet.perf_test.results import recommend_workers, retry_bot_count
from psynet.perf_test.runtime import _BotState
from psynet.pytest_psynet import path_to_test_experiment


def _base_result(**overrides):
    """Return a minimal valid result for format_test_results."""
    fields = {
        "n_bots": 2,
        "actual_duration": 6.3,
        "total_bots_started": 2,
        "bot_errors": 0,
        "bots_succeeded": 2,
        "bots_failed": 0,
        "bots_incomplete": 0,
        "total_requests": 10,
        "key_requests": 10,
        "request_errors": 0,
        "median_response_time": 0.04,
        "p95_response_time": 0.1,
        "max_response_time": 0.15,
        "avg_bot_duration": 6.3,
        "requests_per_sec": 1.6,
        "min_trial_count": 3,
        "median_trial_count": 4,
        "max_trial_count": 5,
        "n_rq_workers": 2,
        "n_rq_job_slots": 40,
        "q_delay_median": 0.02,
    }
    return PerformanceTestResult(**{**fields, **overrides})


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


def test_bot_pace_factor_is_redrawn_outside_its_bounds():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")

    with patch.object(tester._random, "lognormvariate", side_effect=[0.2, 5, 1.4]):
        assert tester._bounded_random_multiplier() == 1.4


def test_bot_pace_factor_averages_one():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    tester._random.seed(0)

    factors = [tester._bounded_random_multiplier() for _ in range(20000)]

    assert sum(factors) / len(factors) == pytest.approx(1, abs=0.01)


def test_monitoring_loop_ends_early_when_server_stops():
    import time

    import requests

    session = Mock()
    session.head.side_effect = requests.ConnectionError()
    tester = PerformanceTester(authenticated_session=session, base_url="http://x")
    bot_state = _BotState()
    start = time.time()

    tester._run_monitoring_loop(1, bot_state, Mock(), start, start + 600)

    assert bot_state.server_stopped
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
    bot_state = _BotState()
    tester._bots.begin_test(bot_state, time.time() + 60, 3)

    for _ in range(3):
        tester._bots.start_slot()
    deadline = time.time() + 5
    while len(bot_state.running) < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert len(bot_state.running) == 3
    tester._stop_bots(bot_state, timeout_s=5)

    assert not any(thread.is_alive() for thread in tester._bots._threads)
    assert [terminated for _, _, terminated in bot_state.bot_durations] == [True] * 3
    assert bot_state.total_bot_errors == 0


def test_bots_that_fail_count_as_started_and_errored(monkeypatch):
    import itertools
    import time

    import requests
    from dallinger import db

    from psynet.participant import ParticipantDriver

    ids = itertools.count(1)

    class FakeDriver(ParticipantDriver):
        def __init__(self):
            self.id = next(ids)
            if self.id == 1:
                raise RuntimeError("500 Server Error")

    response = requests.Response()
    response.status_code = 500
    response.url = "http://localhost:5000/participant_status/7194"
    experiment = Mock()
    experiment.run_bot.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr("psynet.bot.BotDriver", FakeDriver)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(db, "session", Mock())
    tester = PerformanceTester(
        authenticated_session=Mock(), base_url="http://x", stagger_interval_s=0
    )
    bot_state = _BotState()
    tester._bots.begin_test(bot_state, time.time() + 0.2, 1)
    tester._bots.start_slot()
    time.sleep(0.4)
    tester._stop_bots(bot_state, timeout_s=5)

    assert bot_state.total_bots_started == bot_state.total_bot_errors >= 2
    assert 1 not in bot_state.errored_bot_ids
    assert 2 in bot_state.errored_bot_ids
    kinds = bot_state.bot_error_kinds
    assert kinds["RuntimeError"] == 1
    assert kinds["HTTP 500 on /participant_status"] == bot_state.total_bot_errors - 1


def test_bot_processes_report_their_bots_to_the_parent(monkeypatch):
    """Runs the bot-process protocol with threads standing in for processes."""
    import itertools
    import queue
    import threading
    import time
    from types import SimpleNamespace

    from dallinger import db

    from psynet.participant import ParticipantDriver
    from psynet.perf_test.runtime import _serve_bot_commands, _ThreadBots

    ids = itertools.count(1)

    class FakeDriver(ParticipantDriver):
        def __init__(self):
            self.id = next(ids)

    class ThreadProcess(threading.Thread):
        pid = exitcode = None

        def start(self):
            super().start()
            self.pid = self.native_id

    def run_bot_process(index, commands, events, settings):
        events.put((0, "ready", index))
        bots = _ThreadBots(PerformanceTester(None, None, stagger_interval_s=0))
        _serve_bot_commands(bots, index, commands, events)

    experiment = Mock()
    experiment.run_bot.side_effect = lambda bot, time_factor: bot._sleep(60)
    monkeypatch.setattr("psynet.bot.BotDriver", FakeDriver)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(db, "session", Mock())
    monkeypatch.setattr("psynet.perf_test.runtime._fit_redis_pool_to_bots", Mock())
    monkeypatch.setattr("psynet.perf_test.runtime._run_bot_process", run_bot_process)
    monkeypatch.setattr(
        "psynet.perf_test.runtime.multiprocessing.get_context",
        lambda method: SimpleNamespace(Queue=queue.Queue, Process=ThreadProcess),
    )
    tester = PerformanceTester(Mock(), "http://x", bot_processes=2)

    with tester.bot_runner(max_bots=4, bot_log_file=None):
        bot_state = _BotState()
        tester._bots.begin_test(bot_state, time.time() + 60, 4)
        for _ in range(4):
            tester._bots.start_slot()
        deadline = time.time() + 5
        while len(bot_state.running) < 4 and time.time() < deadline:
            time.sleep(0.01)
        assert bot_state.peak_running == bot_state.total_bots_started == 4
        tester._stop_bots(bot_state, timeout_s=5)

    assert [terminated for _, _, terminated in bot_state.bot_durations] == [True] * 4
    assert len(bot_state.process_loads) == 2
    assert bot_state.unreported_bot_processes == []


@pytest.mark.parametrize(
    "requested, max_bots, cpu_count, expected",
    [("auto", 100, 16, 1), ("auto", 2000, 16, 4), ("auto", 2000, 2, 1), (8, 3, 2, 3)],
)
def test_bot_process_count(monkeypatch, requested, max_bots, cpu_count, expected):
    from psynet.perf_test.runtime import _choose_bot_processes

    monkeypatch.setattr("psynet.perf_test.runtime.os.cpu_count", lambda: cpu_count)
    assert _choose_bot_processes(requested, max_bots) == expected


@pytest.mark.parametrize("url", ["http://localhost:5000", None])
def test_bot_errors_without_a_route_are_still_described(url):
    import requests

    from psynet.perf_test.results import describe_bot_error

    response = requests.Response()
    response.status_code = 502
    response.url = url
    assert describe_bot_error(requests.HTTPError(response=response)) == (
        "HTTP 502 on /"
    )


def test_database_connection_limits_are_named_with_advice():
    from psynet.perf_test.results import describe_bot_error

    try:
        try:
            raise Exception("FATAL:  sorry, too many clients already")
        except Exception as cause:
            raise RuntimeError("could not create participant") from cause
    except RuntimeError as err:
        kind = describe_bot_error(err)

    assert kind == "PostgreSQL out of connections"
    results = [
        _base_result(n_bots=10),
        _base_result(n_bots=20, bot_errors=5, bot_error_kinds={kind: 5}),
    ]
    text = _join(format_capacity_summary(results))
    assert "raise max_connections" in text
    # The bots' own connections hit the limit, so the server wasn't measured.
    assert "At 20, the test couldn't measure the server" in text


def test_capacity_summary_names_the_bot_errors():
    results = [
        _base_result(n_bots=10),
        _base_result(
            n_bots=20,
            bot_errors=1,
            bot_error_kinds={"HTTP 500 on /participant_status": 1},
        ),
    ]

    assert (
        "At 20, 1 of 2 bots (50%) failed, over the 1% limit.\n"
        "  Errors at 20: 1 x HTTP 500 on /participant_status."
    ) in _join(format_capacity_summary(results))


def test_status_is_printed_as_plain_lines_when_output_is_not_a_terminal(capsys):
    import time

    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    bot_state = _BotState(bots_failed_during_test=3)

    tester._show_realtime_status(bot_state, time.time(), time.time() + 60, force=True)

    output = capsys.readouterr().out
    assert "Running: 0" in output
    assert "Failed by experiment: 3" in output
    assert "\r" not in output


def test_parallel_test_reraises_a_bot_error_after_all_bots_finish(monkeypatch):
    import threading

    import pytest
    from dallinger import db

    from psynet.experiment import _run_parallel_test

    finished = []

    def run_bot(bot, time_factor):
        finished.append(bot)
        if threading.current_thread().name.endswith("-1"):
            pytest.fail("bot failed")

    experiment = Mock(run_bot=run_bot)
    monkeypatch.setattr("psynet.experiment.BotDriver", Mock)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(db, "session", Mock())
    check_bots = Mock()

    with pytest.raises(pytest.fail.Exception, match="bot failed"):
        _run_parallel_test(
            n_bots=3, time_factor=0, stagger_interval_s=0, check_bots=check_bots
        )

    assert len(finished) == 3
    check_bots.assert_not_called()


def test_a_suite_stops_after_a_bot_process_does_not_report():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    result = _base_result(n_bots=10, server_stopped=False, unreported_bot_processes=[2])
    with (
        patch.object(tester, "run_test", return_value=result),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        assert PerformanceSuite(tester).run([10, 20]) == [result]


def test_a_failed_reset_stops_the_suite_but_keeps_the_completed_tests(caplog):
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    before_test = Mock(side_effect=[None, None, RuntimeError("disk full.")])

    with (
        caplog.at_level("INFO"),
        patch.object(
            tester,
            "run_test",
            side_effect=lambda title, n_bots, *_: _base_result(n_bots=n_bots),
        ),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        suite = PerformanceSuite(tester, before_test=before_test)
        results = suite.run([10, 20, 40])

    assert [r.n_bots for r in results] == [10, 20]
    assert suite.reset_error == "disk full."
    assert "PERFORMANCE TEST SUMMARY" in caplog.text
    assert (
        "The run stopped early: resetting the database before test 3 failed "
        "(disk full). The summary above covers the 2 tests that completed."
    ) in caplog.text
    plain = [m for m in caplog.messages if "PERFORMANCE TEST" in m or "stopped" in m]
    assert len(plain) == 3 and not any("\x1b[" in m for m in plain)


def test_a_test_that_raises_still_prints_the_summary_of_the_earlier_tests(caplog):
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    error = RuntimeError("exit code 1: OperationalError: server closed\nTraceback")
    results = [_base_result(n_bots=10), _base_result(n_bots=20), error]

    with (
        caplog.at_level("INFO"),
        patch.object(tester, "run_test", side_effect=results),
        patch.object(tester, "pause_between_tests"),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
        pytest.raises(RuntimeError, match="server closed"),
    ):
        PerformanceSuite(tester).run([10, 20, 40])

    assert "PERFORMANCE TEST SUMMARY" in caplog.text
    assert (
        "The run stopped early: test 3 failed (exit code 1: OperationalError: "
        "server closed). The summary above covers the 2 tests that completed."
    ) in caplog.text


def test_a_failed_first_reset_stops_the_suite_without_results():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    before_test = Mock(side_effect=RuntimeError("snapshot failed"))

    with patch("psynet.perf_test.runtime.raise_open_file_limit"):
        suite = PerformanceSuite(tester, before_test=before_test)
        assert suite.run([10, 20]) == []
    assert suite.reset_error == "snapshot failed"


def test_a_suite_calls_before_test_before_every_test_instead_of_pausing():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    before_test = Mock()

    with (
        patch.object(
            tester,
            "run_test",
            side_effect=lambda title, n_bots, *_: _base_result(n_bots=n_bots),
        ),
        patch.object(tester, "pause_between_tests") as pause,
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        PerformanceSuite(tester, before_test=before_test).run([10, 20])

    assert before_test.call_count == 2
    pause.assert_not_called()


@pytest.mark.parametrize(
    "session_minutes, minimum, expected",
    [(None, 1, 1), (0, 1, 1), (0.3, 1, 1), (12.1, 1, 19), (40, 1, 30), (40, 45, 45)],
)
def test_default_duration_covers_a_session_and_start_up(
    session_minutes, minimum, expected
):
    assert default_duration_minutes(session_minutes, minimum) == expected


@pytest.mark.parametrize(
    "session_minutes, minimum, expected",
    [(None, 1, 1), (0.3, 1, 1), (3.2, 1, 4), (12, 1, 5), (12, 8, 8)],
)
def test_capacity_search_tests_last_a_session_up_to_five_minutes(
    session_minutes, minimum, expected
):
    assert default_duration_minutes(session_minutes, minimum, search=True) == expected


@pytest.mark.parametrize(
    "session_minutes, expected",
    [(12, (24, 12)), (0.08, (2, 0.1)), (45, (60, 30)), (None, (1, None))],
)
def test_confirmation_test_spreads_arrivals_over_a_session_and_lasts_two(
    session_minutes, expected
):
    from psynet.perf_test.results import confirmation_timing

    assert confirmation_timing(session_minutes, 1) == expected


def _search(tester, fake_test, **kwargs):
    """Run a capacity search whose tests ``fake_test(n_bots, duration, arrival)`` measures."""
    with (
        patch.object(
            tester,
            "run_test",
            side_effect=lambda title, n_bots, bot_log_file, duration_minutes, arrival_minutes: (
                fake_test(n_bots, duration_minutes, arrival_minutes)
            ),
        ),
        patch.object(tester, "pause_between_tests"),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        suite = PerformanceSuite(tester)
        return suite, suite.find_capacity(**kwargs)


def _session_tester(time_factor=1, estimated_duration_minutes=12, **kwargs):
    """Return a tester of a 12-minute study whose search tests last 5 minutes."""
    return PerformanceTester(
        authenticated_session=Mock(),
        base_url="http://x",
        duration_minutes=5,
        time_factor=time_factor,
        estimated_duration_minutes=estimated_duration_minutes,
        **kwargs,
    )


_PHASE = dict(key_requests=100, request_errors=0, p95_response_time=0.1)
# A confirmation test that reached the steady state.
_STEADY = dict(
    first_completion_s=600.0, startup_phase=_PHASE, steady_state_phase=_PHASE
)


def _confirmation_search(caplog, confirmation_overrides, **tester_kwargs):
    """Search a server that handles 150 bots in short tests, then confirm 120."""
    tester = _session_tester(**tester_kwargs)
    arrivals = []

    def fake_test(n_bots, duration_minutes, arrival_minutes):
        arrivals.append(arrival_minutes)
        if duration_minutes > 5:
            return _base_result(n_bots=n_bots, **confirmation_overrides)
        return _base_result(
            n_bots=n_bots, p95_response_time=0.9 if n_bots > 150 else 0.1
        )

    with caplog.at_level("INFO"):
        suite, results = _search(tester, fake_test)
    return suite, results, arrivals


@pytest.mark.parametrize("confirmed", [True, False])
def test_capacity_search_ends_with_a_long_confirmation_test(caplog, confirmed):
    p95 = 0.1 if confirmed else 0.9
    _, results, _ = _confirmation_search(caplog, dict(p95_response_time=p95, **_STEADY))

    confirmation = results[-1]
    assert [r.confirmation for r in results] == [False] * 8 + [True]
    assert (confirmation.n_bots, confirmation.duration_minutes) == (120, 24)
    assert confirmation.arrival_minutes == 12
    assert results[0].duration_minutes == 5 and results[0].session_minutes == 12
    assert "then a 24-min validation test" in caplog.text
    if confirmed:
        assert "Recommended: at most 120 participants at once." in caplog.text
        assert (
            "Validation test: 120 bots (80% of 150), arriving over 12 min"
            in caplog.text
        )
    else:
        assert (
            "and failed: the p95 response time was 900 ms, over the 500 ms limit."
            in caplog.text
        )
        # p95 900 ms is 1.8 times the 500 ms limit: 120 / 1.8 = 66.
        assert "Recommended: try at most 66 participants at once" in caplog.text
    assert "(80% of 150)." not in caplog.text


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({}, "never reached the steady state"),
        (dict(server_stopped=True, **_STEADY), "could not be tested: server stopped."),
        (
            dict(server_stopped=True, p95_response_time=None, **_STEADY),
            "could not be tested: server stopped; no responses recorded.",
        ),
        (
            dict(p95_response_time=None, **_STEADY),
            "could not be tested: no responses recorded.",
        ),
    ],
)
def test_a_confirmation_that_measures_nothing_leaves_the_cap_unconfirmed(
    caplog, overrides, expected
):
    _confirmation_search(caplog, overrides)

    assert expected in caplog.text
    assert (
        "at most 120 participants at once, but the validation test didn't confirm it"
        in caplog.text
    )
    assert "and passed." not in caplog.text and "try at most" not in caplog.text


def test_a_confirmation_that_fails_on_queue_wait_gets_the_queue_advice(caplog):
    _confirmation_search(
        caplog, dict(queue_waits={"high": {"q_delay_p95": 30.0}}, **_STEADY)
    )

    assert (
        "the p95 high-priority async queue wait was 30.00 s, over the 5 s limit"
        in caplog.text
    )
    assert caplog.text.count("waited too long for") == 1
    assert "validation test, jobs that participants wait for waited" in caplog.text


# A capacity search with 10 workers that failed on queue waits at 130 bots.
_QUEUE_SEARCH = [
    _base_result(
        n_bots=n,
        queue_waits={"high": {"q_delay_p95": wait}},
        n_rq_workers=10,
        n_rq_job_slots=10,
    )
    for n, wait in [(120, 2.2), (130, 8.7)]
]


def test_worker_advice_after_a_confirmed_cap_is_for_going_above_it():
    results = [
        *_QUEUE_SEARCH,
        _tapping_result(96, 10, 0.55, confirmation=True, duration_minutes=26),
    ]

    text = _join(format_capacity_summary(results))

    assert "Recommended: at most 96 participants at once." in text
    assert (
        "In the 130-bot test, jobs that participants wait for waited too long "
        "for one of the 10 worker processes.\n"
        "Recommended settings for 96 participants at once:\n"
        "    worker_processes = 10\n"
        "In the 96-bot validation test, the 10 worker processes "
        "were busy 55% of the time. Keep the current 10 (the load needs about "
        "8). To go above 96, raise worker_processes above 10 and test again."
    ) in text


def test_a_failed_confirmation_on_grown_data_suggests_a_reset(caplog):
    _confirmation_search(
        caplog,
        dict(p95_response_time=0.9, db_rows_before={"trial": 50_000}, **_STEADY),
    )

    assert "so its failure may come from the data the search left" in caplog.text
    assert "--reset-database" in caplog.text


@pytest.mark.parametrize(
    "time_factor, estimated, confirm, reason",
    [
        (1, 12, False, "--no-confirm"),
        (0, 12, True, "--time-factor 0"),
        (1, None, True, "the experiment's estimated session length is unknown"),
    ],
)
def test_capacity_search_can_skip_the_confirmation_test(
    caplog, time_factor, estimated, confirm, reason
):
    tester = _session_tester(time_factor, estimated_duration_minutes=estimated)

    def fake_test(n_bots, duration_minutes, arrival_minutes):
        return _base_result(
            n_bots=n_bots, p95_response_time=0.9 if n_bots > 15 else 0.1
        )

    with caplog.at_level("INFO"):
        suite, results = _search(tester, fake_test, confirm=confirm)

    assert not any(r.confirmation for r in results)
    assert suite.confirmation_skipped.startswith(reason)
    assert f"Validation test skipped: {reason}" in caplog.text
    assert "Recommended: at most 12 participants at once" in caplog.text


@pytest.mark.parametrize("duration_minutes, warns", [(3, True), (20, False)])
def test_suite_header_shows_the_estimate_and_warns_about_short_tests(
    caplog, duration_minutes, warns
):
    tester = PerformanceTester(
        authenticated_session=Mock(),
        base_url="http://x",
        duration_minutes=duration_minutes,
        time_factor=1,
        estimated_duration_minutes=13,
    )
    with (
        caplog.at_level("INFO"),
        patch.object(tester, "run_test", return_value=_base_result()),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        PerformanceSuite(tester).run([2])

    assert "Estimated session:    13.0 min" in caplog.text
    assert ("sees mostly the start of the study" in caplog.text) == warns


def test_arrival_minutes_spreads_bot_slots_evenly_over_the_window():
    import time

    tester = PerformanceTester(
        authenticated_session=Mock(),
        base_url="http://x",
        stagger_interval_s=100,
    )
    bot_state = _BotState()
    started = []

    def start_slot():
        started.append(time.time())
        bot_state.first_bot_initialized = True

    start = time.time()
    tester._run_monitoring_loop(4, bot_state, start_slot, start, start + 1, 0.01)

    # The loop can only start a slot late, never early: 0.6 s over 3 gaps.
    assert len(started) == 4
    assert all(t - started[0] >= 0.2 * i - 0.01 for i, t in enumerate(started))


def test_arrival_minutes_starts_a_single_bot_slot():
    import time

    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    bot_state = _BotState()
    start_slot = Mock(
        side_effect=lambda: setattr(bot_state, "first_bot_initialized", True)
    )

    start = time.time()
    tester._run_monitoring_loop(1, bot_state, start_slot, start, start + 0.5, 1)

    start_slot.assert_called_once()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_phase_stats_split_requests_and_queue_waits_at_the_boundary(db_session):
    from datetime import datetime, timedelta

    from dallinger import db

    from psynet.async_job import AsyncJob
    from psynet.experiment import Request

    start = datetime(2026, 10, 12, 12)

    def at(seconds):
        return start + timedelta(seconds=seconds)

    requests = [(1, 2.0, 200), (2, 1.0, 500), (3, 0.5, 503)]
    requests += [(60 + i, 0.1, 200) for i in range(20)]
    for seconds, duration, status_code in requests:
        db.session.add(
            Request(
                creation_time=at(seconds),
                duration=duration,
                status_code=status_code,
                method="POST",
                endpoint="/response",
            )
        )
    # Local jobs have no priority and count as high priority.
    jobs = [(5, 5, "high"), (70, 71, None), (30, 90, "high")]
    jobs += [(10, 100, "low"), (80, 85, "low")]
    jobs = [
        dict(
            time_enqueued=at(enqueued),
            time_started=at(started),
            queue_delay=float(started - enqueued),
            priority=priority,
            finished=True,
            cpu_time=2.0 if priority == "low" else 0.5,
        )
        for enqueued, started, priority in jobs
    ]
    jobs.append(
        dict(
            time_enqueued=at(50),
            time_started=None,
            queue_delay=None,
            priority="low",
            finished=False,
            cpu_time=None,
        )
    )
    db.session.execute(AsyncJob.__table__.insert(), jobs)
    db.session.flush()

    startup, steady = phase_stats(0, 10**9, 0, at(600), boundary=at(60))

    def waits(jobs, p95, backlog=0, oldest=None):
        return dict(jobs=jobs, q_delay_p95=p95, backlog=backlog, oldest_queued_s=oldest)

    assert startup == dict(
        key_requests=3,
        request_errors=1,
        p95_response_time=pytest.approx(1.9),
        # Jobs enqueued before the boundary but started after it count in the
        # steady state, and in the start-up backlog.
        queue_waits={"high": waits(1, 0.0, 1, 30.0), "low": waits(0, None, 2, 50.0)},
    )
    assert steady == dict(
        key_requests=20,
        request_errors=0,
        p95_response_time=0.1,
        queue_waits={
            "high": waits(2, pytest.approx(57.05)),
            "low": waits(2, pytest.approx(85.75), 1, 550.0),
        },
    )
    overall = async_job_stats(0, at(600))
    assert overall["queue_waits"] == {
        "high": waits(3, pytest.approx(54.1)),
        "low": waits(2, pytest.approx(85.75), 1, 550.0),
    }
    assert [
        (s["priority"], s["count"], s["cpu_avg"]) for s in overall["async_job_stats"]
    ] == [("high", 3, 0.5), ("low", 2, 2.0)]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_a_high_priority_job_that_never_started_fails_the_queue_limit(db_session):
    from datetime import datetime, timedelta

    from dallinger import db

    from psynet.async_job import AsyncJob

    ended_at = datetime(2026, 10, 12, 12, 10)
    db.session.execute(
        AsyncJob.__table__.insert(),
        [
            dict(
                time_enqueued=ended_at - timedelta(seconds=waited),
                time_started=None,
                queue_delay=None,
                priority="high",
                failed=cancelled,
                cancelled=cancelled,
            )
            for waited, cancelled in [(40, False), (500, True)]
        ],
    )
    db.session.flush()

    result = PerformanceTestResult(
        p95_response_time=0.1, **async_job_stats(0, ended_at)
    )

    # The cancelled job is not part of the backlog.
    assert result.queue_waits["high"]["backlog"] == 1
    assert capacity_failures(result) == ["p95 high-priority async queue wait 40.00 s"]


def test_report_compares_start_up_and_steady_state():
    phases = dict(
        first_completion_s=200.0,
        actual_duration=600.0,
        startup_phase=dict(
            key_requests=500,
            request_errors=0,
            p95_response_time=0.9,
            queue_waits={"high": {"q_delay_p95": 12.0}, "low": {"backlog": 30}},
        ),
        steady_state_phase=dict(
            key_requests=900,
            request_errors=0,
            p95_response_time=0.1,
            queue_waits={"high": {"q_delay_p95": 1.0}, "low": {"backlog": 4}},
        ),
    )
    report = _join(format_test_results(_base_result(**phases)))
    assert "Start-up: the first 200 s" in report
    assert "p95 high-priority queue wait" in report
    backlog_row = next(
        line for line in report.splitlines() if "Low-priority jobs queued" in line
    )
    assert backlog_row.split()[-2:] == ["30", "4"]

    over = _base_result(n_bots=40, p95_response_time=0.7, **phases)
    summary = _join(format_capacity_summary([over]))
    assert "the start-up exceeded the limits (p95 response time 900 ms" in summary

    no_completion = _join(format_test_results(_base_result()))
    assert "No bot completed the experiment during the test" in no_completion


_HOLD_TIMEOUT = "timeline_hold:wait_while, fail_on_timeout"


@pytest.mark.parametrize(
    "over_capacity",
    [
        {"p95_response_time": 0.9},
        {"failed_reasons": {_HOLD_TIMEOUT: 100}},
        {"busy_early_finishes": {"main_chain": {"participants": 100}}},
    ],
)
@pytest.mark.parametrize(
    "capacity, expected_probes",
    [
        (150, [10, 20, 40, 80, 160, 120, 140, 150]),
        (5, [10, 5, 7, 6]),
    ],
)
def test_capacity_search_brackets_then_bisects(
    capacity, expected_probes, over_capacity
):
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")

    def fake_test(title, n_bots, *_):
        overrides = over_capacity if n_bots > capacity else {}
        return _base_result(n_bots=n_bots, server_stopped=False, **overrides)

    with (
        patch.object(tester, "run_test", side_effect=fake_test),
        patch.object(tester, "pause_between_tests"),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
        patch("psynet.perf_test.runtime._fit_redis_pool_to_bots"),
    ):
        results = PerformanceSuite(tester).find_capacity()

    assert [r.n_bots for r in results] == expected_probes


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("timeline")],
    indirect=True,
)
def test_database_rows_count_new_participants(db_session):
    import uuid

    from dallinger import db

    from psynet.experiment import get_experiment
    from psynet.participant import Participant
    from psynet.perf_test.measure import database_rows

    before = database_rows()
    assert "async_job" in before
    db.session.add(
        Participant(
            experiment=get_experiment(),
            recruiter_id="hotair",
            worker_id=str(uuid.uuid4()),
            hit_id=str(uuid.uuid4()),
            assignment_id=str(uuid.uuid4()),
            mode="debug",
        )
    )
    db.session.flush()

    assert database_rows()["participant"] == before["participant"] + 1


def test_failed_participants_are_classified_by_failed_not_status():
    from types import SimpleNamespace

    from psynet.perf_test.measure import _bot_outcome, _failure_reason

    failed = SimpleNamespace(
        status="approved",
        failed=True,
        failure_tags=[
            "fail_on_timeout",
            "UnsuccessfulEndPage",
            "timeline_hold:barrier:round_3",
        ],
    )
    approved = SimpleNamespace(status="approved", failed=False, failure_tags=[])

    assert _bot_outcome(failed, errored=False) == "failed by the experiment"
    assert _bot_outcome(failed, errored=True) == "failed by the experiment"
    assert _bot_outcome(approved, errored=True) != "failed by the experiment"
    assert _failure_reason(failed) == "timeline_hold:barrier:round_N, fail_on_timeout"


@pytest.mark.parametrize(
    "failed_reasons, expected",
    [
        (
            {_HOLD_TIMEOUT: 139},
            "139 participants failed for waiting too long at timeline_hold:wait_while",
        ),
        (
            {"while_loop:Waiting for trial, fail_on_timeout": 139},
            "139 participants failed for waiting too long at while_loop:Waiting for trial",
        ),
        (
            {_HOLD_TIMEOUT: 100, "sync group below minimum size": 39},
            "139 participants failed for waiting too long at "
            "sync group below minimum size, timeline_hold:wait_while",
        ),
        (
            {"timeout between barriers": 139},
            "139 participants failed for waiting too long at timeout between barriers",
        ),
        ({"sync group below minimum size": 139}, None),
        ({"attention_test_1, performance_check": 139}, None),
    ],
)
def test_only_participants_failed_for_waiting_too_long_limit_capacity(
    failed_reasons, expected
):
    result = _base_result(
        n_bots=150,
        total_bots_started=294,
        bots_succeeded=155,
        participants_failed=139,
        failed_reasons=failed_reasons,
    )

    failures = capacity_failures(result)
    text = _join(format_capacity_summary([result]))

    if expected:
        assert failures == [expected]
        assert f"No test passed. At 150, {expected}, over the 1% limit." in text
        assert "Design experiments to avoid this" in text
    else:
        assert failures == []
        assert "Largest passing test: 150 bots at once; no test failed" in text


@pytest.mark.parametrize(
    "other_limits, capped, larger_passed",
    [
        ({}, False, False),
        ({}, False, True),
        ({"p95_response_time": 0.9}, True, False),
        ({"bot_errors": 5}, True, False),
    ],
)
def test_only_wait_timeouts_alone_leave_capacity_without_a_cap(
    other_limits, capped, larger_passed
):
    results = [
        _base_result(n_bots=10, total_bots_started=20),
        _base_result(
            n_bots=20,
            total_bots_started=40,
            participants_failed=1,
            failed_reasons={_HOLD_TIMEOUT: 1},
            **other_limits,
        ),
    ]
    if larger_passed:
        results.append(_base_result(n_bots=40, total_bots_started=80))

    text = _join(format_capacity_summary(results))

    assert ("Recommended:" in text) == capped
    assert ("(80% of 10)" if capped else "The limit wasn't found.") in text
    assert "Design experiments to avoid this" in text
    assert ("40 bots also passed, so the results are inconsistent" in text) == (
        larger_passed
    )


@pytest.mark.parametrize(
    "failed_reasons, wording",
    [
        ({"performance_check": 3}, "the experiment failed 3 participants (3"),
        (
            {_HOLD_TIMEOUT: 1, "performance_check": 3},
            "the experiment also failed 3 participants for other reasons (3",
        ),
    ],
)
def test_a_passing_test_reports_participants_failed_by_design(failed_reasons, wording):
    result = _base_result(
        n_bots=10, total_bots_started=200, failed_reasons=failed_reasons
    )

    text = _join(format_capacity_summary([result]))

    assert wording in text
    assert "These don't count against the limits" in text


@pytest.mark.parametrize("participants", [1, 23])
def test_participants_who_got_fewer_trials_because_chains_were_busy_limit_capacity(
    participants,
):
    result = _base_result(
        n_bots=150,
        total_bots_started=150,
        busy_early_finishes={
            "main_chain": {
                "participants": participants,
                "median_trials": 41,
                "expected_trials": 60,
                "candidate": "chain",
            }
        },
    )

    report = _join(format_test_results(result))
    summary = _join(format_capacity_summary([result]))

    share = f"{participants / 150:.0%}"
    assert (
        f"{participants} of 150 bots started ({share}) got fewer trials in "
        "main_chain because every chain was busy; median 41 of 60 trials."
    ) in report
    if participants == 1:
        assert capacity_failures(result) == []
        assert "1 bot that got fewer trials in main_chain" in summary
    else:
        assert capacity_failures(result) == [
            "23 of 150 bots started (15%) got fewer trials in main_chain because "
            "every chain was busy"
        ]
        # 23 is 15 times the 1.5 allowed, so a retry goes down to half.
        assert retry_bot_count(result, CapacityLimits()) == 75
        search = _join(
            format_capacity_summary(
                [_base_result(n_bots=100, total_bots_started=100), result]
            )
        )
        assert "Largest passing test: 100 bots at once." in search
        assert "Recommended: at most 80 participants at once" in search
        assert "wait_for_networks=True" in search
        assert (
            "judge the recommended number by the validation test that --n-bots auto"
            in search
        )


@pytest.mark.parametrize(
    "participants, max_rate, passes",
    [(1, 0.01, True), (2, 0.01, False), (2, 0.05, True)],
)
def test_busy_chains_allow_one_bot_and_a_configurable_share(
    participants, max_rate, passes
):
    result = _base_result(
        n_bots=42,
        total_bots_started=55,
        busy_early_finishes={"main_chain": {"participants": participants}},
    )
    limits = CapacityLimits(max_busy_early_finish_rate=max_rate)

    assert (capacity_failures(result, limits) == []) == passes


def test_test_results_show_participants_the_experiment_failed():
    text = _join(
        format_test_results(
            _base_result(
                bots_succeeded=1,
                participants_failed=3,
                failed_reasons={
                    **{f"prescreen_{i}": 2 for i in range(5)},
                    "performance_check": 1,
                    _HOLD_TIMEOUT: 1,
                },
            )
        )
    )

    assert "Failed by the experiment" in text
    assert f"{_HOLD_TIMEOUT} (waited too long)" in text
    assert "Other reasons" in text
    assert "performance_check " not in text


def test_summaries_report_database_growth():
    results = [
        _base_result(
            n_bots=260,
            db_rows_before={"participant": 2_000, "trial": 65_000},
            db_rows_after={"participant": 2_400, "trial": 75_000},
        ),
        _base_result(
            n_bots=320,
            request_errors=5,
            db_rows_before={"participant": 2_400, "trial": 100_000},
            db_rows_after={"participant": 3_000, "trial": 103_000},
        ),
    ]

    text = _join(format_capacity_summary(results))
    assert (
        "The database grew a lot during these tests (trial rows went from "
        "65,000 to 103,000), so later tests ran on more data"
    ) in text
    assert "--reset-database" in text

    results[-1].db_rows_after = {"participant": 2_600, "trial": 80_000}
    assert "database grew" not in _join(format_capacity_summary(results))

    # After --reset-database every test starts from the same data.
    results[-1].db_rows_before = results[0].db_rows_before
    results[-1].db_rows_after = {"participant": 3_000, "trial": 103_000}
    text = _join(format_capacity_summary(results))
    assert (
        "The 320-bot test added a lot of data: trial rows went from 65,000 to "
        "103,000. The server can handle fewer participants"
    ) in text
    assert "--reset-database" not in text


def test_capacity_limits_from_options_keeps_zero_and_defaults_none():
    limits = CapacityLimits.from_options(max_p95_s=0, max_queue_p95_s=None)

    assert limits == CapacityLimits(max_p95_s=0.0)


def test_capacity_summary_mentions_queue_waits_only_with_async_jobs():
    results = [_base_result(n_bots=50, p95_response_time=0.1, q_delay_median=None)]
    assert "queue" not in _join(format_performance_summary(results))

    results[0].queue_waits = {"high": {"q_delay_p95": 0.1}}
    assert "queue wait under" in _join(format_performance_summary(results))


def test_only_high_priority_queue_waits_limit_capacity():
    low = {"q_delay_p95": 90.0, "backlog": 40, "oldest_queued_s": 140.0}
    results = [
        _base_result(
            n_bots=100, queue_waits={"high": {"q_delay_p95": 1.0}, "low": low}
        ),
        _base_result(
            n_bots=200,
            queue_waits={"high": {"q_delay_p95": 2.0, "oldest_queued_s": 40.0}},
        ),
    ]

    text = _join(format_capacity_summary(results, CapacityLimits(max_queue_p95_s=5)))

    assert "Largest passing test: 100 bots at once." in text
    assert "At 200, the p95 high-priority async queue wait was 40.00 s" in text
    assert (
        "Low-priority async jobs in the 100-bot test: p95 queue wait 140.00 s, "
        "40 still queued at the end. Participants don't wait for these"
    ) in text
    assert "can't keep up" not in text


def _phase_backlog(backlog):
    return dict(_PHASE, queue_waits={"low": {"q_delay_p95": 1.0, "backlog": backlog}})


@pytest.mark.parametrize(
    "end, busy, behind",
    [
        (95, 0.5, "the low-priority backlog grew from 2 to 95 jobs"),
        (8, 0.9, "the 2 worker processes were busy 90% of the time"),
        (8, 0.5, None),
    ],
)
def test_workers_falling_behind_warn_but_pass(end, busy, behind):
    result = _tapping_result(
        60,
        2,
        busy,
        startup_phase=_phase_backlog(2),
        steady_state_phase=_phase_backlog(end),
        queue_waits={"low": {"q_delay_p95": 1.0, "backlog": end}},
    )

    text = _join(format_capacity_summary([result]))

    assert capacity_failures(result) == []
    assert "Largest passing test: 60 bots at once" in text
    if behind:
        assert f"{behind}, so the workers can't keep up in the long run" in text
    assert ("can't keep up" in text) == bool(behind)
    # Workers that fell behind need more than the current 2, never fewer.
    assert f"    worker_processes = {3 if behind else 2}" in text


def _tapping_result(n_bots, workers, busy, slots=1, cpu_share=0.9, **overrides):
    """Return a test like tapping's on a 16-core server: 43 s of worker time per 777 s session."""
    fields = dict(
        n_bots=n_bots,
        n_rq_workers=workers,
        n_rq_job_slots=workers * slots,
        server_cores=16,
        avg_succeeded_duration=777.0,
        actual_duration=1800.0,
        first_completion_s=900.0,
        startup_phase=_PHASE,
        steady_state_phase=_PHASE,
        worker_load=dict(
            jobs=500,
            busy_s=busy * workers * 900,
            cpu_share=cpu_share,
            per_participant_s=43.0,
        ),
    )
    return _base_result(**{**fields, **overrides})


# One worker keeps up with about 777 / 43 = 18 participants, so 3 with about 54.
@pytest.mark.parametrize(
    "result, n, expected",
    [
        # The confirmed 96 kept 10 workers 55% busy; 8 would do, but the
        # advice keeps the current 10.
        (
            _tapping_result(96, 10, 0.55),
            96,
            dict(processes=10, demand=8, reason="current"),
        ),
        # Saturated: 60 × 43 / 777 / 0.7 = 4.7 is a minimum.
        (_tapping_result(60, 3, 0.98), 60, dict(processes=5, reason="minimum")),
        # 192 need 16, but 16 cores leave 14.
        (
            _tapping_result(96, 10, 0.55),
            192,
            dict(processes=14, demand=16, reason="cores"),
        ),
        # 1 worker 73% busy needs 0.73 / 0.7 = 1.04, so 2.
        (_tapping_result(10, 1, 0.73), 10, dict(processes=2, reason="estimate")),
        # 2 workers that fell behind with half the load they could take get 3.
        (
            _tapping_result(
                60,
                2,
                0.5,
                startup_phase=_phase_backlog(2),
                steady_state_phase=_phase_backlog(95),
            ),
            60,
            dict(processes=3, demand=2, reason="behind"),
        ),
        # 6 workers on 8 cores already use all the cores left.
        (
            _tapping_result(96, 6, 0.55, server_cores=8),
            96,
            dict(processes=6, reason="current", all_cores=True),
        ),
        # 10 I/O jobs at once in each 20-slot process use 60% of its core.
        (
            _tapping_result(40, 2, 10, slots=20, cpu_share=0.6),
            40,
            dict(processes=2, greenlets=20),
        ),
        (
            _tapping_result(96, 10, 0.55, worker_load={}, steady_state_phase=None),
            96,
            dict(
                skipped="the 96-bot test ran for less than 60 s after its first bot finished"
            ),
        ),
    ],
)
def test_recommend_workers(result, n, expected):
    advice = recommend_workers(result, n)

    assert {key: getattr(advice, key) for key in expected} == expected


@pytest.mark.parametrize(
    "results, present, absent",
    [
        # The 10 current workers exceed the 6 cores left, but the load uses 8.
        (
            [_tapping_result(96, 10, 0.55, server_cores=8)],
            "would use about 8 worker processes, but the 8-core server",
            "about 10",
        ),
        # The load needs 3, but only the cores keep it below the current 10.
        (
            [_tapping_result(96, 10, 0.2, server_cores=8)],
            "so this is fewer than the 10 worker processes the test ran",
            "would use about",
        ),
        # Above a confirmed cap that already uses all the cores left.
        (
            _QUEUE_SEARCH
            + [_tapping_result(96, 10, 0.55, confirmation=True, server_cores=12)],
            "(all the cores left)\nIn the 96-bot validation test, "
            "the 10 worker processes were busy 55% of the time. Keep the current "
            "10 (the load needs about 8). To go above 96, use a larger server or "
            "cheaper jobs.",
            "raise worker_processes above",
        ),
        # Above a confirmed cap where the cores trim the count below the test's.
        (
            _QUEUE_SEARCH
            + [_tapping_result(96, 10, 0.55, confirmation=True, server_cores=10)],
            "8 would be about 69% busy. To go above 96, use a larger server or "
            "cheaper jobs.",
            "raise worker_processes above",
        ),
        # No bot finished in either test, so neither had a steady state.
        (
            [
                _tapping_result(
                    40,
                    2,
                    0.5,
                    first_completion_s=None,
                    startup_phase=None,
                    steady_state_phase=None,
                    worker_load={},
                ),
                _base_result(n_bots=80, queue_waits={"high": {"q_delay_p95": 8.7}}),
            ],
            "No estimate of worker_processes: no bot finished, so there's no "
            "steady state to measure.",
            "40-bot test ran for less than",
        ),
        # A test that failed on response times, whose backlog also grew.
        (
            [
                _tapping_result(
                    60,
                    2,
                    0.5,
                    p95_response_time=0.9,
                    startup_phase=_phase_backlog(2),
                    steady_state_phase=_phase_backlog(95),
                )
            ],
            "That doesn't fail the test by itself",
            "still passes",
        ),
        # 1.5 CPU-heavy jobs running per process means busy all the time.
        (
            [_tapping_result(40, 2, 1.5, slots=20)],
            "worker_greenlets_per_process = 1",
            "150%",
        ),
    ],
)
def test_worker_text_states_what_was_measured(results, present, absent):
    test_lines = [line for r in results for line in format_test_results(r)]
    text = _join(test_lines + format_capacity_summary(results))

    assert present in text and absent not in text


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_worker_load_sums_worker_time_in_the_steady_state(db_session):
    from datetime import datetime, timedelta

    from dallinger import db

    from psynet.async_job import AsyncJob, LocalAsyncJob, WorkerAsyncJob

    start = datetime(2026, 10, 12, 12)

    def at(seconds):
        return start + timedelta(seconds=seconds)

    worker, local = (
        c.__mapper__.polymorphic_identity for c in (WorkerAsyncJob, LocalAsyncJob)
    )
    # (type, started, finished, failed, CPU s); the steady state is 60 s to 100 s.
    jobs = [(worker, 50, 70, None, 18.0), (worker, 80, 90, None, 9.0)]
    jobs += [(worker, 95, None, None, None), (local, 80, 90, None, 1.0)]
    jobs += [(worker, 85, None, 95, None), (worker, None, None, 90, None)]
    db.session.execute(
        AsyncJob.__table__.insert(),
        [
            dict(
                type=job_type,
                time_started=started and at(started),
                time_finished=finished and at(finished),
                time_of_death=failed and at(failed),
                time_taken=finished and float(finished - started),
                cpu_time=cpu,
                finished=finished is not None,
                failed=failed is not None,
            )
            for job_type, started, finished, failed, cpu in jobs
        ],
    )
    db.session.flush()

    # 10 + 10 s of the finished jobs, 5 s still running and 10 s before failing.
    assert worker_load(0, at(100), at(60), outcomes={}) == dict(
        jobs=2, busy_s=35.0, cpu_share=pytest.approx(0.9), per_participant_s=None
    )


def test_fewer_running_workers_than_configured_are_flagged():
    result = _base_result(n_rq_workers=8, configured_worker_processes=10)

    expected = (
        "Only 8 of the 10 async worker processes that worker_processes configures"
    )
    assert expected in _join(format_test_results(result))
    assert expected in _join(format_capacity_summary([result]))

    result.n_rq_workers = 10
    assert "Only" not in _join(format_capacity_summary([result]))


def test_capacity_summary_warns_when_starting_the_bots_took_much_of_the_test():
    results = [_base_result(n_bots=50, actual_duration=60.0, ramp_up_s=30.0)]
    assert (
        "took 30 s of the 60 s test, so the server ran fully loaded for only 50%"
        in _join(format_capacity_summary(results))
    )

    validated = _base_result(n_bots=40, confirmation=True, **_STEADY)
    assert "took" not in _join(format_capacity_summary([*results, validated]))

    results[0].ramp_up_s = 5.0
    assert "took" not in _join(format_capacity_summary(results))

    # Spread arrivals start slowly on purpose.
    results[0].ramp_up_s, results[0].arrival_minutes = 30.0, 0.5
    assert "took" not in _join(format_capacity_summary(results))


def test_monitoring_loop_records_how_long_the_bots_took_to_start():
    import time

    tester = PerformanceTester(
        authenticated_session=Mock(), base_url="http://x", stagger_interval_s=0.01
    )
    bot_state = _BotState()
    bot_state.first_bot_initialized = True
    start = time.time()

    tester._run_monitoring_loop(3, bot_state, Mock(), start, start + 2)

    assert bot_state.slots_started == 3
    assert bot_state.ramp_up_s is not None
    assert 0 <= bot_state.ramp_up_s < 2


def test_raise_open_file_limit_reaches_the_hard_limit_or_65536():
    resource = pytest.importorskip("resource")
    from psynet.perf_test import raise_open_file_limit

    original = resource.getrlimit(resource.RLIMIT_NOFILE)
    soft, hard = original
    if hard == resource.RLIM_INFINITY or soft < 256:
        pytest.skip("needs a finite hard limit")
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))
    try:
        raise_open_file_limit()
        assert resource.getrlimit(resource.RLIMIT_NOFILE) == (min(hard, 65536), hard)
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, original)


@pytest.mark.parametrize("blocking", [False, True])
def test_redis_pool_lets_every_bot_hold_a_connection(monkeypatch, blocking):
    import redis
    from dallinger import db

    server = db.redis_conn.connection_pool.connection_kwargs
    if blocking:
        pool = redis.BlockingConnectionPool(max_connections=2, timeout=0.1, **server)
    else:
        pool = redis.ConnectionPool(max_connections=2, **server)
    monkeypatch.setattr(db, "redis_conn", redis.Redis(connection_pool=pool))
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    with patch.multiple(
        tester,
        _capture_initial_state=Mock(),
        _run_monitoring_loop=Mock(),
        _max_request_id=Mock(),
        _clear_realtime_status=Mock(),
        _calculate_and_report_results=Mock(),
    ):
        tester.run_test("TEST 1/1", 5, None, duration_minutes=0)

    connections = [pool.get_connection() for _ in range(105)]
    for connection in connections:
        pool.release(connection)
    pool.disconnect()


def test_a_test_whose_bots_did_not_all_start_is_not_within_capacity():
    result = _base_result(n_bots=640, p95_response_time=0.1, slots_started=590)

    assert capacity_failures(result) == [
        "only 590 of 640 bots started (use a longer --duration-minutes)"
    ]


def test_a_test_whose_bots_were_never_all_running_is_not_within_capacity():
    result = _base_result(n_bots=1820, slots_started=1820, peak_running=1050)

    assert capacity_failures(result) == [
        "at most 1,050 of 1,820 bots were taking part at once, because new bots "
        "could not start fast enough"
    ]


def test_a_stray_error_is_reported_but_does_not_cap_capacity():
    def result(n, **overrides):
        return _base_result(
            n_bots=n, key_requests=47_000, total_bots_started=3_000, **overrides
        )

    results = [
        result(640, request_errors=1, busy_responses=3, bot_errors=1),
        result(2000, request_errors=60, queue_waits={"high": {"q_delay_p95": 36.9}}),
    ]

    text = _join(format_capacity_summary(results))
    assert "Largest passing test: 640 bots at once." in text
    assert (
        "failed, over the 0.1% limit; the p95 high-priority async queue wait was 36.90 s"
        in text
    )
    assert (
        "The 640-bot test had 1 request error, 3 busy/stale responses and 1 bot error"
        in text
    )
    assert (
        "for one of the 2 worker processes, up to 40 jobs at once. No estimate "
        "of worker_processes: no bot finished, so there's no steady state to "
        "measure. Raise worker_processes in config.txt"
    ) in text
    assert "worker_greenlets_per_process = 1" in text


@pytest.mark.parametrize(
    "planned, advice",
    [
        (
            True,
            "The validation test, which lasts longer than a session, would "
            "measure it; to run it alone, use --n-bots 104 --arrival-minutes 13 "
            "--duration-minutes 26 with your other options.",
        ),
        (
            False,
            "A test longer than a session measures it: --n-bots 104 "
            "--arrival-minutes 13 --duration-minutes 26 with your other options.",
        ),
    ],
)
def test_worker_advice_without_a_steady_state_names_a_longer_test(planned, advice):
    results = [
        _base_result(
            n_bots=n,
            session_minutes=13,
            duration_minutes=4,
            n_rq_workers=10,
            n_rq_job_slots=10,
            queue_waits={"high": {"q_delay_p95": wait}},
        )
        for n, wait in [(130, 4.2), (140, 7.3)]
    ]

    text = _join(format_capacity_summary(results, confirmation_planned=planned))

    assert (
        f"{advice} To go above 104, raise worker_processes above 10 and test again."
        in text
    )
    assert "Raise worker_processes" not in text


def test_long_test_advice_leaves_out_an_arrival_window_too_short_to_round():
    from psynet.perf_test.report import _long_test_text

    result = _base_result(session_minutes=0.04, duration_minutes=1)
    assert "--arrival-minutes" not in _long_test_text(result, 10, False)


def test_queue_advice_says_when_no_worker_processes_ran():
    results = [
        _base_result(n_bots=10),
        _base_result(
            n_bots=20,
            queue_waits={"high": {"q_delay_p95": 36.9}},
            n_rq_workers=0,
            n_rq_job_slots=0,
        ),
    ]

    text = _join(format_capacity_summary(results))
    assert "no worker processes were running, so they couldn't run" in text
    assert "Raise worker_processes" not in text


def test_a_test_whose_bots_ran_late_could_not_be_tested():
    results = [
        _base_result(n_bots=80, p95_response_time=0.085, tester_lag_p95_s=0.01),
        _base_result(
            n_bots=160,
            p95_response_time=0.1,
            tester_lag_p95_s=0.24,
        ),
    ]

    assert capacity_failures(results[1]) == [
        "bots in the test process were running 240 ms late (p95), so they could "
        "not keep pace (use more --bot-processes)"
    ]
    text = _join(format_capacity_summary(results))
    assert "Largest passing test: 80 bots at once" in text
    assert "At 160, the test couldn't measure the server" in text
    assert "Spread the bots over more processes with --bot-processes" in text
    assert "Recommended:" not in text
    details = _join(format_test_results(results[1]))
    assert "240 ms" in details


def test_a_bot_process_that_did_not_report_makes_a_test_untestable():
    results = [_base_result(n_bots=80), _base_result(unreported_bot_processes=[2])]
    assert "bot process(es) 2 did not report" in capacity_failures(results[1])[0]
    assert "the test couldn't measure the server" in _join(
        format_capacity_summary(results)
    )


def test_load_monitor_measures_how_late_threads_run_while_the_lock_is_held():
    import sys
    import time

    from psynet.perf_test.runtime import _LoadMonitor

    monitor = _LoadMonitor()
    time.sleep(0.2)
    switch_interval = sys.getswitchinterval()
    # Keep the interpreter lock in this thread for 0.3 s.
    sys.setswitchinterval(1.0)
    try:
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            pass
    finally:
        sys.setswitchinterval(switch_interval)
    lag_p95_s = monitor.stop()

    assert lag_p95_s > 0.1


def test_bot_processes_ignore_messages_from_an_earlier_test():
    import queue
    import time

    from psynet.perf_test.runtime import _BotProcesses

    bot_processes = object.__new__(_BotProcesses)
    bot_state = _BotState()
    bot_processes._test = (2, bot_state, time.time() + 60)
    bot_processes._events, bot_processes._replies = queue.Queue(), queue.Queue()
    for event in [
        (1, "start", 7),
        (1, "finished", 0, 0.2, 0),
        (2, "start", 8),
        (2, "finished", 0, 0.01, 0),
        None,
    ]:
        bot_processes._events.put(event)

    bot_processes._apply_events()

    assert list(bot_state.running) == [8]
    assert bot_processes._replies.get_nowait() == (2, "finished", 0, 0.01, 0)
    assert bot_processes._replies.empty()


_POSTGRES_BOT_ERRORS = dict(
    bot_errors=40,
    total_bots_started=400,
    bot_error_kinds={"PostgreSQL out of connections": 40},
)


def _bots(n, **overrides):
    return _base_result(**{"n_bots": n, "p95_response_time": 0.1, **overrides})


@pytest.mark.parametrize(
    "results, expected, absent",
    [
        (
            [
                _bots(100),
                _bots(150, p95_response_time=0.4),
                _bots(200, request_errors=3),
            ],
            [
                "Recommended: at most 120 participants at once (80% of 150).",
                "Largest passing test: 150 bots at once. At 200, 3 of 10 requests "
                "(30%) failed, over the 0.1% limit.",
            ],
            [],
        ),
        (
            [_bots(50)],
            ["Largest passing test: 50 bots at once; no test failed"],
            ["Recommended:"],
        ),
        (
            [_bots(10), _bots(20, bot_errors=1), _bots(40)],
            [
                "Largest passing test: 10 bots at once.",
                "40 bots also passed, so the results are inconsistent",
            ],
            [],
        ),
        (
            [_bots(2, bot_errors=1), _bots(4, bot_errors=1)],
            [
                "No test passed. At 2, 1 of 2 bots (50%) failed, over the 1% "
                "limit; fix the errors or test fewer bots."
            ],
            [],
        ),
        (
            [_bots(2, p95_response_time=0.9)],
            [
                "No test passed. At 2, the p95 response time was 900 ms, over "
                "the 500 ms limit; test fewer bots."
            ],
            [],
        ),
        *(
            (
                [_bots(10, bot_errors=1), _bots(n)],
                [
                    "No test passed. At 10, 1 of 2 bots (50%) failed",
                    f"{n} bots passed, so the results are inconsistent",
                ],
                [],
            )
            for n in (20, 10)
        ),
        (
            [_bots(80), _bots(160, slots_started=160, peak_running=140)],
            [
                "Largest passing test: 80 bots at once",
                "At 160, the test couldn't measure the server",
                "limit the test rather than the server",
            ],
            ["Recommended:"],
        ),
        *(
            (
                [_bots(80), _base_result(n_bots=160, **unmeasured)],
                ["Largest passing test: 80 bots at once"],
                ["Recommended:"],
            )
            for unmeasured in [
                dict(peak_running=100, p95_response_time=None, **_POSTGRES_BOT_ERRORS),
                dict(peak_running=160, **_POSTGRES_BOT_ERRORS),
                dict(slots_started=160, peak_running=0),
            ]
        ),
        (
            [_bots(10, **_POSTGRES_BOT_ERRORS)],
            [
                "No test passed. At 10, the test couldn't measure the server: 40 "
                "of 400 bots (10%) failed",
                "The limit wasn't found.",
                "raise max_connections",
            ],
            ["Recommended:", "did not keep"],
        ),
    ],
)
def test_capacity_verdicts(results, expected, absent):
    text = _join(format_capacity_summary(results))
    for line in expected:
        assert line in text
    for line in absent:
        assert line not in text


@pytest.mark.parametrize("time_factor", [0, 2])
def test_capacity_summary_asks_for_realistic_pauses(time_factor):
    text = _join(format_capacity_summary([_bots(50)], time_factor=time_factor))
    assert "use --time-factor 1 to size the number of participants" in text
    assert "--time-factor" not in _join(format_capacity_summary([_bots(50)]))
    assert format_capacity_summary([]) == []


@pytest.mark.parametrize("local", [True, False])
def test_only_a_local_summary_says_the_results_apply_to_this_computer(local):
    text = _join(format_performance_summary([_bots(50)], local=local))
    assert ("only show how the experiment copes on this computer" in text) == local


@pytest.mark.parametrize(
    "server_limit, reason",
    [
        (dict(busy_responses=300), "were answered busy or stale, over the 1% limit"),
        (dict(p95_response_time=0.9), "the p95 response time was 900 ms"),
    ],
)
def test_server_limits_cap_capacity_even_when_bots_started_too_slowly(
    server_limit, reason
):
    results = [
        _base_result(n_bots=80, p95_response_time=0.085),
        _base_result(n_bots=160, peak_running=140, **server_limit),
    ]

    text = _join(format_capacity_summary(results))

    assert "Largest passing test: 80 bots at once." in text
    assert reason in text
    assert "Recommended: at most 64 participants at once" in text


def test_one_error_in_a_short_test_does_not_cap_capacity():
    assert capacity_failures(_base_result(key_requests=700, request_errors=1)) == []
    assert capacity_failures(_base_result(key_requests=700, request_errors=2)) == [
        "2 request errors"
    ]


def test_a_saved_result_reads_back_ignoring_unknown_and_missing_keys():
    import json
    from dataclasses import asdict

    result = _base_result(endpoint_p95={"/response": 0.2})
    saved = json.loads(json.dumps(asdict(result), allow_nan=False))

    assert PerformanceTestResult.from_dict(saved) == result
    read_back = PerformanceTestResult.from_dict({**saved, "removed_metric": 1})
    assert read_back.endpoint_p95 == {"/response": 0.2}
    assert capacity_failures(PerformanceTestResult.from_dict({"n_bots": 4})) == [
        "no responses recorded"
    ]
    assert PerformanceTestResult.from_dict({"bots_succeeded": None}).bots_succeeded == 0
    old = PerformanceTestResult.from_dict(
        {
            k: v
            for k, v in saved.items()
            if k not in ("participants_failed", "failed_reasons", "db_rows_before")
        }
    )
    assert (old.participants_failed, old.failed_reasons, old.db_rows_before) == (
        0,
        {},
        {},
    )


def test_busy_responses_are_not_request_errors():
    assert _split_failed_requests([(503, 4), (409, 1), (500, 2)]) == (2, 5)


def test_a_storm_of_busy_responses_exceeds_capacity():
    assert capacity_failures(_base_result(key_requests=700, busy_responses=10)) == []
    assert capacity_failures(
        _base_result(key_requests=10_000, request_errors=0, busy_responses=300)
    ) == ["300 busy/stale responses"]


def test_each_endpoint_must_stay_within_the_response_time_limit(monkeypatch):
    result = _base_result(
        p95_response_time=0.426,
        endpoint_p95={"/timeline": 0.191, "/response": 0.511},
    )

    assert capacity_failures(result) == ["p95 response time for /response 511 ms"]
    # The overall p95 is within the limit, so its cell isn't red.
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    summary = _join(format_performance_summary([result], terminal=True))
    assert " 426 ms" in summary and "m426 ms" not in summary


# --- format_test_results ---


_ASYNC_JOB_STATS = [
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


@pytest.mark.parametrize(
    "overrides, expected",
    [
        (
            {},
            ["BOT OUTCOMES", "BOT RUNTIMES", "REQUEST METRICS", "TRIALS PER BOT"],
        ),
        (
            dict(
                median_response_time=None,
                p95_response_time=None,
                max_response_time=None,
                total_requests=0,
            ),
            ["RESPONSE TIMES", "N/A"],
        ),
        (
            dict(
                total_bots_started=5, bots_succeeded=1, bots_failed=1, bots_incomplete=1
            ),
            ["Bot error before joining"],
        ),
        (
            dict(median_wait_page_time=1.5, n_wait_page_samples=10),
            ["Median time on wait pages per bot (n=10)"],
        ),
        (
            dict(async_job_stats=_ASYNC_JOB_STATS),
            ["ASYNC JOB TIMES", "tm1", "create_trial", "Q Med"],
        ),
        (dict(async_job_stats=None), ["No completed async jobs"]),
    ],
    ids=["basic", "no-responses", "bots-not-in-db", "wait-pages", "jobs", "no-jobs"],
)
def test_format_test_results(overrides, expected):
    text = _join(format_test_results(_base_result(**overrides)))
    for line in [
        "TEST RESULTS",
        "2 worker processes, up to 40 jobs at once",
        *expected,
    ]:
        assert line in text


# --- format_performance_summary ---


def test_performance_summary_tabulates_the_tests_then_gives_the_verdict(monkeypatch):
    short = dict(duration_minutes=3, session_minutes=11.4, bots_succeeded=0)
    no_jobs = dict(q_delay_median=None)
    results = [
        _base_result(
            n_bots=560,
            total_bots_started=570,
            request_errors=1,
            bot_errors=10,
            bot_error_kinds={"OperationalError": 10},
            **short,
            **no_jobs,
        ),
        _base_result(n_bots=520, total_bots_started=520, **short, **no_jobs),
        _base_result(
            n_bots=416,
            confirmation=True,
            duration_minutes=23,
            actual_duration=1380,
            arrival_minutes=11.4,
            bots_succeeded=433,
            **_STEADY,
            **no_jobs,
        ),
    ]

    lines = format_performance_summary(results, label="rating", elapsed_s=3720)
    text = _join(lines)

    assert "rating: 3 tests, 1 h 02 min" in text
    assert (
        "Limits checked: p95 response time under 500 ms, at most 0.1% of requests "
        "failing, at most 1% of bots failing."
    ) in text
    assert "queue" not in text and "Busy" not in text
    rows = {line.split()[0]: line for line in lines if line.strip()[:1].isdigit()}
    assert list(rows) == ["520", "560", "416"]
    assert " pass " in rows["520"] and rows["520"].endswith(" largest passing")
    assert " FAIL " in rows["560"] and re.search(r"^ +560 +570 ", rows["560"])
    assert "10 (1.8%)" in rows["560"]
    assert rows["416"].endswith(" 433  validation test")
    assert "shorter than one participant session (11 min)" in text
    assert (
        "Recommended: at most 416 participants at once.\n"
        "Largest passing test: 520 bots at once. At 560, 10 of 570 bots (1.8%) "
        "failed, over the 1% limit.\n"
        "  Errors at 560: 10 x OperationalError.\n"
        "Validation test: 416 bots (80% of 520), arriving over 11 min, ran for 23 min and "
        "passed."
    ) in text
    assert "Not measured: uploads over participants' own networks" in text
    # Only the failure that broke its limit is red.
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    coloured = _join(format_performance_summary(results, terminal=True))
    assert "m10 (1.8%)" in coloured and " 1 (" in coloured and "m1 (" not in coloured


def test_performance_summary_is_plain_text_off_a_terminal(monkeypatch):
    results = [
        _base_result(
            n_bots=n,
            busy_responses=n,
            participants_failed=1,
            busy_early_finishes={"main_chain": {"participants": 1}},
            queue_waits={"high": {"q_delay_p95": high}, "low": {"q_delay_p95": 9.0}},
        )
        for n, high in ((100, 1.0), (200, 8.0))
    ]
    results.append(_base_result(n_bots=400, slots_started=300))

    plain = _join(format_performance_summary(results, terminal=False))

    assert "untested" in plain
    assert "\x1b[" not in plain and "\u2026" not in plain
    assert "largest passing" in _join(
        format_performance_summary([_base_result()], terminal=False)
    )
    # Measures that most tests lack go in a second table, keyed by bot count.
    tables = plain.split("\n\n")
    extra = next(t for t in tables if "queue p95" in t)
    assert "N/A" not in plain
    assert re.search(r"\n +100 +100 \(\d.*1\.0 s +9\.0 s", extra)
    assert max(map(len, next(t for t in tables if "Req/s" in t).splitlines())) <= 112
    assert "\x1b[" not in _join(format_test_results(results[0]))
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    coloured = _join(format_performance_summary(results, terminal=True))
    # Only the high-priority queue wait over its limit is red, in the second table.
    assert re.search(r"\x1b\[91m *8\.0 s", coloured)
    assert not re.search(r"\x1b\[91m *(1|9)\.0 s", coloured)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert "\x1b[" in _join(format_test_results(results[0]))
    monkeypatch.setenv("TERM", "dumb")
    assert "\x1b[" not in _join(format_performance_summary(results, terminal=True))
    assert "\x1b[" not in _join(format_test_results(results[0]))

    monkeypatch.setenv("COLUMNS", "60")
    monkeypatch.setenv("NO_COLOR", "1")
    narrow = format_performance_summary(results, terminal=True)
    notes = narrow[narrow.index("Notes") :]
    assert len(notes) > 3 and max(map(len, notes)) <= 60
    assert "\x1b[" not in _join(narrow) and "\u2026" not in _join(narrow)


def test_experiment_code_key_changes_with_config_txt(tmp_path, monkeypatch):
    from psynet.perf_ssh import experiment_code_key

    monkeypatch.chdir(tmp_path)
    (tmp_path / "deploy.toml").write_text(
        "version = 1\n[exclude]\npaths = []\nnames = []\nsuffixes = []\n"
    )
    (tmp_path / "experiment.py").write_text("")
    (tmp_path / "config.txt").write_text("[Config]\n")
    key = experiment_code_key()
    (tmp_path / "config.txt").write_text("[Config]\n# A comment\n")
    assert experiment_code_key() != key


def test_experiment_code_key_follows_the_local_dallinger_checkout(
    tmp_path, monkeypatch
):
    import subprocess

    from psynet.perf_ssh import experiment_code_key

    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "deploy.toml").write_text(
        "version = 1\n[exclude]\npaths = []\nnames = []\nsuffixes = []\n"
    )
    monkeypatch.chdir(experiment)
    checkout = tmp_path / "Dallinger"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "bots.py").write_text("A = 1\n")

    keys = [experiment_code_key(), experiment_code_key(dallinger_source=str(checkout))]
    (checkout / "bots.py").write_text("A = 2\n")
    keys.append(experiment_code_key(dallinger_source=str(checkout)))
    (checkout / "new_module.py").write_text("")
    keys.append(experiment_code_key(dallinger_source=str(checkout)))

    assert len(set(keys)) == 4


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_performance_tests_refuse_participants_that_bots_did_not_create(db_session):
    import click
    from dallinger import db

    from psynet.bot import Bot
    from psynet.command_line import _check_no_real_participants
    from psynet.experiment import get_experiment
    from psynet.participant import Participant
    from psynet.redis import redis_vars

    redis_vars.set("launch_finished", True)
    Bot()
    _check_no_real_participants(force=False)
    db.session.add(
        Participant(
            get_experiment(),
            recruiter_id="generic",
            worker_id="w",
            assignment_id="a",
            hit_id="",
            mode="debug",
        )
    )
    db.session.commit()
    with pytest.raises(click.ClickException, match="1 participant"):
        _check_no_real_participants(force=False)
    _check_no_real_participants(force=True)


@pytest.mark.parametrize(
    "mode, recruiter, live",
    [
        ("debug", "prolific", False),
        ("sandbox", "hotair", False),
        ("sandbox", "generic", False),
        ("sandbox", "prolific", True),
        ("sandbox", "lucid-recruiter", True),
        ("live", "hotair", True),
    ],
)
def test_live_recruitment_counts_as_real_participants(mode, recruiter, live):
    from psynet.recruiters import recruits_real_participants

    config = {"mode": mode, "recruiter": recruiter}
    assert (
        bool(recruits_real_participants(Mock(get=lambda k, d=None: config.get(k, d))))
        is live
    )


_EXPERIMENT = {
    "label": "Test",
    "test_n_bots": 2,
    "test_duration_minutes": 1,
    "test_parallel_stagger_interval_s": 0.1,
    "estimated_duration_minutes": 1,
}


def _fake_server(respond):
    """Return an SSH executor whose ``run`` answers with ``respond(cmd)``, an output or (status, output).

    Commands that report their exit status get it appended, as the server would.
    """
    executor = Mock()
    executor.commands = []

    def run(cmd, raise_=True):
        executor.commands.append(cmd)
        response = respond(cmd)
        status, output = response if isinstance(response, tuple) else (0, response)
        if "__psynet_exit_status" not in cmd:
            return output
        return f"{output}__psynet_exit_status={status}\n"

    executor.run.side_effect = run
    return executor


def _answers(responses):
    """Return a ``respond`` for :func:`_fake_server` that answers with the first of ``responses`` whose pattern is in the command, else ``""``."""
    return lambda cmd: next((out for pat, out in responses.items() if pat in cmd), "")


# A database of 1,000 bytes on a disk with plenty of free space.
_DISK = {
    "pg_database_size": "1000\n",
    "data_directory": "/var/lib/postgresql/data\n",
    " df ": "Filesystem 1024-blocks Used Available\nx 9 0 9999 1% /\n",
}


def _remote_app(respond, isolated=True):
    """Return a ``RemoteApp`` of ``my-app`` whose server answers with ``respond(cmd)``."""
    from psynet.perf_ssh import RemoteApp

    def answer(cmd):
        if cmd.startswith("docker inspect"):
            own = "my-app_postgresql" in cmd
            return "172.18.0.2" if own == isolated else ""
        if "DATABASE_URL" in cmd:
            return "my-app\n"
        return respond(cmd)

    remote = RemoteApp(_fake_server(answer), "my-app", "server")
    remote.prepare = Mock(return_value=0)
    return remote


@pytest.mark.parametrize(
    "prefill, restore_fails", [(None, False), (None, True), (5, False), (5, True)]
)
def test_a_remote_reset_restores_only_the_apps_database_in_its_container(
    prefill, restore_fails, caplog
):
    from psynet.perf_ssh import DatabaseReset

    in_use = [(1, 'ERROR:  55006: database "my-app" is being accessed\n')]
    answers = _answers({**_DISK, "pg_tables": "participant\n", "count(*)": "3\n"})
    restores = []

    def respond(cmd):
        if 'DROP DATABASE IF EXISTS "my-app"' in cmd and in_use:
            return in_use.pop()
        if 'CREATE DATABASE "my-app" TEMPLATE' in cmd:
            restores.append(cmd)
            if restore_fails and len(restores) == 2:
                return (1, "ERROR:  53100: could not extend file: No space left\n")
        return answers(cmd)

    remote = _remote_app(respond)
    remote.stop = Mock(side_effect=lambda **_: setattr(remote, "_stopped", ["web"]))
    remote.start = Mock(side_effect=lambda: setattr(remote, "_stopped", []))
    reset = DatabaseReset(remote, prefill)
    with caplog.at_level("INFO"):
        reset()
        reset()
        if restore_fails:
            with pytest.raises(RuntimeError, match="No space left"):
                reset.close()
        else:
            reset.close()

    sql = [c for c in remote.executor.commands if " psql " in c]
    assert sql and all("docker exec" in c and "my-app_postgresql" in c for c in sql)
    english = (
        "-e 'PGOPTIONS=-cclient_min_messages=warning -clc_messages=C' -e LC_MESSAGES=C"
    )
    assert all(english in c for c in sql)
    snapshot = reset.snapshot
    assert snapshot.startswith("my-app_snapshot_")
    baseline = reset._copies[0]
    assert baseline.startswith("my-app_baseline_") == bool(prefill)
    original = baseline if prefill else snapshot
    assert re.findall(r"(?:CREATE|DROP) DATABASE [^']*", " ".join(sql)) == [
        *([f'CREATE DATABASE "{baseline}" TEMPLATE "my-app"'] if prefill else []),
        f'CREATE DATABASE "{snapshot}" TEMPLATE "my-app"',
        'DROP DATABASE IF EXISTS "my-app"',
        'DROP DATABASE IF EXISTS "my-app"',
        f'CREATE DATABASE "my-app" TEMPLATE "{snapshot}"',
        'DROP DATABASE IF EXISTS "my-app"',
        f'CREATE DATABASE "my-app" TEMPLATE "{original}"',
        # A failed restore keeps the copy that it restores from.
        *(
            f'DROP DATABASE IF EXISTS "{c}"'
            for c in reset._copies
            if not (restore_fails and c == original)
        ),
    ]
    assert any("redis-cli --scan --pattern" in c for c in remote.executor.commands)
    assert reset.snapshot_rows == {"participant": 3}
    assert remote.stop.call_count == 3 + bool(prefill)
    # The final restore doesn't need the web server for the safety check.
    assert remote.stop.call_args.kwargs == {"check": False}
    # The caller's start_stopped_services starts them after close().
    assert remote.start.call_count == remote.stop.call_count - 1
    assert ("already held 3 participants" in caplog.text) == (not prefill)
    assert ("Could not restore the database my-app" in caplog.text) == restore_fails
    if restore_fails:
        assert f"{original} keeps the database as the run found it" in caplog.text
        assert "psynet destroy ssh --server server --app my-app" in caplog.text


def test_an_interrupted_final_restore_still_drops_the_other_copies():
    from psynet.perf_ssh import DatabaseReset

    def respond(cmd):
        if 'CREATE DATABASE "my-app" TEMPLATE "my-app_baseline_' in cmd:
            raise KeyboardInterrupt
        return _answers({**_DISK, "pg_tables": "participant\n", "count(*)": "0\n"})(cmd)

    remote = _remote_app(respond)
    remote.stop, remote.start = Mock(), Mock()
    reset = DatabaseReset(remote, prefill_participants=5)
    reset()
    with pytest.raises(KeyboardInterrupt):
        reset.close()

    sql = " ".join(c for c in remote.executor.commands if " psql " in c)
    dropped = re.findall(r'DROP DATABASE IF EXISTS "(my-app_[^"]*)"', sql)
    assert dropped == [reset.snapshot]


@pytest.mark.parametrize(
    "error, ours",
    [
        ("53100: could not extend file: No space left", True),
        ('42P04: database "my-app_snapshot_1" already exists', False),
    ],
)
def test_a_failed_first_snapshot_is_dropped_and_the_database_left_alone(error, ours):
    from psynet.perf_ssh import DatabaseReset

    def respond(cmd):
        if 'CREATE DATABASE "my-app_snapshot_' in cmd:
            return (1, f"ERROR:  {error}\n")
        return _answers(_DISK)(cmd)

    remote = _remote_app(respond)
    remote.stop, remote.start = Mock(), Mock()
    reset = DatabaseReset(remote)
    with pytest.raises(RuntimeError, match="No space left|already exists"):
        reset()
    reset.close()

    sql = " ".join(c for c in remote.executor.commands if " psql " in c)
    dropped = re.findall(r'DROP DATABASE IF EXISTS "([^"]*)"', sql)
    # A database of the same name that this run didn't create stays.
    assert len(dropped) == ours
    assert all(d.startswith("my-app_snapshot_") for d in dropped)


def test_remote_output_leaves_out_stderr_unless_the_command_fails():
    import subprocess

    from psynet.perf_ssh import run_with_status

    executor = Mock()
    executor.run.side_effect = lambda cmd, raise_: (
        subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
    )
    assert run_with_status(executor, "echo '{}'; echo WARN >&2") == (0, "{}\n")
    status, output = run_with_status(executor, "cat /no/such/file && echo copied")
    assert status != 0 and "No such file" in output
    executor.run.side_effect = lambda cmd, raise_: "partial output"
    assert run_with_status(executor, "echo hi") == (255, "partial output")


def test_a_prefilled_reset_refuses_to_copy_while_async_jobs_are_unfinished():
    from psynet.perf_ssh import DatabaseReset

    remote = _remote_app(_answers(_DISK))
    remote.stop, remote.start = Mock(), Mock()
    reset = DatabaseReset(remote, prefill_participants=5)
    remote.prepare.return_value = 2
    with pytest.raises(RuntimeError, match="2 async jobs had not finished"):
        reset()
    assert not any("CREATE DATABASE" in c for c in remote.executor.commands)


@pytest.mark.parametrize("restart_fails", [False, True])
def test_ssh_starts_the_stopped_services_again_after_a_failed_reset(
    restart_fails, tmp_path, monkeypatch, capsys
):
    import json

    import click

    from psynet.command_line import _run_ssh_performance_test

    respond = _answers(
        {
            "CREATE DATABASE": (
                1,
                "ERROR:  53100: could not extend file: No space left\n",
            ),
            **(
                {".yml start ": (1, "Error: no such container\n")}
                if restart_fails
                else {}
            ),
            "SCARD": "1\n",
            "ps --services": "postgresql\nredis\nweb\nworker_1\npgbouncer\nsidecar\n",
            **_DISK,
        }
    )

    monkeypatch.chdir(tmp_path)
    # Its handler would keep writing to capsys's stdout after this test.
    monkeypatch.setattr("psynet.perf_test.log_to_console", lambda *args: None)
    executor = _remote_app(respond).executor
    with (
        patch("psynet.command_line._ssh_executor", return_value=executor),
        patch("psynet.perf_ssh.RemoteApp.prepare", return_value=0),
        pytest.raises(click.ClickException) as error,
    ):
        _run_ssh_performance_test(
            "my-app",
            "server",
            _EXPERIMENT,
            reset=True,
            n_bots=[2],
            force=False,
            json_output="results.json",
        )

    assert "No space left" in error.value.message
    assert (
        "Starting the app's server processes again failed" in error.value.message
    ) == restart_fails
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["results"] == [] and "No space left" in data["reset_error"]
    manual = "docker compose start web worker_1 pgbouncer sidecar"
    assert (manual in capsys.readouterr().out) == restart_fails
    commands = executor.commands
    stop, start = (
        next(i for i, c in enumerate(commands) if f".yml {action} " in c)
        for action in ("stop", "start")
    )
    assert "stop web worker_1 pgbouncer sidecar ;" in commands[stop]
    assert "start web worker_1 pgbouncer sidecar ;" in commands[start]
    assert start > max(i for i, c in enumerate(commands) if " psql " in c)


def test_a_remote_reset_never_stops_every_service_of_an_app():
    remote = _remote_app(
        _answers({"ps --services": "postgresql\nredis\nfrontdoor\n", "": "0\n"})
    )
    with pytest.raises(RuntimeError, match="None of my-app's server processes"):
        remote.stop()
    assert not any(".yml stop" in c for c in remote.executor.commands)


_REDIS_CLI = """#!/bin/sh
cd "$FAKE_REDIS" || exit 1
case "$1" in
  SCARD) ls | wc -l ;;
  SMEMBERS) ls ;;
  HGET) sed -n "s/^$3 //p" "$2" ;;
esac
"""


@pytest.mark.parametrize("recovers", [True, False])
def test_a_remote_restart_waits_for_workers_and_names_those_that_never_register(
    recovers, tmp_path, monkeypatch
):
    import shlex
    import subprocess
    from types import SimpleNamespace

    from psynet import perf_ssh

    clock = [0.0]
    monkeypatch.setattr(
        perf_ssh,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda s: clock.__setitem__(0, clock[0] + s),
        ),
    )
    # RQ worker hashes, one file per key, read by a stub redis-cli.
    redis = tmp_path / "redis"
    redis.mkdir()
    (tmp_path / "redis-cli").write_text(_REDIS_CLI)
    (tmp_path / "redis-cli").chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    env["FAKE_REDIS"] = str(redis)

    def register(hostname):
        key = redis / f"rq:worker:{hostname}-id"
        key.write_text(f"name {hostname}-id\nhostname {hostname}\n")

    register("c1")
    register("c2")
    printed = []
    monkeypatch.setattr(
        perf_ssh, "print", lambda line: printed.append((clock[0], line)), raising=False
    )

    def respond(cmd):
        # Dallinger's worker_startup_timeout exits a hung worker, and Docker restarts it.
        if recovers and clock[0] >= 130:
            register("c2")
        if "exec -T web python -c" in cmd and clock[0] < 160:
            return (1, "")
        if redis_command := re.search(r"exec -T redis (.*) ; }", cmd):
            return subprocess.run(
                shlex.split(redis_command[1]), env=env, capture_output=True, text=True
            ).stdout
        if ".yml stop " in cmd:
            for key in redis.iterdir():
                key.unlink()
        if ".yml start " in cmd:
            register("c1")
        if "docker inspect" in cmd:
            return "worker_1 c1\nworker_2 c2\n"
        if "ps --services" in cmd:
            return "redis\nweb\nworker_1\nworker_2\n"
        return "c1\nc2\n" if "ps -a -q" in cmd else ""

    remote = perf_ssh.RemoteApp(_fake_server(respond), "my-app", "server")
    remote.prepare = Mock()
    remote.stop()
    if recovers:
        remote.start()
    else:
        with pytest.raises(RuntimeError) as error:
            remote.start()
        assert "1 of 2 worker processes registered with RQ; worker_2 didn't." in str(
            error.value
        )
        assert "cd ~/dallinger/my-app && docker compose restart worker_2" in str(
            error.value
        )
    waiting = "Waiting for worker processes to register (1 of 2; up to 180 s)"
    assert all(t >= 20 for t, line in printed if waiting in line)
    assert any(waiting in line for _, line in printed)
    web = "Waiting for the web server to answer (up to 180 s)"
    assert any(web in line for _, line in printed) == recovers
    assert not any(".yml restart" in c for c in remote.executor.commands)


@pytest.mark.parametrize("web_database", ["dallinger", "other-app"])
def test_a_remote_reset_refuses_a_database_not_named_after_the_app(web_database):
    from psynet.perf_ssh import DatabaseReset, RemoteApp

    remote = RemoteApp(_fake_server(lambda cmd: f"{web_database}\n"), "my-app", "s")
    remote.prepare = Mock()
    with pytest.raises(ValueError, match="Refusing to reset"):
        DatabaseReset(remote)


def test_a_remote_reset_refuses_when_the_free_disk_space_is_unknown():
    from psynet.perf_ssh import DatabaseReset

    disk_unknown = {**_DISK, " df ": (1, "df: denied\n")}
    reset = DatabaseReset(_remote_app(_answers(disk_unknown)))
    with pytest.raises(RuntimeError, match="free disk space"):
        reset._check_disk_space("my-app")


def test_a_suite_drives_remote_tests_through_their_json_results():
    import re
    from dataclasses import asdict

    from psynet.perf_ssh import RemotePerformanceTester

    remote = Mock(force=False)
    remote.run_psynet.side_effect = lambda args, bot_log: {
        "psynet_version": "remote",
        "results": [
            asdict(_base_result(n_bots=int(re.search(r"--n-bots (\d+)", args)[1])))
        ],
    }
    tester = RemotePerformanceTester(
        remote,
        duration_minutes=1,
        stagger_interval_s=0.1,
        time_factor=1.0,
        bot_processes="auto",
    )
    before_test = Mock()

    results = PerformanceSuite(tester, before_test=before_test).run([2, 4])

    assert [r.n_bots for r in results] == [2, 4]
    assert before_test.call_count == 2
    assert "--test-label 'TEST 2/2'" in remote.run_psynet.call_args.args[0]
    assert tester.remote_metadata == {"psynet_version": "remote"}


def _remote_search(
    monkeypatch,
    reset=False,
    reset_side_effect=None,
    cleanup_error=None,
    interrupt_at_test=None,
    restore_error=None,
    start_stopped_services=None,
    **options,
):
    """Run a mocked SSH capacity search of a 12-minute study; return its remote commands and results."""
    import re
    from dataclasses import asdict

    from psynet.command_line import _run_ssh_performance_test

    def run_psynet(args, bot_log):
        if re.search(rf"--test-label 'TEST {interrupt_at_test}'", args):
            raise KeyboardInterrupt
        n_bots = int(re.search(r"--n-bots (\d+)", args)[1])
        p95 = 0.9 if n_bots > 150 else 0.1
        result = _base_result(n_bots=n_bots, p95_response_time=p95, **_STEADY)
        return {"psynet_version": "remote", "results": [asdict(result)]}

    monkeypatch.setattr("psynet.perf_test.log_to_console", lambda *args: None)
    with (
        patch("psynet.command_line._ssh_executor"),
        patch("psynet.perf_ssh.RemoteApp.run_psynet", side_effect=run_psynet) as run,
        patch(
            "psynet.command_line._ssh_database_reset",
            return_value=reset
            and Mock(
                snapshot=None,
                snapshot_rows=None,
                side_effect=reset_side_effect,
                **{"close.side_effect": restore_error},
            ),
        ),
        patch(
            "psynet.perf_ssh.RemoteApp.start_stopped_services",
            start_stopped_services or Mock(side_effect=cleanup_error),
        ),
    ):
        results = _run_ssh_performance_test(
            "my-app",
            "server",
            {**_EXPERIMENT, "estimated_duration_minutes": 12},
            reset=reset,
            n_bots="auto",
            **options,
        )
    return [c.args[0] for c in run.call_args_list], results


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_a_failed_remote_reset_writes_the_json_then_fails(
    cleanup_fails, tmp_path, monkeypatch
):
    import json

    import click

    json_output = tmp_path / "results.json"
    reset_failure = "exit code 1: disk full"
    with pytest.raises(click.ClickException) as error:
        _remote_search(
            monkeypatch,
            reset=True,
            reset_side_effect=[None, None, click.Abort(reset_failure)],
            cleanup_error=RuntimeError("my-app may be stopped")
            if cleanup_fails
            else None,
            json_output=str(json_output),
            max_queue_p95_s=8,
        )
    assert "Resetting the database failed" in error.value.message
    assert ("my-app may be stopped" in error.value.message) == cleanup_fails

    data = json.loads(json_output.read_text())
    assert len(data["results"]) == 2
    assert data["finished_at"] and data["reset_error"] == reset_failure
    assert data["options"]["max_queue_p95_s"] == 8
    assert data["options"]["confirmation_skipped"] == "resetting the database failed"


def test_a_failed_final_restore_fails_the_command(monkeypatch):
    import click

    start_stopped_services = Mock()
    with pytest.raises(click.ClickException) as error:
        _remote_search(
            monkeypatch,
            reset=True,
            restore_error=RuntimeError("disk full"),
            start_stopped_services=start_stopped_services,
        )
    assert "Restoring the database to how the run found it failed: disk full" in (
        error.value.message
    )
    start_stopped_services.assert_called_once()


def test_an_interrupted_remote_search_keeps_the_finished_tests_json(
    tmp_path, monkeypatch
):
    import json

    json_output = tmp_path / "results.json"
    with pytest.raises(KeyboardInterrupt):
        _remote_search(monkeypatch, interrupt_at_test=3, json_output=str(json_output))

    data = json.loads(json_output.read_text())
    assert [r["n_bots"] for r in data["results"]] == [10, 20]
    assert data["finished_at"] is None
    assert list(tmp_path.iterdir()) == [json_output]
    umask = os.umask(0)
    os.umask(umask)
    assert json_output.stat().st_mode & 0o777 == 0o666 & ~umask


def test_a_failed_per_test_json_write_doesnt_stop_the_run(monkeypatch):
    finished_at = []

    def write(json_output, *, metadata, **_):
        finished_at.append(metadata["finished_at"])
        if len(finished_at) == 1:
            raise OSError("No space left on device")

    with patch("psynet.command_line._write_json_results", side_effect=write):
        _, results = _remote_search(monkeypatch, json_output="results.json")

    assert len(results) > 1 and len(finished_at) == len(results) + 1
    assert finished_at[-1] is not None


def test_remote_failures_name_the_last_error_line():
    from psynet.command_line import _remote_failure_summary

    lines = ["Starting", "psycopg2.OperationalError: FATAL:  no more", "Exiting"]
    assert _remote_failure_summary(1, lines) == (
        "exit code 1: psycopg2.OperationalError: FATAL:  no more"
    )
    assert _remote_failure_summary(2, ["Starting", "Killed", ""]) == (
        "exit code 2: Killed"
    )
    assert _remote_failure_summary(3, []) == "exit code 3"


def test_a_remote_capacity_search_ends_with_a_confirmation_test(tmp_path, monkeypatch):
    """Over SSH, tests are timed like a local search of a 12-minute study, and later ones pause first."""
    import json

    json_output = tmp_path / "results.json"
    commands, results = _remote_search(monkeypatch, json_output=str(json_output))

    assert all(c.startswith("performance-test local --existing") for c in commands)
    assert "--suite-started-s-ago" not in commands[0]
    assert all("--suite-started-s-ago" in c for c in commands[1:])
    assert all("--duration-minutes 5 " in c for c in commands[:-1])
    assert not any("--arrival-minutes" in c for c in commands[:-1])
    assert "--n-bots 120 " in commands[-1]
    assert "--duration-minutes 24 --arrival-minutes 12.0 " in commands[-1]
    assert [r.confirmation for r in results] == [False] * 8 + [True]
    written = json.loads(json_output.read_text())
    assert written["psynet_version"] == "remote"
    options = written["options"]
    assert options["confirm"] is True and options["confirmation_skipped"] is None
    assert options["session_minutes"] == 12
    assert options["reset_database"] is False


@pytest.mark.parametrize(
    "options, n_tests, last_command",
    [
        (dict(no_confirm=True), 8, "--duration-minutes 5 "),
        (dict(reset=True), 9, "--arrival-minutes 12.0 "),
    ],
    ids=["no-confirm", "reset-database"],
)
def test_remote_search_options_reach_the_right_tests(
    monkeypatch, options, n_tests, last_command
):
    commands, _ = _remote_search(monkeypatch, **options)

    assert len(commands) == n_tests
    assert last_command in commands[-1]
    assert not any("--arrival-minutes" in c for c in commands[:8])
    if "reset" in options:
        assert not any("--suite-started-s-ago" in c for c in commands)


def test_resetting_refuses_live_mode_even_with_force(monkeypatch):
    import click

    from psynet.command_line import _check_no_real_participants

    monkeypatch.setattr("psynet.command_line.get_config", lambda: {"mode": "live"})
    with pytest.raises(click.ClickException, match="live mode, even with --force"):
        _check_no_real_participants(force=True, resetting=True)

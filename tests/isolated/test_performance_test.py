import os
from unittest.mock import Mock, patch

import pytest

from psynet.isolated_environment import ENV_VAR, READY_ENV_VAR, SHARED
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
from psynet.perf_test.measure import _split_failed_requests, phase_stats
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
        "avg_response_time": 0.05,
        "median_response_time": 0.04,
        "p95_response_time": 0.1,
        "p99_response_time": 0.12,
        "stddev_response_time": 0.02,
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


def test_postgres_running_out_of_connections_is_named_with_advice():
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
    assert "raise max_connections" in _join(format_capacity_summary(results))


def test_capacity_summary_names_the_bot_errors():
    results = [
        _base_result(n_bots=10),
        _base_result(
            n_bots=20,
            bot_errors=1,
            bot_error_kinds={"HTTP 500 on /participant_status": 1},
        ),
    ]

    assert "20 did not (1 bot error (HTTP 500 on /participant_status))" in _join(
        format_capacity_summary(results)
    )


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
        patch.object(tester, "_test_performance", return_value=result),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        assert PerformanceSuite(tester).run([10, 20]) == [result]


def test_a_suite_calls_before_test_before_every_test_instead_of_pausing():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    before_test = Mock()

    with (
        patch.object(
            tester,
            "_test_performance",
            side_effect=lambda n_bots, bot_log_file: _base_result(n_bots=n_bots),
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
        patch.object(tester, "_test_performance", return_value=_base_result()),
        patch("psynet.perf_test.runtime.raise_open_file_limit"),
    ):
        PerformanceSuite(tester).run([2])

    assert "Estimated session:    13.0 min" in caplog.text
    assert ("only sees the start of the study" in caplog.text) == warns


def test_arrival_minutes_spreads_bot_slots_evenly_over_the_window():
    import time

    tester = PerformanceTester(
        authenticated_session=Mock(),
        base_url="http://x",
        stagger_interval_s=100,
        arrival_minutes=0.01,
    )
    bot_state = _BotState()
    started = []

    def start_slot():
        started.append(time.time())
        bot_state.first_bot_initialized = True

    start = time.time()
    tester._run_monitoring_loop(4, bot_state, start_slot, start, start + 1)

    # The loop can only start a slot late, never early: 0.6 s over 3 gaps.
    assert len(started) == 4
    assert all(t - started[0] >= 0.2 * i - 0.01 for i, t in enumerate(started))


def test_arrival_minutes_starts_a_single_bot_slot():
    import time

    tester = PerformanceTester(
        authenticated_session=Mock(), base_url="http://x", arrival_minutes=1
    )
    bot_state = _BotState()
    start_slot = Mock(
        side_effect=lambda: setattr(bot_state, "first_bot_initialized", True)
    )

    start = time.time()
    tester._run_monitoring_loop(1, bot_state, start_slot, start, start + 0.5)

    start_slot.assert_called_once()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_phase_stats_split_requests_and_queue_waits_at_the_boundary(db_session):
    from datetime import datetime, timedelta

    from dallinger import db

    from psynet.experiment import Request
    from psynet.process import AsyncProcess

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
    db.session.execute(
        AsyncProcess.__table__.insert(),
        [
            dict(time_enqueued=at(s), time_started=at(s), queue_delay=delay)
            for s, delay in [(5, 30.0), (70, 1.0)]
        ],
    )
    db.session.flush()

    startup, steady = phase_stats(0, 10**9, 0, at(600), boundary=at(60))

    assert startup == dict(
        key_requests=3,
        request_errors=1,
        p95_response_time=pytest.approx(1.9),
        q_delay_p95=30.0,
    )
    assert steady == dict(
        key_requests=20, request_errors=0, p95_response_time=0.1, q_delay_p95=1.0
    )


def test_report_compares_start_up_and_steady_state():
    phases = dict(
        first_completion_s=200.0,
        actual_duration=600.0,
        startup_phase=dict(
            key_requests=500, request_errors=0, p95_response_time=0.9, q_delay_p95=12.0
        ),
        steady_state_phase=dict(
            key_requests=900, request_errors=0, p95_response_time=0.1, q_delay_p95=1.0
        ),
    )
    report = _join(format_test_results(_base_result(**phases)))
    assert "Start-up: the first 200 s" in report
    assert "p95 async queue wait" in report

    over = _base_result(n_bots=40, p95_response_time=0.7, **phases)
    summary = _join(format_capacity_summary([over]))
    assert "the start-up exceeded the limits (p95 response time 900 ms" in summary

    no_completion = _join(format_test_results(_base_result()))
    assert "No bot completed the experiment during the test" in no_completion


_HOLD_TIMEOUT = "timeline_hold:wait_while, fail_on_timeout"


@pytest.mark.parametrize(
    "over_capacity",
    [{"p95_response_time": 0.9}, {"failed_reasons": {_HOLD_TIMEOUT: 100}}],
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

    def fake_test(n_bots, bot_log_file):
        overrides = over_capacity if n_bots > capacity else {}
        return _base_result(n_bots=n_bots, server_stopped=False, **overrides)

    with (
        patch.object(tester, "_test_performance", side_effect=fake_test),
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


class _RecordingCursor:
    """Record the statements composed with ``psycopg2.sql`` that run on a cursor."""

    def __init__(self, cursor, statements):
        self._cursor, self._statements = cursor, statements

    def execute(self, statement, params=None):
        from psycopg2 import sql

        if isinstance(statement, sql.Composable):
            self._statements.append(statement.as_string(self._cursor))
        return self._cursor.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


@pytest.fixture
def scratch_database(db_session, monkeypatch):
    """Yield a scratch database's URL and a list of databases to drop afterwards.

    The scratch database stands in for the isolated test session's own.
    """
    from dallinger import db

    from psynet.isolated_environment import (
        DATABASE_ENV_VAR,
        create_database,
        drop_database,
    )
    from psynet.perf_reset import _maintenance_cursor

    url = create_database(
        db.engine.url.render_as_string(hide_password=False), suffix="_scratch_test_0"
    )
    created = [url.rsplit("/", 1)[1]]
    monkeypatch.setenv(DATABASE_ENV_VAR, created[0])
    yield url, created
    with _maintenance_cursor(url) as cursor:
        for name in created:
            drop_database(cursor, name)


def _participants(database_url, n_new=0):
    """Add ``n_new`` rows to a minimal participant table; return its row count."""
    import psycopg2

    connection = psycopg2.connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("CREATE TABLE IF NOT EXISTS participant (id serial)")
            for _ in range(n_new):
                cursor.execute("INSERT INTO participant DEFAULT VALUES")
            cursor.execute("SELECT count(*) FROM participant")
            return cursor.fetchone()[0]
    finally:
        connection.close()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_database_reset_restores_snapshots_and_drops_only_its_own(scratch_database):
    import re
    from contextlib import contextmanager

    from psynet import perf_reset
    from psynet.redis import redis_vars

    url, created = scratch_database
    cache = perf_reset.prefill_snapshot_name("0123456789ab", 3)
    created.append(cache)
    statements = []

    class RecordingReset(perf_reset.DatabaseReset):
        @contextmanager
        def _connect(self):
            with super()._connect() as cursor:
                yield _RecordingCursor(cursor, statements)

    _participants(url, 1)
    redis_vars.set("launch_finished", True)
    server = Mock()
    reset = RecordingReset(server.stop, server.start, database_url=url)
    reset()
    created.append(reset.snapshot)
    assert reset.snapshot_rows == {"participant": 1}
    _participants(url, 1)
    reset()
    assert _participants(url) == 1
    assert server.stop.call_count == server.start.call_count == 2
    assert redis_vars.get("launch_finished") is True
    reset.close()
    assert perf_reset.find_snapshot(reset.snapshot, url) is None

    prefill = RecordingReset(
        server.stop,
        server.start,
        prefill=lambda: _participants(url, 2),
        keep_as=cache,
        database_url=url,
    )
    prefill()
    prefill.close()
    assert cache in [name for name, _, _ in perf_reset.list_snapshots(url)]
    _participants(url, 5)
    cached = RecordingReset(
        server.stop, server.start, from_snapshot=cache, database_url=url
    )
    cached()
    cached.close()
    assert _participants(url) == 3

    dropped = re.findall(
        r'DROP DATABASE (?:IF EXISTS )?"([^"]+)"', " ".join(statements)
    )
    assert set(dropped) == {created[0], reset.snapshot}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.parametrize("second_stop", [None, RuntimeError("still stopping")])
def test_close_keeps_a_finished_prefill_whose_snapshot_was_not_taken(
    scratch_database, second_stop
):
    from psynet import perf_reset

    url, created = scratch_database
    keep = perf_reset.prefill_snapshot_name("fedcba987654", 2)
    created.append(keep)
    server = Mock()
    server.stop.side_effect = [KeyboardInterrupt, second_stop]
    reset = perf_reset.DatabaseReset(
        server.stop, server.start, prefill=Mock(), keep_as=keep, database_url=url
    )
    with pytest.raises(KeyboardInterrupt):
        reset()
    reset.close()
    assert server.stop.call_count == 2
    assert perf_reset.find_snapshot(keep, url) == keep


@pytest.mark.parametrize(
    "url, allowed",
    [
        ("postgresql://u:p@localhost/dallinger_test_5000", True),
        ("postgresql:///dallinger_test_5000?host=/tmp", True),
        ("postgresql://u:p@localhost/postgres", False),
        ("postgresql://u:p@localhost/template1", False),
        ("postgresql://u:p@db.example.org/dallinger_test_5000", False),
    ],
)
def test_reset_refuses_system_and_remote_databases(url, allowed):
    from psynet.isolated_environment import DATABASE_ENV_VAR
    from psynet.perf_reset import check_resettable_database

    environ = {DATABASE_ENV_VAR: "dallinger_test_5000"}
    if allowed:
        check_resettable_database(url, environ)
    else:
        with pytest.raises(ValueError, match="Refusing"):
            check_resettable_database(url, environ)


def test_reset_refuses_a_session_variable_naming_a_debug_database():
    from psynet.isolated_environment import DATABASE_ENV_VAR
    from psynet.perf_reset import check_resettable_database

    with pytest.raises(ValueError, match="Refusing"):
        check_resettable_database(
            "postgresql://u:p@localhost/dallinger", {DATABASE_ENV_VAR: "dallinger"}
        )


@pytest.mark.parametrize(
    "environ",
    [{"CI": "1"}, {READY_ENV_VAR: "1"}, {ENV_VAR: SHARED}, None],
    ids=["ci", "ready-without-isolation", "shared", "isolated"],
)
def test_reset_only_drops_the_isolated_session_database(environ):
    from psynet.isolated_environment import (
        DEFAULT_DATABASE_URL,
        IsolatedEnvironment,
        should_isolate,
    )
    from psynet.perf_reset import check_resettable_database

    shared = {"DATABASE_URL": os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)}
    if environ is None:
        with IsolatedEnvironment.start(shared) as environment:
            check_resettable_database(environment.env["DATABASE_URL"], environment.env)
        return
    environ = {**shared, **environ}
    assert not should_isolate(environ)
    with pytest.raises(ValueError, match="only works in .* isolated test environment"):
        check_resettable_database(
            "postgresql://dallinger:dallinger@localhost/dallinger", environ
        )


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
        assert "Even 150 bots did not keep" in text
        assert f"({expected})." in text
        assert "Design experiments to avoid this" in text
    else:
        assert failures == []
        assert "at least 150" in text


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

    assert ("Cap concurrent participants" in text) == capped
    assert ("about 10" if capped else "at least 10") in text
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
    assert "These don't count against capacity" in text


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
        f"{participants} of 150 participants ({share}) got fewer trials in "
        "main_chain because every chain was busy; median 41 of 60 trials."
    ) in report
    if participants == 1:
        assert capacity_failures(result) == []
        assert "1 participant who got fewer trials" in summary
    else:
        assert capacity_failures(result) == [
            "23 participants got fewer trials in main_chain because every "
            "chain was busy"
        ]
        assert "wait_for_networks=True" in summary
        assert "Cap concurrent participants" not in summary


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
            db_rows_before={"participant": 2_400, "trial": 75_000},
            db_rows_after={"participant": 3_000, "trial": 103_000},
        ),
    ]

    assert (
        "Database rows from the first test to the last: participant 2,000 to "
        "3,000, trial 65,000 to 103,000." in _join(format_performance_summary(results))
    )
    text = _join(format_capacity_summary(results))
    assert "The database grew a lot during these tests" in text
    assert "trial 65,000 and 103,000" in text
    assert "Rerun with --reset-database" in text

    results[-1].db_rows_after = {"participant": 2_600, "trial": 80_000}
    assert "database grew" not in _join(format_capacity_summary(results))


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
    assert "Cap concurrent participants at about 120 (80% of 150)." in text


def test_capacity_summary_mentions_queue_waits_only_with_async_processes():
    results = [_base_result(n_bots=50, p95_response_time=0.1, q_delay_median=None)]
    assert "async" not in _join(format_capacity_summary(results))

    results[0].q_delay_median = 0.5
    assert "async queue wait under" in _join(format_capacity_summary(results))


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
    assert "Cap concurrent" not in text
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


def test_capacity_summary_says_when_every_count_failed():
    results = [_base_result(n_bots=n, bot_errors=1) for n in (2, 4)]

    assert "Even 2 bots did not keep" in _join(format_capacity_summary(results))
    assert format_capacity_summary([]) == []


@pytest.mark.parametrize("n_passed", [20, 10])
def test_capacity_summary_flags_a_pass_at_or_above_a_failed_smallest_count(n_passed):
    results = [
        _base_result(n_bots=10, p95_response_time=0.1, bot_errors=1),
        _base_result(n_bots=n_passed, p95_response_time=0.1),
    ]

    text = _join(format_capacity_summary(results))

    assert "Even 10 bots did not keep" in text
    assert f"{n_passed} bots passed, so the results are inconsistent" in text


def test_capacity_summary_warns_when_starting_the_bots_took_much_of_the_test():
    results = [_base_result(n_bots=50, actual_duration=60.0, ramp_up_s=30.0)]
    assert (
        "took 30 s of the 60 s test, so the server ran fully loaded for only 50%"
        in _join(format_capacity_summary(results))
    )

    results[0].ramp_up_s = 5.0
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
    tester.duration_minutes = 0
    with patch.multiple(
        tester,
        _capture_initial_state=Mock(),
        _run_monitoring_loop=Mock(),
        _max_request_id=Mock(),
        _clear_realtime_status=Mock(),
        _calculate_and_report_results=Mock(),
    ):
        tester.run_test("1/1", 5, bot_log_file=None)

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
        result(2000, request_errors=60, q_delay_p95=36.9),
    ]

    text = _join(format_capacity_summary(results))
    assert "Capacity: about 640" in text
    assert "60 request errors; p95 async queue wait 36.90 s" in text
    assert (
        "The 640-bot test had 1 request error, 3 busy/stale responses and 1 bot error"
        in text
    )
    assert "add worker processes with num_dynos_worker" in text


def test_capacity_summary_does_not_suggest_a_cap_when_bots_started_too_slowly():
    results = [
        _base_result(n_bots=80, p95_response_time=0.085),
        _base_result(n_bots=160, slots_started=160, peak_running=140),
    ]

    text = _join(format_capacity_summary(results))

    assert "Capacity: at least 80 concurrent bots" in text
    assert "160 could not be tested" in text
    assert "limit the test rather than the server" in text
    assert "Cap concurrent" not in text


def test_a_test_whose_bots_ran_late_could_not_be_tested():
    results = [
        _base_result(n_bots=80, p95_response_time=0.085, tester_lag_p95_s=0.01),
        _base_result(
            n_bots=160,
            p95_response_time=0.1,
            tester_lag_p95_s=0.24,
            tester_cpu_share=0.95,
        ),
    ]

    assert capacity_failures(results[1]) == [
        "bots in the test process were running 240 ms late (p95), so they could "
        "not keep pace (use more --bot-processes)"
    ]
    text = _join(format_capacity_summary(results))
    assert "Capacity: at least 80 concurrent bots" in text
    assert "160 could not be tested" in text
    assert "Spread the bots over more processes with --bot-processes" in text
    assert "Cap concurrent" not in text
    details = _join(format_test_results(results[1]))
    assert "240 ms" in details and "95% of a core" in details


def test_a_bot_process_that_did_not_report_makes_a_test_untestable():
    results = [_base_result(n_bots=80), _base_result(unreported_bot_processes=[2])]
    assert "bot process(es) 2 did not report" in capacity_failures(results[1])[0]
    assert "could not be tested" in _join(format_capacity_summary(results))


def test_a_busy_cpu_share_alone_does_not_fail_a_test():
    assert capacity_failures(_base_result(tester_cpu_share=0.95)) == []


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
    _, lag_p95_s = monitor.stop()

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
        (1, "start", 7, 0.1),
        (1, "finished", 0, (0.5, 0.2), 0),
        (2, "start", 8, 0.1),
        (2, "finished", 0, (0.1, 0.01), 0),
        None,
    ]:
        bot_processes._events.put(event)

    bot_processes._apply_events()

    assert list(bot_state.running) == [8]
    assert bot_processes._replies.get_nowait() == (2, "finished", 0, (0.1, 0.01), 0)
    assert bot_processes._replies.empty()


_POSTGRES_BOT_ERRORS = dict(
    bot_errors=40,
    total_bots_started=400,
    bot_error_kinds={"PostgreSQL out of connections": 40},
)


@pytest.mark.parametrize(
    "unmeasured",
    [
        dict(peak_running=100, p95_response_time=None, **_POSTGRES_BOT_ERRORS),
        dict(peak_running=160, **_POSTGRES_BOT_ERRORS),
        dict(slots_started=160, peak_running=0),
    ],
    ids=["slow-start-and-postgres", "postgres-only", "none-running"],
)
def test_capacity_summary_does_not_suggest_a_cap_when_the_test_could_not_measure(
    unmeasured,
):
    results = [
        _base_result(n_bots=80, p95_response_time=0.085),
        _base_result(n_bots=160, **unmeasured),
    ]

    text = _join(format_capacity_summary(results))

    assert "Capacity: at least 80 concurrent bots" in text
    assert "Cap concurrent" not in text


def test_capacity_summary_says_when_even_the_smallest_count_could_not_be_tested():
    results = [_base_result(n_bots=10, p95_response_time=0.1, **_POSTGRES_BOT_ERRORS)]

    text = _join(format_capacity_summary(results))

    assert "10 bots could not be tested (40 bot errors" in text
    assert "raise max_connections" in text
    assert "Cap concurrent" not in text
    assert "did not keep" not in text


@pytest.mark.parametrize(
    "server_limit, reason",
    [
        (dict(busy_responses=300), "300 busy/stale responses"),
        (dict(p95_response_time=0.9), "p95 response time 900 ms"),
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

    assert "Capacity: about 80 concurrent bots" in text
    assert reason in text
    assert "Cap concurrent participants at about 64" in text


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


def test_each_endpoint_must_stay_within_the_response_time_limit():
    result = _base_result(
        p95_response_time=0.426,
        endpoint_p95={"/timeline": 0.191, "/response": 0.511},
    )

    assert capacity_failures(result) == ["p95 response time for /response 511 ms"]


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


def test_format_test_results_init_times():
    lines = format_test_results(
        _base_result(
            median_init_time=0.2, p95_init_time=0.5, max_init_time=0.5, n_init_samples=4
        )
    )
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
    assert "TIME ON WAIT PAGES PER BOT (n=10 bots" in text


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


# --- format_performance_summary ---


def test_format_performance_summary_single_result():
    lines = format_performance_summary([_base_result()])
    text = _join(lines)
    assert "CUMULATIVE PERFORMANCE TEST SUMMARY" in text
    assert "Req/s" in text
    assert "1.6" in text
    assert "Resp Med (s)" in text
    assert "0.04" in text
    assert "Not measured: uploads over participants' own networks" in text


def test_format_performance_summary_scaling():
    r1 = _base_result(n_bots=1, median_response_time=0.1, q_delay_median=0.05)
    r2 = _base_result(n_bots=2, median_response_time=0.2, q_delay_median=0.1)
    lines = format_performance_summary([r2, r1])
    text = _join(lines)
    assert "2.0x" in text
    assert "\u2014" in text  # baseline marker
    assert "Resp Med vs base" in text and "Q Med vs base" in text
    assert "||" not in text
    rows = [line.split()[0] for line in lines if line.strip()[:1].isdigit()]
    assert rows == ["1", "2"]


def test_prefill_cache_key_changes_with_config_txt(tmp_path, monkeypatch):
    from psynet.perf_reset import experiment_code_key

    monkeypatch.chdir(tmp_path)
    (tmp_path / "deploy.toml").write_text(
        "version = 1\n[exclude]\npaths = []\nnames = []\nsuffixes = []\n"
    )
    (tmp_path / "experiment.py").write_text("")
    (tmp_path / "config.txt").write_text("[Config]\n")
    key = experiment_code_key()
    (tmp_path / "config.txt").write_text("[Config]\n# A comment\n")
    assert experiment_code_key() != key


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


@pytest.mark.parametrize("leader_exited", [True, False])
def test_eperm_from_the_server_group_means_stopped_only_once_its_leader_exited(
    leader_exited,
):
    from itertools import count

    import click

    from psynet.perf_local_server import _stop_process_group

    process = Mock(pid=12345, returncode=0 if leader_exited else None)
    with (
        patch("psynet.perf_local_server.os.killpg", side_effect=PermissionError),
        patch("psynet.perf_local_server.time.monotonic", side_effect=count(0, 20)),
        patch("psynet.perf_local_server.time.sleep"),
    ):
        if leader_exited:
            _stop_process_group(process)
            process.wait.assert_called_once()
        else:
            with pytest.raises(click.ClickException, match="did not stop"):
                _stop_process_group(process)
            process.wait.assert_not_called()


def test_database_copies_need_twice_the_database_size_free(
    caplog, tmp_path, monkeypatch
):
    import psycopg2

    from psynet.isolated_environment import DATABASE_ENV_VAR
    from psynet.perf_reset import DatabaseReset

    monkeypatch.setenv(DATABASE_ENV_VAR, "experiment_test_0")
    reset = DatabaseReset(
        Mock(), Mock(), database_url="postgresql:///experiment_test_0"
    )
    cursor = Mock()
    (tmp_path / "PG_VERSION").write_text("16")
    cursor.fetchone.side_effect = [(1e9,), (str(tmp_path),)]
    with (
        patch("psynet.perf_reset.shutil.disk_usage", return_value=Mock(free=1.5e9)),
        patch("psynet.perf_reset.list_snapshots", return_value=[("s", 3e9, None)]),
        pytest.raises(RuntimeError, match=r"2\.0 GB.*3\.0 GB.*snapshots --drop"),
    ):
        reset._check_disk_space(cursor, "experiment")

    # A data directory in a container, or one PostgreSQL won't show, isn't checked.
    cursor.fetchone.side_effect = [(1e9,), ("/in/a/container",)]
    reset._check_disk_space(cursor, "experiment")
    assert "isn't on this computer" in caplog.text
    cursor.fetchone.side_effect = [(1e9,)]
    cursor.execute.side_effect = [None, psycopg2.Error("permission denied")]
    reset._check_disk_space(cursor, "experiment")


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

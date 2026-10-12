from unittest.mock import Mock, patch

import pytest

from psynet.perf_test import (
    CapacityLimits,
    PerformanceSuite,
    PerformanceTester,
    PerformanceTestResult,
    _BotState,
    _split_failed_requests,
    capacity_failures,
    colorize_success_rate,
    format_capacity_summary,
    format_performance_summary,
    format_test_results,
)
from psynet.pytest_psynet import path_to_test_experiment


def _base_result(**overrides):
    """Return a minimal valid result for format_test_results."""
    fields = {
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
        "key_requests": 10,
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
    from psynet.perf_test import _serve_bot_commands, _ThreadBots

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
    monkeypatch.setattr("psynet.perf_test._fit_redis_pool_to_bots", Mock())
    monkeypatch.setattr("psynet.perf_test._run_bot_process", run_bot_process)
    monkeypatch.setattr(
        "psynet.perf_test.multiprocessing.get_context",
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
    from psynet.perf_test import _choose_bot_processes

    monkeypatch.setattr("psynet.perf_test.os.cpu_count", lambda: cpu_count)
    assert _choose_bot_processes(requested, max_bots) == expected


@pytest.mark.parametrize("url", ["http://localhost:5000", None])
def test_bot_errors_without_a_route_are_still_described(url):
    import requests

    from psynet.perf_test import _describe_bot_error

    response = requests.Response()
    response.status_code = 502
    response.url = url
    assert _describe_bot_error(requests.HTTPError(response=response)) == (
        "HTTP 502 on /"
    )


def test_postgres_running_out_of_connections_is_named_with_advice():
    from psynet.perf_test import _describe_bot_error

    try:
        try:
            raise Exception("FATAL:  sorry, too many clients already")
        except Exception as cause:
            raise RuntimeError("could not create participant") from cause
    except RuntimeError as err:
        kind = _describe_bot_error(err)

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


def test_a_suite_stops_after_a_bot_process_does_not_report():
    tester = PerformanceTester(authenticated_session=Mock(), base_url="http://x")
    result = _base_result(n_bots=10, server_stopped=False, unreported_bot_processes=[2])
    with (
        patch.object(tester, "_test_performance", return_value=result),
        patch("psynet.perf_test.raise_open_file_limit"),
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
        patch("psynet.perf_test.raise_open_file_limit"),
    ):
        PerformanceSuite(tester, before_test=before_test).run([10, 20])

    assert before_test.call_count == 2
    pause.assert_not_called()


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
        patch("psynet.perf_test.raise_open_file_limit"),
        patch("psynet.perf_test._fit_redis_pool_to_bots"),
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
    from psynet.perf_test import _database_rows

    before = _database_rows()
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

    assert _database_rows()["participant"] == before["participant"] + 1


def test_failed_participants_are_classified_by_failed_not_status():
    from types import SimpleNamespace

    from psynet.perf_test import _bot_outcome, _failure_reason

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
    """Record the statements run on a cursor."""

    def __init__(self, cursor, statements):
        self._cursor, self._statements = cursor, statements

    def execute(self, statement, params=None):
        from psycopg2 import sql

        if isinstance(statement, sql.Composable):
            self._statements.append(statement.as_string(self._cursor))
        return self._cursor.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("timeline")],
    indirect=True,
)
def test_database_reset_restores_the_snapshot_and_drops_only_its_own_databases(
    db_session, tmp_path
):
    import re
    import shutil
    import subprocess
    from contextlib import contextmanager

    import psycopg2
    from dallinger import db

    from psynet import perf_reset
    from psynet.isolated_environment import create_database, drop_database
    from psynet.redis import redis_vars

    scratch_url = create_database(
        db.engine.url.render_as_string(hide_password=False), suffix="_reset_scratch"
    )
    scratch = scratch_url.rsplit("/", 1)[1]
    cache = perf_reset.prefill_snapshot_name("0123456789ab", 3, 2)
    statements = []

    class RecordingReset(perf_reset.DatabaseReset):
        @contextmanager
        def _connect(self):
            with super()._connect() as cursor:
                yield _RecordingCursor(cursor, statements)

    def participants(n_new=0):
        connection = psycopg2.connect(scratch_url)
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS participant (id serial)")
                for _ in range(n_new):
                    cursor.execute("INSERT INTO participant DEFAULT VALUES")
                cursor.execute("SELECT count(*) FROM participant")
                return cursor.fetchone()[0]
        finally:
            connection.close()

    participants(1)
    redis_vars.set("launch_finished", True)
    server = Mock()
    snapshots = []
    try:
        reset = RecordingReset(server.stop, server.start, database_url=scratch_url)
        reset()
        snapshots.append(reset.snapshot)
        assert reset.snapshot_rows == {"participant": 1}
        participants(1)
        reset()
        assert participants() == 1
        assert server.stop.call_count == server.start.call_count == 2
        assert redis_vars.get("launch_finished") is True
        reset.close()
        assert perf_reset.find_snapshot(reset.snapshot, scratch_url) is None

        kept = RecordingReset(
            server.stop, server.start, keep_as=cache, database_url=scratch_url
        )
        kept()
        kept.close()
        assert perf_reset.find_snapshot(cache, scratch_url) == cache
        assert cache in [name for name, _, _ in perf_reset.list_snapshots(scratch_url)]
        perf_reset.drop_snapshot(cache, scratch_url)

        dropped = set(
            re.findall(r'DROP DATABASE (?:IF EXISTS )?"([^"]+)"', " ".join(statements))
        )
        assert dropped == {scratch, f"{scratch}__new", reset.snapshot, cache}

        if shutil.which("pg_dump"):
            archive = tmp_path / "snapshot.dump"
            subprocess.run(
                ["pg_dump", "--format=custom", f"--file={archive}", scratch_url],
                check=True,
            )
            participants(2)
            restored = perf_reset.DatabaseReset(
                server.stop,
                server.start,
                from_snapshot=str(archive),
                database_url=scratch_url,
            )
            restored()
            restored.close()
            assert participants() == 1
            assert archive.exists()
    finally:
        with perf_reset._maintenance_cursor(scratch_url) as cursor:
            for name in [scratch, f"{scratch}__new", cache, *snapshots]:
                drop_database(cursor, name)


@pytest.mark.parametrize(
    "url, allowed",
    [
        ("postgresql://u:p@localhost/dallinger_test_5000", True),
        ("postgresql:///dallinger?host=/tmp", True),
        ("postgresql://u:p@localhost/postgres", False),
        ("postgresql://u:p@db.example.org/dallinger", False),
    ],
)
def test_reset_refuses_system_and_remote_databases(url, allowed):
    from psynet.perf_reset import check_resettable_database

    if allowed:
        check_resettable_database(url)
    else:
        with pytest.raises(ValueError, match="Refusing"):
            check_resettable_database(url)


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


def test_capacity_summary_flags_a_pass_above_a_failed_smallest_count():
    results = [
        _base_result(n_bots=10, p95_response_time=0.1, bot_errors=1),
        _base_result(n_bots=20, p95_response_time=0.1),
    ]

    text = _join(format_capacity_summary(results))

    assert "Even 10 bots did not keep" in text
    assert "20 bots passed, so the results are inconsistent" in text


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

    from psynet.perf_test import _LoadMonitor

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

    from psynet.perf_test import _BotProcesses

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
    from decimal import Decimal

    from psynet.perf_test import _to_json_safe

    result = _base_result(endpoint_p95={"/response": Decimal("0.2")})
    saved = json.loads(json.dumps(_to_json_safe(result)))

    assert saved["endpoint_p95"] == {"/response": 0.2}
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
    lines = format_performance_summary([r2, r1])
    text = _join(lines)
    assert "2.0x" in text
    assert "\u2014" in text  # baseline marker
    assert "Resp Med vs base" in text and "Q Med vs base" in text
    assert "||" not in text
    rows = [line.split()[0] for line in lines if line.strip()[:1].isdigit()]
    assert rows == ["1", "2"]


def test_format_performance_summary_returns_list():
    lines = format_performance_summary([_base_result()])
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)


def test_performance_summary_handles_missing_response_metrics():
    result = _base_result(
        total_requests=0,
        avg_response_time=None,
        median_response_time=None,
        p95_response_time=None,
        p99_response_time=None,
        stddev_response_time=None,
        max_response_time=None,
    )
    lines = format_performance_summary([result])
    assert any("N/A" in line for line in lines)


def test_performance_summary_handles_no_completed_or_failed_bots():
    result = _base_result(
        completed_during_test=0,
        total_requests=0,
        median_response_time=None,
        p95_response_time=0.0,
        avg_bot_duration=None,
        avg_init_time=None,
    )
    lines = format_performance_summary([result])
    assert isinstance(lines, list)

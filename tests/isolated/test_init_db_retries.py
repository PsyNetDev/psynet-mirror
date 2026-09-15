import dallinger.db
import pytest
import sqlalchemy.exc

from psynet import pytest_psynet


class FakeDeadlock(Exception):
    pgcode = pytest_psynet.DEADLOCK_PGCODE


class FakeOtherError(Exception):
    pgcode = "55006"  # object_in_use


def operational_error(orig):
    return sqlalchemy.exc.OperationalError("DROP TABLE ...", None, orig)


@pytest.fixture
def terminate_calls(monkeypatch):
    """Replace terminate_other_postgres_connections with a counting stub."""
    calls = []
    monkeypatch.setattr(
        pytest_psynet,
        "terminate_other_postgres_connections",
        lambda: calls.append("terminate"),
    )
    return calls


def test_retries_on_deadlock_then_succeeds(terminate_calls, monkeypatch):
    calls = []

    def fake_init_db(drop_all=False):
        calls.append(drop_all)
        if len(calls) == 1:
            raise operational_error(FakeDeadlock())
        return "session"

    monkeypatch.setattr(dallinger.db, "init_db", fake_init_db)
    assert pytest_psynet.init_db_with_retries(wait_sec=0) == "session"
    assert calls == [True, True]
    # Terminate only after a deadlock, never before the first attempt.
    assert terminate_calls == ["terminate"]


def test_happy_path_does_not_terminate_backends(terminate_calls, monkeypatch):
    monkeypatch.setattr(dallinger.db, "init_db", lambda drop_all=False: "session")
    assert pytest_psynet.init_db_with_retries(wait_sec=0) == "session"
    assert terminate_calls == []


def test_non_deadlock_error_propagates_immediately(terminate_calls, monkeypatch):
    calls = []

    def fake_init_db(drop_all=False):
        calls.append(drop_all)
        raise operational_error(FakeOtherError())

    monkeypatch.setattr(dallinger.db, "init_db", fake_init_db)
    with pytest.raises(sqlalchemy.exc.OperationalError):
        pytest_psynet.init_db_with_retries(wait_sec=0)
    assert len(calls) == 1
    assert terminate_calls == []


def test_persistent_deadlock_raises_after_max_attempts(terminate_calls, monkeypatch):
    calls = []

    def fake_init_db(drop_all=False):
        calls.append(drop_all)
        raise operational_error(FakeDeadlock())

    monkeypatch.setattr(dallinger.db, "init_db", fake_init_db)
    with pytest.raises(sqlalchemy.exc.OperationalError):
        pytest_psynet.init_db_with_retries(max_attempts=3, wait_sec=0)
    assert len(calls) == 3
    # Terminate between attempts only (not after the final failed attempt).
    assert terminate_calls == ["terminate", "terminate"]


def test_deadlock_pgcode_matches_psycopg2_deadlock_class():
    """Pin the driver contract: SQLSTATE 40P01 is psycopg2's DeadlockDetected.

    Green CI pipelines only exercise the no-deadlock path, so if the driver
    ever stopped exposing ``pgcode`` this way, retries would silently stop
    working. This test makes such a change visible.
    """
    import psycopg2.errors

    assert (
        psycopg2.errors.lookup(pytest_psynet.DEADLOCK_PGCODE)
        is psycopg2.errors.DeadlockDetected
    )


def test_stop_debug_experiment_process_still_stops_when_flush_fails(monkeypatch):
    """Flush failures must not skip server/worker shutdown."""
    stop_calls = []

    def fail_flush(*args, **kwargs):
        raise OSError("PTY gone")

    monkeypatch.setattr(pytest_psynet, "flush_output", fail_flush)
    monkeypatch.setattr(
        pytest_psynet,
        "stop_local_debug_process",
        lambda process: stop_calls.append(process),
    )

    process = object()
    pytest_psynet._stop_debug_experiment_process(process)
    assert stop_calls == [process]

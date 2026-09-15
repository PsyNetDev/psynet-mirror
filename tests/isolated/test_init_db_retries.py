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
def no_idle_drain(monkeypatch):
    from psynet import data as data_mod

    monkeypatch.setattr(data_mod, "_IDLE_CLIENT_DRAIN_SEC", 0)


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


def test_drop_foreign_key_constraints_retries_deadlock(monkeypatch):
    """Ingest must retry exclusive FK drops that deadlock with the poller."""
    from psynet import data as data_mod

    calls = {"n": 0}

    class FakeSession:
        def commit(self):
            return None

        def rollback(self):
            return None

        def execute(self, statement):
            calls["n"] += 1
            if calls["n"] == 1:
                raise operational_error(FakeDeadlock())

    monkeypatch.setattr(data_mod.db, "session", FakeSession())
    monkeypatch.setattr(data_mod, "list_fkeys", lambda bind=None: ([object()], []))
    monkeypatch.setattr(data_mod, "DropConstraint", lambda fkey: fkey)
    data_mod._drop_foreign_key_constraints(wait_sec=0)
    assert calls["n"] == 2


class _FakeBegin:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self, execute):
        self._execute = execute
        self.closed = False

    def execute(self, statement):
        return self._execute(statement)

    def begin(self):
        return _FakeBegin()

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _FakeEngine:
    def __init__(self, execute):
        self._execute = execute
        self.connections = []

    def connect(self):
        conn = _FakeConn(self._execute)
        self.connections.append(conn)
        return conn


def _stub_drop_all_session(monkeypatch):
    from psynet import data as data_mod

    class FakeSession:
        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(data_mod.db, "session", FakeSession())
    monkeypatch.setattr(data_mod, "_old_drop_all", lambda bind=None: None)
    monkeypatch.setattr(data_mod, "DropConstraint", lambda fkey: fkey)
    monkeypatch.setattr(data_mod, "DropTable", lambda table: table)


def test_drop_all_db_tables_retries_deadlock(monkeypatch):
    """Leftover exclusive table drops must retry a deadlock."""
    from psynet import data as data_mod

    calls = {"n": 0}

    def execute(statement):
        calls["n"] += 1
        if calls["n"] == 1:
            raise operational_error(FakeDeadlock())

    old_drop_calls = []
    _stub_drop_all_session(monkeypatch)
    monkeypatch.setattr(
        data_mod, "_old_drop_all", lambda bind=None: old_drop_calls.append(bind)
    )
    monkeypatch.setattr(data_mod, "list_fkeys", lambda bind=None: ([], [object()]))
    engine = _FakeEngine(execute)
    data_mod.drop_all_db_tables(bind=engine, wait_sec=0)
    assert calls["n"] == 2
    assert old_drop_calls == [engine]
    assert [conn.closed for conn in engine.connections] == [True, True]


def test_drop_all_db_tables_non_transient_error_propagates(monkeypatch):
    from psynet import data as data_mod

    calls = {"n": 0}

    def execute(statement):
        calls["n"] += 1
        raise operational_error(FakeOtherError())

    _stub_drop_all_session(monkeypatch)
    monkeypatch.setattr(data_mod, "list_fkeys", lambda bind=None: ([], [object()]))
    engine = _FakeEngine(execute)
    with pytest.raises(sqlalchemy.exc.OperationalError):
        data_mod.drop_all_db_tables(bind=engine, wait_sec=0)
    assert calls["n"] == 1
    assert engine.connections[0].closed


def test_drop_all_db_tables_retries_when_old_drop_all_deadlocks(monkeypatch):
    """Enum cleanup after CASCADE must retry the whole drop on deadlock."""
    from psynet import data as data_mod

    calls = {"n": 0, "old": 0}

    def execute(statement):
        calls["n"] += 1

    def old_drop(bind=None):
        calls["old"] += 1
        if calls["old"] == 1:
            raise operational_error(FakeDeadlock())

    _stub_drop_all_session(monkeypatch)
    monkeypatch.setattr(data_mod, "_old_drop_all", old_drop)
    monkeypatch.setattr(data_mod, "list_fkeys", lambda bind=None: ([], [object()]))
    engine = _FakeEngine(execute)
    data_mod.drop_all_db_tables(bind=engine, wait_sec=0)
    assert calls["old"] == 2
    assert calls["n"] == 2


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
    pytest_psynet.stop_debug_experiment_process(process)
    assert stop_calls == [process]


def test_stop_debug_experiment_process_skips_already_closed_process(monkeypatch):
    stop_calls = []
    monkeypatch.setattr(
        pytest_psynet,
        "stop_local_debug_process",
        lambda process: stop_calls.append(process),
    )

    class ClosedProcess:
        closed = True

    pytest_psynet.stop_debug_experiment_process(ClosedProcess())
    assert stop_calls == []


def test_drop_all_refuses_clients_that_appear_during_retry(monkeypatch):
    """Load must not retry DROP TABLE after a live client appears."""
    from psynet import data as data_mod

    calls = {"n": 0, "lists": 0}

    def execute(statement):
        calls["n"] += 1
        raise operational_error(FakeDeadlock())

    def fake_list(release_local=True):
        calls["lists"] += 1
        if calls["lists"] == 1:
            return []
        return [(99, "dallinger", "gunicorn", "active")]

    _stub_drop_all_session(monkeypatch)
    monkeypatch.setattr("psynet.db.list_other_database_clients", fake_list)
    monkeypatch.setattr(data_mod, "list_fkeys", lambda bind=None: ([], [object()]))
    engine = _FakeEngine(execute)
    with data_mod._refuse_other_clients_while_dropping():
        with pytest.raises(data_mod.DatabaseInUseError, match="pid 99"):
            data_mod.drop_all_db_tables(bind=engine, wait_sec=0)
    assert calls["n"] == 1
    assert calls["lists"] == 2


def test_drop_all_retries_deadlock_without_refusing_other_clients(monkeypatch):
    """Generic drop_all (debug, pytest) must still retry leftover locks."""
    from psynet import data as data_mod

    calls = {"n": 0, "lists": 0}

    def execute(statement):
        calls["n"] += 1
        if calls["n"] == 1:
            raise operational_error(FakeDeadlock())

    def fake_list(release_local=True):
        calls["lists"] += 1
        return [(99, "dallinger", "gunicorn", "idle")]

    _stub_drop_all_session(monkeypatch)
    monkeypatch.setattr("psynet.db.list_other_database_clients", fake_list)
    monkeypatch.setattr(data_mod, "list_fkeys", lambda bind=None: ([], [object()]))
    engine = _FakeEngine(execute)
    data_mod.drop_all_db_tables(bind=engine, wait_sec=0)
    assert calls["n"] == 2
    assert calls["lists"] == 0


def test_populate_db_from_zip_file_refuses_listed_clients(
    monkeypatch, tmp_path, no_idle_drain
):
    from psynet import data as data_mod

    dropped = []
    monkeypatch.setattr(
        "psynet.db.list_other_database_clients",
        lambda release_local=True: [(123, "dallinger", "gunicorn", "idle")],
    )
    monkeypatch.setattr(
        data_mod, "init_db", lambda drop_all=False: dropped.append(drop_all)
    )
    monkeypatch.setattr("dallinger.data.ingest_zip", lambda path: dropped.append(path))
    with pytest.raises(data_mod.DatabaseInUseError, match="pid 123"):
        data_mod.populate_db_from_zip_file(str(tmp_path / "export.zip"))
    assert dropped == []


def test_assert_database_idle_drains_then_succeeds(monkeypatch):
    from psynet import data as data_mod

    calls = {"n": 0, "release_local": [], "releases": []}

    def fake_list(release_local=True):
        calls["n"] += 1
        calls["release_local"].append(release_local)
        if calls["n"] == 1:
            return [(1, "dallinger", "", "idle")]
        return []

    monkeypatch.setattr("psynet.db.list_other_database_clients", fake_list)
    monkeypatch.setattr(
        "psynet.db.release_local_database_connections",
        lambda: calls["releases"].append("release"),
    )
    monkeypatch.setattr(data_mod, "_IDLE_CLIENT_POLL_SEC", 0)
    data_mod.assert_database_idle_for_replace(wait_sec=1)
    assert calls["n"] == 2
    assert calls["releases"] == ["release"]
    assert calls["release_local"] == [False, False]


def test_populate_db_from_zip_file_runs_when_idle(monkeypatch, tmp_path):
    from psynet import data as data_mod

    calls = []
    monkeypatch.setattr(
        "psynet.db.list_other_database_clients", lambda release_local=True: []
    )
    monkeypatch.setattr("psynet.db.release_local_database_connections", lambda: None)

    def fake_init(drop_all=False):
        assert data_mod._refuse_other_clients_on_drop.get() is True
        calls.append("init")

    monkeypatch.setattr(data_mod, "init_db", fake_init)
    monkeypatch.setattr("dallinger.data.ingest_zip", lambda path: calls.append(path))
    zip_path = str(tmp_path / "export.zip")
    data_mod.populate_db_from_zip_file(zip_path)
    assert calls == ["init", zip_path]
    assert data_mod._refuse_other_clients_on_drop.get() is False


def test_populate_db_from_zip_file_refuses_a_live_backend(
    monkeypatch, tmp_path, no_idle_drain
):
    from sqlalchemy import create_engine, text

    from psynet import data as data_mod

    dropped = []
    monkeypatch.setattr(
        data_mod, "init_db", lambda drop_all=False: dropped.append(drop_all)
    )
    monkeypatch.setattr("dallinger.data.ingest_zip", lambda path: dropped.append(path))

    other = create_engine(data_mod.db.engine.url)
    conn = other.connect()
    try:
        conn.execute(text("SELECT 1"))
        with pytest.raises(data_mod.DatabaseInUseError, match="other clients"):
            data_mod.populate_db_from_zip_file(str(tmp_path / "export.zip"))
    finally:
        conn.close()
        other.dispose()
    assert dropped == []

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import pytest

from psynet.isolated_environment import (
    DEBUG,
    DEFAULT_DATABASE_URL,
    DEFAULT_REDIS_URL,
    ENV_VAR,
    READY_ENV_VAR,
    TEST,
    IsolatedEnvironment,
    IsolationError,
    _claim_port,
    _spare_redis_database,
    check_no_debug_server,
    shared_environment_warning,
    should_isolate,
    start_redis_server,
)


@pytest.fixture
def drop_new_databases():
    """Drop the databases that the test creates."""
    import psycopg2
    from psycopg2 import sql

    def names(cursor):
        cursor.execute("SELECT datname FROM pg_database")
        return {name for (name,) in cursor.fetchall()}

    connection = psycopg2.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            before = names(cursor)
            yield
            for name in names(cursor) - before:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
                )
    finally:
        connection.close()


def test_should_isolate_respects_opt_out_and_ci():
    assert should_isolate({})
    assert should_isolate({ENV_VAR: "isolated"})
    assert not should_isolate({ENV_VAR: "shared"})
    assert not should_isolate({READY_ENV_VAR: "1"})
    assert not should_isolate({"CI": "true"})
    with pytest.raises(ValueError, match="'isolated'.*'shared'.*'bogus'"):
        should_isolate({ENV_VAR: "bogus"})


def test_shared_environment_warns_once():
    assert "reset" in shared_environment_warning({ENV_VAR: "shared"})
    assert shared_environment_warning({ENV_VAR: "shared", READY_ENV_VAR: "1"}) is None
    assert shared_environment_warning({}) is None


@pytest.mark.parametrize(
    "purpose, newcomer", [(TEST, "the tests"), (DEBUG, "a second debug server")]
)
def test_sessions_refuse_a_directory_that_a_debug_server_serves(
    tmp_path, purpose, newcomer
):
    fake_psynet = tmp_path / "psynet"
    fake_psynet.write_text("import time\ntime.sleep(60)\n")
    process = subprocess.Popen(
        [sys.executable, str(fake_psynet), "debug", "local"], cwd=tmp_path
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                check_no_debug_server(tmp_path, purpose)
            except RuntimeError as e:
                assert f"PID {process.pid}" in str(e)
                assert f"{newcomer} would replace" in str(e)
                break
            time.sleep(0.1)
        else:
            pytest.fail("the debug process was not detected")
        check_no_debug_server(tmp_path / "..")
    finally:
        process.kill()
        process.wait()


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="needs redis-server")
def test_isolated_environment_uses_its_own_services(drop_new_databases):
    shared = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        "REDIS_URL": os.environ.get("REDIS_URL", DEFAULT_REDIS_URL),
        "base_port": os.environ.get("base_port", "5000"),
    }
    with (
        IsolatedEnvironment.start(shared) as first,
        IsolatedEnvironment.start(shared, purpose=DEBUG) as second,
    ):
        for key in ["DATABASE_URL", "REDIS_URL", "base_port"]:
            assert len({shared[key], first.env[key], second.env[key]}) == 3
        assert first.env[READY_ENV_VAR] == "1"
        port = first.env["base_port"]
        database = urlsplit(shared["DATABASE_URL"]).path.lstrip("/")
        assert urlsplit(first.env["DATABASE_URL"]).path == f"/{database}_test_{port}"
        debug_port = second.env["base_port"]
        assert second.env["DATABASE_URL"].endswith(f"/{database}_debug_{debug_port}")
        assert f"export DATABASE_URL={second.env['DATABASE_URL']}" in second.describe()
        redis_port = int(first.env["REDIS_URL"].rsplit(":", 1)[1])
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="needs redis-server")
def test_isolated_environment_skips_ports_whose_redis_port_is_taken(
    drop_new_databases,
):
    with IsolatedEnvironment.start() as probe:
        web_port, redis_url = probe.env["base_port"], probe.env["REDIS_URL"]
    redis_port = int(redis_url.rsplit(":", 1)[1])

    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", redis_port))
        blocker.listen()
        with IsolatedEnvironment.start() as environment:
            assert environment.env["base_port"] != web_port
            assert environment.env["REDIS_URL"] != redis_url
        with pytest.raises(RuntimeError, match="in use"):
            start_redis_server(redis_port, tempfile.gettempdir())


def test_spare_redis_databases_avoid_the_shared_one():
    assert _spare_redis_database("redis://localhost:6379", 0) == 1
    assert _spare_redis_database("redis://localhost:6379", 1) == 2
    assert _spare_redis_database("redis://localhost:6379/1", 0) == 0


def test_a_failed_debug_start_says_to_drop_isolated():
    assert "without --isolated" in str(IsolationError("no port", DEBUG))


def test_a_failed_start_explains_how_to_opt_out():
    unreachable = "postgresql://dallinger:dallinger@127.0.0.1:1/dallinger"

    environ = {**os.environ, "DATABASE_URL": unreachable}
    free_port, lock = _claim_port(int(environ.get("base_port", 5000)) + 100)
    lock.close()

    with pytest.raises(IsolationError, match=f"{ENV_VAR}=shared") as error:
        IsolatedEnvironment.start(environ)

    assert isinstance(error.value.__cause__, RuntimeError)
    port, lock = _claim_port(free_port)
    lock.close()
    assert port == free_port, "the failed start kept its port claim"

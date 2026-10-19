import os
import shutil
import socket
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from psynet.isolated_environment import (
    DEFAULT_DATABASE_URL,
    DEFAULT_REDIS_URL,
    ENV_VAR,
    READY_ENV_VAR,
    IsolatedEnvironment,
    IsolationError,
    _claim_port,
    _spare_redis_database,
    postgres_connection_limit_message,
    shared_environment_warning,
    should_isolate,
    start_redis_server,
    try_lock,
)
from psynet.testing.locks import (
    HELD_LOCK_ENV_VAR,
    SERVER,
    TEST_SESSION,
    DirectoryInUseError,
    check_no_server,
    experiment_directory_lock,
)


def _database_exists(database_url):
    import psycopg2

    parts = urlsplit(database_url)
    shared = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    connection = psycopg2.connect(shared)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (parts.path.lstrip("/"),),
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


def test_should_isolate_respects_opt_out_and_ci():
    assert should_isolate({})
    assert should_isolate({ENV_VAR: "isolated"})
    assert not should_isolate({ENV_VAR: "shared"})
    assert not should_isolate({READY_ENV_VAR: "1"})
    assert not should_isolate({"CI": "true"})
    assert should_isolate({"CI": "false"})
    with pytest.raises(ValueError, match="'isolated'.*'shared'.*'bogus'"):
        should_isolate({ENV_VAR: "bogus"})


def test_shared_environment_warns_once():
    assert "reset" in shared_environment_warning({ENV_VAR: "shared"})
    assert shared_environment_warning({ENV_VAR: "shared", READY_ENV_VAR: "1"}) is None
    assert shared_environment_warning({}) is None


@pytest.mark.parametrize(
    "holder, kind", [(SERVER, TEST_SESSION), (SERVER, SERVER), (TEST_SESSION, SERVER)]
)
def test_servers_and_tests_refuse_a_directory_that_the_other_holds(
    tmp_path, monkeypatch, holder, kind
):
    """Tests wait only for other tests; anything else in the directory is refused."""
    monkeypatch.delenv(HELD_LOCK_ENV_VAR, raising=False)
    with experiment_directory_lock(tmp_path, export=False, kind=holder):
        message = rf"A PsyNet {holder} \(PID {os.getpid()}\) is using"
        with pytest.raises(DirectoryInUseError, match=message):
            with experiment_directory_lock(tmp_path, kind=kind):
                pass
        if holder == SERVER:
            with pytest.raises(DirectoryInUseError, match=message):
                check_no_server(tmp_path)
        else:
            check_no_server(tmp_path)
    with experiment_directory_lock(tmp_path, kind=kind):
        check_no_server(tmp_path)


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="needs redis-server")
def test_isolated_environment_uses_its_own_services():
    shared = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        "REDIS_URL": os.environ.get("REDIS_URL", DEFAULT_REDIS_URL),
        "base_port": os.environ.get("base_port", "5000"),
    }
    with (
        IsolatedEnvironment.start(shared) as first,
        IsolatedEnvironment.start(shared) as second,
    ):
        for key in ["DATABASE_URL", "REDIS_URL", "base_port"]:
            assert len({shared[key], first.env[key], second.env[key]}) == 3
        assert first.env[READY_ENV_VAR] == "1"
        port = first.env["base_port"]
        database = urlsplit(shared["DATABASE_URL"]).path.lstrip("/")
        assert urlsplit(first.env["DATABASE_URL"]).path == f"/{database}_test_{port}"
        assert _database_exists(first.env["DATABASE_URL"])
        redis_port = int(first.env["REDIS_URL"].rsplit(":", 1)[1])
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()
        develop_directory = Path(first.env["dallinger_develop_directory"])
        develop_directory.mkdir(exist_ok=True)

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()
    assert not develop_directory.exists()
    assert not _database_exists(first.env["DATABASE_URL"])


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="needs redis-server")
def test_isolated_environment_skips_ports_whose_redis_port_is_taken():
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
            start_redis_server(redis_port)


def test_port_claims_skip_symlinked_lock_files(tmp_path, monkeypatch):
    target = tmp_path / "precious"
    target.write_text("keep me")
    (tmp_path / "6990.lock").symlink_to(target)
    monkeypatch.setattr(
        "psynet.isolated_environment.port_lock_path",
        lambda port: str(tmp_path / f"{port}.lock"),
    )

    port, lock = _claim_port(6990)
    lock.close()

    assert port != 6990
    assert target.read_text() == "keep me"


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root can open read-only files for writing",
)
def test_read_only_lock_files_still_lock(tmp_path):
    """Another user's lock file can't be opened for writing, but still locks."""
    path = tmp_path / "other-user.lock"
    path.touch(mode=0o444)

    with try_lock(str(path)) as lock:
        assert not lock.writable()
        assert try_lock(str(path)) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs os.mkfifo")
def test_lock_files_must_be_regular_files(tmp_path):
    os.mkfifo(tmp_path / "fifo.lock", 0o444)
    with pytest.raises(OSError, match="not a regular file"):
        try_lock(str(tmp_path / "fifo.lock"))


def test_spare_redis_databases_avoid_the_shared_one():
    assert _spare_redis_database("redis://localhost:6379", 0) == 1
    assert _spare_redis_database("redis://localhost:6379", 1) == 2
    assert _spare_redis_database("redis://localhost:6379/1", 0) == 0


def test_spare_redis_database_is_emptied_when_the_session_ends(monkeypatch):
    import redis

    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda cmd: None if cmd == "redis-server" else real_which(cmd)
    )
    with IsolatedEnvironment.start() as environment:
        url = environment.env["REDIS_URL"]
        redis.Redis.from_url(url).set("left-by-test", "1")
    assert not redis.Redis.from_url(url).exists("left-by-test")


def test_description_hides_the_redis_password():
    environment = IsolatedEnvironment(
        {
            "DATABASE_URL": "postgresql://u:p@localhost/dallinger_test_5100",
            "REDIS_URL": "redis://:secret@redis.example:6380/3",
            "base_port": "5100",
        }
    )

    description = environment.describe()

    assert "Redis at redis.example:6380/3," in description
    assert "secret" not in description


def test_a_failed_start_explains_how_to_opt_out(tmp_path, monkeypatch):
    unreachable = "postgresql://dallinger:dallinger@127.0.0.1:1/dallinger"
    monkeypatch.setattr(
        "psynet.isolated_environment.port_lock_path",
        lambda port: str(tmp_path / f"{port}.lock"),
    )

    environ = {**os.environ, "DATABASE_URL": unreachable}
    free_port, lock = _claim_port(int(environ.get("base_port", 5000)) + 100)
    lock.close()

    with pytest.raises(IsolationError, match=f"{ENV_VAR}=shared") as error:
        IsolatedEnvironment.start(environ)

    assert isinstance(error.value.__cause__, RuntimeError)
    port, lock = _claim_port(free_port)
    lock.close()
    assert port == free_port, "the failed start kept its port claim"


@pytest.mark.parametrize(
    "server_error",
    [
        "FATAL:  sorry, too many clients already",
        "FATAL:  remaining connection slots are reserved for non-replication "
        "superuser connections",
    ],
)
def test_running_out_of_postgres_connections_is_explained(server_error):
    message = str(IsolationError(RuntimeError(f"Could not connect: {server_error}")))

    assert server_error in message
    assert "PostgreSQL server has run out of connections" in message
    assert "max_connections" in message
    assert f"{ENV_VAR}=shared" not in message, "opting out would not help"
    assert postgres_connection_limit_message("database does not exist") is None


@pytest.mark.skipif(not shutil.which("redis-server"), reason="needs redis-server")
def test_a_failed_redis_start_drops_the_new_database(monkeypatch):
    import psynet.isolated_environment as isolated_environment

    created = []
    create_database = isolated_environment.create_database

    def recording_create_database(*args, **kwargs):
        created.append(create_database(*args, **kwargs))
        return created[-1]

    def failing_redis(*args, **kwargs):
        raise RuntimeError("Redis did not start.")

    monkeypatch.setattr(
        isolated_environment, "create_database", recording_create_database
    )
    monkeypatch.setattr(isolated_environment, "start_redis_server", failing_redis)

    with pytest.raises(IsolationError, match="Redis did not start"):
        IsolatedEnvironment.start()

    assert len(created) == 1
    assert not _database_exists(created[0])

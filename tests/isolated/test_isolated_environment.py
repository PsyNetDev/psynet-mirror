import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

import psynet
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
    without_session_settings,
)


def test_should_isolate_respects_opt_out_and_ci():
    assert should_isolate({})
    assert should_isolate({ENV_VAR: "isolated"})
    assert not should_isolate({ENV_VAR: "shared"})
    assert not should_isolate({READY_ENV_VAR: "1"})
    assert not should_isolate({"CI": "true"})
    assert should_isolate({"CI": "false"})
    with pytest.raises(ValueError, match="'isolated'.*'shared'.*'bogus'"):
        should_isolate({ENV_VAR: "bogus"})


def test_new_sessions_ignore_an_exported_debug_session():
    exported = {
        "DATABASE_URL": "postgresql://u:p@localhost/dallinger_debug_5100",
        "REDIS_URL": "redis://127.0.0.1:6479",
        "base_port": "5100",
        "OTHER": "kept",
    }
    assert without_session_settings(exported) == {
        "DATABASE_URL": "postgresql://u:p@localhost/dallinger",
        "OTHER": "kept",
    }
    plain = {"DATABASE_URL": "postgresql://u:p@localhost/study_2", "base_port": "5200"}
    assert without_session_settings(plain) == plain


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
    """A user's debug server is refused; one that a test session started isn't."""
    from psynet.testing.locks import HELD_LOCK_ENV_VAR

    fake_psynet = tmp_path / "psynet"
    fake_psynet.write_text("import time\ntime.sleep(60)\n")
    shell = {k: v for k, v in os.environ.items() if k != HELD_LOCK_ENV_VAR}

    def spawn(env):
        return subprocess.Popen(
            [sys.executable, str(fake_psynet), "debug", "local"], cwd=tmp_path, env=env
        )

    test_server = spawn({**shell, HELD_LOCK_ENV_VAR: str(tmp_path)})
    processes = [test_server]
    try:
        time.sleep(0.5)
        check_no_debug_server(tmp_path, purpose)
        user_server = spawn(shell)
        processes.append(user_server)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                check_no_debug_server(tmp_path, purpose)
            except RuntimeError as e:
                assert f"PID {user_server.pid}" in str(e)
                assert f"{newcomer} would replace" in str(e)
                break
            time.sleep(0.1)
        else:
            pytest.fail("the debug process was not detected")
        check_no_debug_server(tmp_path / "..")
    finally:
        for process in processes:
            process.kill()
            process.wait()


def test_a_debug_server_is_not_refused_by_its_own_wrapper(tmp_path):
    """``timeout 60 psynet debug local`` doesn't count as a server in its directory."""
    wrapper = tmp_path / "psynet"
    wrapper.write_text(
        "import subprocess, sys\n"
        "check = 'from psynet.isolated_environment import check_no_debug_server as c; c(\".\")'\n"
        "sys.exit(subprocess.run([sys.executable, '-c', check]).returncode)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(psynet.__file__).parents[1])}
    result = subprocess.run(
        [sys.executable, str(wrapper), "debug", "local"], cwd=tmp_path, env=env
    )
    assert result.returncode == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux only")
def test_children_stop_when_their_caller_is_killed(tmp_path):
    """A SIGKILLed launcher still stops its Redis server and re-run command."""
    import psutil

    pid_file = tmp_path / "child.pid"
    caller = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, time\n"
            "from psynet.isolated_environment import sigterm_on_caller_exit\n"
            "child = subprocess.Popen(['sleep', '60'], "
            "preexec_fn=sigterm_on_caller_exit())\n"
            f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)\n",
        ],
        env={**os.environ, "PYTHONPATH": str(Path(psynet.__file__).parents[1])},
    )
    deadline = time.monotonic() + 30
    while not pid_file.exists() or not pid_file.read_text():
        assert time.monotonic() < deadline, "child process did not start"
        time.sleep(0.1)
    child = psutil.Process(int(pid_file.read_text()))
    caller.kill()
    caller.wait()
    child.wait(timeout=10)


@pytest.mark.skipif(shutil.which("redis-server") is None, reason="needs redis-server")
def test_isolated_environment_uses_its_own_services():
    url = urlsplit(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    database = re.sub(r"_(test|debug)_\d+$", "", url.path.lstrip("/"))
    shared = {
        "DATABASE_URL": urlunsplit(url._replace(path=f"/{database}")),
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
        assert urlsplit(first.env["DATABASE_URL"]).path == f"/{database}_test_{port}"
        debug_port = second.env["base_port"]
        assert second.env["DATABASE_URL"].endswith(f"/{database}_debug_{debug_port}")
        assert _database_exists(shared, first.env["DATABASE_URL"])
        assert _database_exists(shared, second.env["DATABASE_URL"])
        assert f"export DATABASE_URL={second.env['DATABASE_URL']}" in second.describe()
        redis_port = int(first.env["REDIS_URL"].rsplit(":", 1)[1])
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()
        develop_directory = Path(first.env["dallinger_develop_directory"])
        develop_directory.mkdir(exist_ok=True)

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()
    assert not develop_directory.exists()
    assert not _database_exists(shared, first.env["DATABASE_URL"])
    assert not _database_exists(shared, second.env["DATABASE_URL"])
    assert "were removed" in second.stopped_message()


def _database_exists(shared, database_url):
    import psycopg2

    connection = psycopg2.connect(shared["DATABASE_URL"])
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (urlsplit(database_url).path.lstrip("/"),),
            )
            return cursor.fetchone() is not None
    finally:
        connection.close()


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
            start_redis_server(redis_port, tempfile.gettempdir())


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


def test_spare_redis_databases_avoid_the_shared_one():
    assert _spare_redis_database("redis://localhost:6379", 0) == 1
    assert _spare_redis_database("redis://localhost:6379", 1) == 2
    assert _spare_redis_database("redis://localhost:6379/1", 0) == 0


def test_a_failed_debug_start_warns_what_dropping_isolated_does():
    message = str(IsolationError("no port", DEBUG))
    assert "Without --isolated" in message and "resets them" in message


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

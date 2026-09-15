"""Tests for local PostgreSQL/Redis service checks and ensure helpers."""

from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner

from psynet.command_line import psynet
from psynet.services import (
    ServiceCheck,
    ensure_local_services,
    verify_local_services,
)


def _ok_checks():
    return [
        ServiceCheck("PostgreSQL", True, "reachable"),
        ServiceCheck("Redis", True, "responded to PING"),
    ]


def _down_checks():
    return [
        ServiceCheck("PostgreSQL", False, "connection refused"),
        ServiceCheck("Redis", False, "connection refused"),
    ]


def test_services_check_succeeds_when_healthy(monkeypatch):
    monkeypatch.setattr(
        "psynet.services.check_local_services",
        _ok_checks,
    )
    result = CliRunner().invoke(psynet, ["services", "check"])
    assert result.exit_code == 0, result.output
    assert "PostgreSQL: OK" in result.output
    assert "Redis: OK" in result.output


def test_services_check_fails_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        "psynet.services.check_local_services",
        _down_checks,
    )
    result = CliRunner().invoke(psynet, ["services", "check"])
    assert result.exit_code != 0
    assert "psynet services ensure" in result.output


def test_services_ensure_starts_when_needed(monkeypatch):
    calls = {"checks": 0, "started": False}

    def fake_checks():
        calls["checks"] += 1
        if calls["started"]:
            return _ok_checks()
        return _down_checks()

    monkeypatch.setattr("psynet.services.check_local_services", fake_checks)
    monkeypatch.setattr("psynet.services._is_interactive", lambda: False)

    def fake_start():
        calls["started"] = True

    monkeypatch.setattr("psynet.services.start_local_services_via_docker", fake_start)
    monkeypatch.setattr(
        "psynet.services._wait_until_services_ready",
        lambda timeout_seconds=30: _ok_checks(),
    )

    result = CliRunner().invoke(psynet, ["services", "ensure", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls["started"] is True
    assert "Local services are ready." in result.output


def test_services_ensure_noninteractive_requires_yes(monkeypatch):
    monkeypatch.setattr("psynet.services.check_local_services", _down_checks)
    monkeypatch.setattr("psynet.services._is_interactive", lambda: False)
    monkeypatch.setattr(
        "psynet.services.start_local_services_via_docker",
        lambda: pytest.fail("must not start without --yes"),
    )

    result = CliRunner().invoke(psynet, ["services", "ensure"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_verify_local_services_soft_warns(monkeypatch):
    monkeypatch.setattr("psynet.services.check_local_services", _down_checks)
    assert verify_local_services(strict=False) is False


def test_verify_local_services_strict_raises(monkeypatch):
    monkeypatch.setattr("psynet.services.check_local_services", _down_checks)
    with pytest.raises(click.ClickException, match="psynet services ensure"):
        verify_local_services(strict=True)


def test_ensure_local_services_soft_does_not_raise(monkeypatch):
    monkeypatch.setattr("psynet.services.check_local_services", _down_checks)
    monkeypatch.setattr("psynet.services._is_interactive", lambda: False)
    assert ensure_local_services(assume_yes=False, strict=False) is False


def test_check_redis_ping_over_socket(monkeypatch):
    """Redis probe uses stdlib RESP PING, not the redis package."""
    from psynet.services import check_redis

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, data):
            assert data == b"*1\r\n$4\r\nPING\r\n"

        def recv(self, _size):
            return b"+PONG\r\n"

    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    result = check_redis()
    assert result.ok
    assert "PONG" in result.detail.upper() or "PING" in result.detail.upper()


def test_check_redis_tolerates_fragmented_response(monkeypatch):
    """TCP may split ``+PONG`` across reads; that is a healthy service."""
    from psynet.services import check_redis

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    fragments = iter([b"+PO", b"NG\r\n"])

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, _data):
            pass

        def recv(self, _size):
            return next(fragments)

    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    assert check_redis().ok


def test_check_redis_closes_socket_when_tls_wrap_fails(monkeypatch):
    """A failed TLS handshake must not leak the underlying socket."""
    import ssl as ssl_module

    from psynet.services import check_redis

    monkeypatch.setenv("REDIS_URL", "rediss://localhost:6379")
    closed = []

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append("context-exit")
            return False

        def close(self):
            closed.append("close")

    def failing_wrap(self, sock, server_hostname=None):
        raise ssl_module.SSLError("handshake failed")

    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    monkeypatch.setattr(ssl_module.SSLContext, "wrap_socket", failing_wrap)

    assert not check_redis().ok
    assert closed, "the raw socket must be released when TLS wrapping fails"


def test_check_postgres_fallback_tolerates_fragmented_header(monkeypatch):
    """The PostgreSQL probe must reassemble a split five-byte header."""
    import builtins
    import struct

    from psynet.services import check_postgres

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://dallinger:dallinger@localhost/dallinger"
    )
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg2":
            raise ImportError("no psycopg2 in thin bootstrap")
        return real_import(name, *args, **kwargs)

    header = b"R" + struct.pack("!I", 8)
    fragments = iter([header[:2], header[2:]])

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, _data):
            pass

        def recv(self, size):
            return next(fragments)[:size]

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("psynet.services.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    assert check_postgres().ok


def test_check_redis_honors_auth_and_database(monkeypatch):
    """Redis URLs retain authentication, decoding, and database semantics."""
    from psynet.services import check_redis

    commands = []
    responses = iter([b"+OK\r\n", b"+OK\r\n", b"+PONG\r\n"])

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, data):
            commands.append(data)

        def recv(self, _size):
            return next(responses)

    monkeypatch.setenv("REDIS_URL", "redis://user:p%40ss@redis.example:6380/2")
    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )

    assert check_redis().ok
    assert commands == [
        b"*3\r\n$4\r\nAUTH\r\n$4\r\nuser\r\n$4\r\np@ss\r\n",
        b"*2\r\n$6\r\nSELECT\r\n$1\r\n2\r\n",
        b"*1\r\n$4\r\nPING\r\n",
    ]


def test_check_redis_requires_exact_pong(monkeypatch):
    """A non-Redis listener mentioning PONG must not pass the probe."""
    from psynet.services import check_redis

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, _data):
            pass

        def recv(self, _size):
            return b"HTTP/1.1 200 PONG\r\n"

    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    assert not check_redis().ok


def test_check_postgres_falls_back_to_pg_isready(monkeypatch):
    """Without psycopg2, thin bootstrap uses pg_isready when available."""
    import builtins

    from psynet.services import check_postgres

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg2":
            raise ImportError("no psycopg2 in thin bootstrap")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        "psynet.services.shutil.which", lambda name: "/usr/bin/pg_isready"
    )

    from psynet.services import _postgres_url

    def fake_run(args, **kwargs):
        assert args == ["pg_isready", "-d", _postgres_url(), "-t", "3"]
        result = Mock()
        result.returncode = 0
        result.stdout = "accepting connections\n"
        result.stderr = ""
        return result

    monkeypatch.setattr("psynet.services.subprocess.run", fake_run)
    result = check_postgres()
    assert result.ok
    assert "pg_isready" in result.detail


def test_check_postgres_fallback_validates_protocol(monkeypatch):
    """An unrelated open TCP port must not pass as PostgreSQL."""
    import builtins

    from psynet.services import check_postgres

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg2":
            raise ImportError("no psycopg2 in thin bootstrap")
        return real_import(name, *args, **kwargs)

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, _data):
            pass

        def recv(self, _size):
            return b"HTTP/"

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("psynet.services.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    assert not check_postgres().ok


def test_check_postgres_fallback_accepts_protocol_response(monkeypatch):
    """The stdlib fallback recognizes a framed PostgreSQL auth response."""
    import builtins
    import struct

    from psynet.services import check_postgres

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://dallinger:dallinger@localhost/dallinger"
    )
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg2":
            raise ImportError("no psycopg2 in thin bootstrap")
        return real_import(name, *args, **kwargs)

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def sendall(self, data):
            assert b"user\x00dallinger\x00database\x00dallinger\x00" in data

        def recv(self, _size):
            return b"R" + struct.pack("!I", 8)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("psynet.services.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "psynet.services.socket.create_connection",
        lambda address, timeout: FakeSock(),
    )
    assert check_postgres().ok


def test_leftover_volume_does_not_look_like_a_container(monkeypatch):
    """A volume sharing the container name must not trigger 'docker start'."""
    from psynet.services import _ensure_docker_container

    commands = []

    def fake_run(args, **kwargs):
        commands.append(args)
        result = Mock()
        # Only volumes remain, so container-scoped inspects fail.
        result.returncode = 1 if "inspect" in args else 0
        result.stdout = ""
        result.stderr = ""
        return result

    monkeypatch.setattr("psynet.services.subprocess.run", fake_run)

    _ensure_docker_container("dallinger_redis", ["run", "-d", "redis"])

    inspect_commands = [args for args in commands if "inspect" in args]
    assert inspect_commands
    for args in inspect_commands:
        assert args[:3] == ["docker", "container", "inspect"]
    assert ["docker", "start", "dallinger_redis"] not in commands
    assert ["docker", "run", "-d", "redis"] in commands


def test_pre_launch_ensures_services_for_docker_mode(monkeypatch):
    """Docker launches still prepare locally, so services are required here too."""
    from psynet.command_line import _pre_launch

    ensure = Mock()
    monkeypatch.setattr("psynet.services.ensure_local_services", ensure)
    monkeypatch.setattr(
        "psynet.command_line._check_experiment_directory", lambda mode, **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.redis_vars.clear",
        Mock(side_effect=RuntimeError("stop-after-redis")),
    )

    ctx = Mock()
    with pytest.raises(RuntimeError, match="stop-after-redis"):
        _pre_launch(
            ctx,
            mode="debug",
            archive=None,
            local_=True,
            docker=True,
        )

    ensure.assert_called_once_with(assume_yes=False, strict=True)


def test_pre_launch_ensures_services_for_local_venv_mode(monkeypatch):
    from psynet.command_line import _pre_launch

    ensure = Mock()
    monkeypatch.setattr("psynet.services.ensure_local_services", ensure)
    monkeypatch.setattr(
        "psynet.command_line._check_experiment_directory", lambda mode, **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.redis_vars.clear",
        Mock(side_effect=RuntimeError("stop-after-redis")),
    )

    ctx = Mock()
    with pytest.raises(RuntimeError, match="stop-after-redis"):
        _pre_launch(
            ctx,
            mode="debug",
            archive=None,
            local_=True,
            docker=False,
        )

    ensure.assert_called_once_with(assume_yes=False, strict=True)


def test_pre_launch_ensures_services_for_ssh_deploy(monkeypatch):
    """SSH deploy still prepares against local Postgres/Redis."""
    from psynet.command_line import _pre_launch

    ensure = Mock()
    monkeypatch.setattr("psynet.services.ensure_local_services", ensure)
    monkeypatch.setattr(
        "psynet.command_line._check_experiment_directory", lambda mode, **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.redis_vars.clear",
        Mock(side_effect=RuntimeError("stop-after-redis")),
    )

    ctx = Mock()
    with pytest.raises(RuntimeError, match="stop-after-redis"):
        _pre_launch(
            ctx,
            mode="live",
            archive=None,
            local_=False,
            ssh=True,
            docker=True,
            server="test-server",
            app="test-app",
        )

    ensure.assert_called_once_with(assume_yes=False, strict=True)


def test_test_local_ensures_services(monkeypatch):
    """``psynet test local`` must ensure Postgres/Redis like local debug/deploy."""
    from psynet.command_line import test__local

    ensure = Mock()
    experiment = Mock()
    monkeypatch.setattr("psynet.services.ensure_local_services", ensure)
    monkeypatch.setattr(
        "psynet.command_line._check_experiment_directory", lambda mode, **kwargs: None
    )
    monkeypatch.setattr(
        "psynet.experiment.get_experiment",
        lambda: experiment,
    )
    monkeypatch.setattr("pytest.main", lambda args: 0)

    result = CliRunner().invoke(test__local, [])
    assert result.exit_code == 0, result.output
    ensure.assert_called_once_with(assume_yes=False, strict=True)

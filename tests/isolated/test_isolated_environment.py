import os
import shutil
import socket
from urllib.parse import urlsplit

import pytest

from psynet.isolated_environment import (
    DEFAULT_DATABASE_URL,
    DEFAULT_REDIS_URL,
    ENV_VAR,
    IsolatedEnvironment,
    should_isolate,
)


def test_should_isolate_respects_opt_out_and_ci():
    assert should_isolate({})
    assert not should_isolate({ENV_VAR: "shared"})
    assert not should_isolate({ENV_VAR: "isolated"})
    assert not should_isolate({"CI": "true"})


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
        assert first.env[ENV_VAR] == "isolated"
        port = first.env["base_port"]
        database = urlsplit(shared["DATABASE_URL"]).path.lstrip("/")
        assert urlsplit(first.env["DATABASE_URL"]).path == f"/{database}_test_{port}"
        redis_port = int(first.env["REDIS_URL"].rsplit(":", 1)[1])
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()


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

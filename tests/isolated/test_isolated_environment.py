import os
import shutil
import socket

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
        assert first.env["DATABASE_URL"] == f"{shared['DATABASE_URL']}_test_{port}"
        redis_port = int(first.env["REDIS_URL"].rsplit(":", 1)[1])
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()

    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", redis_port), timeout=1).close()

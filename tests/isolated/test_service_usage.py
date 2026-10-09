"""Tests for ``psynet services list``."""

import json
import os
import subprocess
import sys
import tempfile
import time

import psutil
from click.testing import CliRunner

from psynet.bootstrap_commands import services_list
from psynet.service_usage import (
    Database,
    RedisServer,
    Session,
    _session_command,
    find_redis_folders,
    find_sessions,
    leftovers,
)


def test_find_sessions_reads_settings_from_running_processes(tmp_path):
    """An isolated launcher and the child it reruns form one session."""
    script = tmp_path / "psynet"
    script.write_text(
        "import json, os, subprocess, sys, time\n"
        "if 'CHILD_ENV' in os.environ:\n"
        "    env = json.loads(os.environ.pop('CHILD_ENV'))\n"
        "    subprocess.run([sys.executable, *sys.argv], env={**os.environ, **env})\n"
        "time.sleep(60)\n"
    )
    child_env = {
        "base_port": "5987",
        "DATABASE_URL": "postgresql://dallinger:dallinger@localhost/dallinger_x",
        "REDIS_URL": "redis://localhost:6987",
        "_PSYNET_TEST_ENVIRONMENT_READY": "1",
    }
    env = {**os.environ, "base_port": "5986", "CHILD_ENV": json.dumps(child_env)}
    process = subprocess.Popen(
        [sys.executable, str(script), "debug", "local"], env=env, cwd=tmp_path
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            matches = [s for s in find_sessions() if s.base_port in ("5986", "5987")]
            if matches and len(matches[0].pids) == 2:
                break
            time.sleep(0.1)
        [session] = matches
        assert (session.base_port, session.database) == ("5987", "dallinger_x")
        assert session.redis_port == 6987
        assert session.pids[0] == process.pid and len(session.pids) == 2
        assert session.command == "psynet debug local"
        assert session.directory == str(tmp_path)
    finally:
        for child in psutil.Process(process.pid).children():
            child.kill()
        process.kill()
        process.wait()


def test_session_command_recognises_scripts_and_python_modules():
    assert _session_command(["/venv/bin/psynet", "debug", "local"]) == [
        "psynet",
        "debug",
        "local",
    ]
    assert _session_command(
        ["python3", "-W", "ignore", "-X", "dev", "-m", "pytest"]
    ) == ["pytest"]
    assert _session_command(["python3", "/venv/bin/dallinger_heroku_worker"]) == [
        "dallinger_heroku_worker"
    ]
    assert _session_command(["python3", "manage.py", "psynet"]) is None
    assert _session_command(["bash"]) is None


def test_leftovers_are_unused_session_databases_redis_servers_and_folders():
    sessions = [Session("5100", "dallinger_test_5100", 6400)]
    databases = [
        Database("dallinger", 0),
        Database("dallinger_test_5100", 0),
        Database("dallinger_test_5110", 0),
        Database("dallinger_debug_5130", 0),
        Database("dallinger_test_5120", 1),
        Database("dallinger_slot2", 0),
        Database("attention_test_1", 0),
        Database("pilot_test_2020_extra", 0),
        Database("study_test_2024", 0),
        Database("survey_debug_2023", 0),
    ]
    redis_servers = [
        RedisServer(1, 6379, "/", started_by_psynet=False, own=True, clients=0),
        RedisServer(2, 6400, "/tmp/a", started_by_psynet=True, own=True, clients=0),
        RedisServer(3, 6410, "/tmp/b", started_by_psynet=True, own=True, clients=0),
        RedisServer(4, 6420, "/tmp/c", started_by_psynet=True, own=False, clients=0),
        RedisServer(5, 6430, "/tmp/d", started_by_psynet=True, own=True, clients=1),
    ]

    folders = ["/tmp/b", "/tmp/psynet-debug-redis-gone"]

    stale_databases, stale_redis, stale_folders = leftovers(
        sessions, redis_servers, databases, folders
    )

    assert [d.name for d in stale_databases] == [
        "dallinger_test_5110",
        "dallinger_debug_5130",
        "dallinger_slot2",
    ]
    assert [r.pid for r in stale_redis] == [3]
    assert stale_folders == ["/tmp/psynet-debug-redis-gone"]

    unknown = RedisServer(6, 6440, "", started_by_psynet=False, own=True, clients=0)
    *_, stale_folders = leftovers(sessions, [*redis_servers, unknown], [], folders)
    assert stale_folders == []


def test_find_redis_folders_skips_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    (tmp_path / "psynet-test-redis-real").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "psynet-test-redis-link").symlink_to(tmp_path / "elsewhere")

    assert find_redis_folders() == [str(tmp_path / "psynet-test-redis-real")]


def test_clean_without_a_terminal_needs_yes(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    folder = tmp_path / "psynet-test-redis-gone"
    folder.mkdir()

    result = CliRunner().invoke(services_list, ["--clean"])

    assert result.exit_code != 0
    assert f"Redis folder {folder}" in result.output
    assert "pass --yes" in result.output
    assert folder.exists()

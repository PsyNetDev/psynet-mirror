"""Tests for ``psynet services list``."""

import fcntl
import json
import os
import subprocess
import sys
import time

import psutil

from psynet.isolated_environment import READY_ENV_VAR
from psynet.service_usage import (
    Database,
    _database_users,
    _session_command,
    find_sessions,
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
        READY_ENV_VAR: "1",
    }
    # Like a shell's: pytest's isolation plugin marks its own environment.
    shell = {k: v for k, v in os.environ.items() if k != READY_ENV_VAR}
    env = {**shell, "base_port": "5986", "CHILD_ENV": json.dumps(child_env)}
    process = subprocess.Popen(
        [sys.executable, str(script), "debug", "local"], env=env, cwd=tmp_path
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            matches = [s for s in find_sessions() if s.directory == str(tmp_path)]
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


def test_databases_of_plain_pytest_sessions_are_found_by_their_port_lock(
    tmp_path, monkeypatch
):
    """Plain pytest sessions are invisible in process environments; their lock isn't."""
    monkeypatch.setattr(
        "psynet.service_usage.port_lock_path", lambda port: str(tmp_path / port)
    )
    database = Database("dallinger_test_6990", 0)
    assert _database_users(database, []) == "no session"
    with open(tmp_path / "6990", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert _database_users(database, []) == "a session holding port 6990"
    assert _database_users(Database("study_test_1", 0), []) == "no session"

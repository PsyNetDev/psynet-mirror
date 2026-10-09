"""Tests for ``psynet services list``."""

import fcntl
import json
import os
import subprocess
import sys
import time

import psutil
from click.testing import CliRunner

from psynet.bootstrap_commands import services_list
from psynet.isolated_environment import READY_ENV_VAR
from psynet.service_usage import (
    Database,
    Session,
    _session_command,
    find_databases,
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


def test_leftovers_are_unused_session_databases():
    sessions = [Session("5100", "dallinger_test_5100", 6400)]
    databases = [
        Database("dallinger", 0),
        Database("dallinger_test_5100", 0),
        Database("dallinger_test_5110", 0),
        Database("dallinger_test_5140", 0),
        Database("dallinger_debug_5130", 0),
        Database("dallinger_test_5120", 1),
        Database("dallinger_slot2", 0),
        Database("booking_test_6000", 0),
        Database("dallinger_test_70000", 0),
        Database("attention_test_1", 0),
        Database("pilot_test_2020_extra", 0),
        Database("study_test_2024", 0),
        Database("survey_debug_2023", 0),
    ]

    stale = leftovers(sessions, databases, in_use={"dallinger_test_5140"})

    assert [d.name for d in stale] == ["dallinger_test_5110", "dallinger_debug_5130"]


def test_clean_keeps_a_database_whose_port_lock_is_held_or_unreadable(
    tmp_path, monkeypatch, capsys
):
    """Plain pytest sessions are invisible in process environments; their lock isn't."""
    from psynet.service_usage import _clean, _cursor

    lock_path = tmp_path / "6990.lock"
    monkeypatch.setattr(
        "psynet.service_usage.port_lock_path", lambda port: str(lock_path)
    )
    name = "psynet_services_test_6990"
    with _cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS {name}")
        cursor.execute(f"CREATE DATABASE {name}")
    try:
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _clean([Database(name, 0)])
        lock_path.unlink()
        lock_path.symlink_to(tmp_path / "elsewhere")
        _clean([Database(name, 0)])
        assert name in [d.name for d in find_databases()]
        output = capsys.readouterr().out
        assert "a session now holds port 6990" in output
        assert "can't open the lock file" in output
        lock_path.unlink()
        _clean([Database(name, 0)])
        assert name not in [d.name for d in find_databases()]
    finally:
        with _cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS {name}")


def test_clean_without_a_terminal_needs_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/dallinger")
    monkeypatch.setattr(
        "psynet.service_usage.port_lock_path", lambda port: str(tmp_path / "lock")
    )
    for finder in ("find_sessions", "find_redis_servers"):
        monkeypatch.setattr(f"psynet.service_usage.{finder}", lambda: [])
    monkeypatch.setattr(
        "psynet.service_usage.find_databases",
        lambda: [Database("dallinger_test_5990", 0)],
    )

    result = CliRunner().invoke(services_list, ["--clean"])

    assert result.exit_code != 0
    assert "dallinger_test_5990" in result.output
    assert "pass --yes" in result.output


def test_clean_refuses_a_remote_database_server(monkeypatch):
    for finder in ("find_sessions", "find_redis_servers", "find_databases"):
        monkeypatch.setattr(f"psynet.service_usage.{finder}", lambda: [])
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.org/dallinger")

    result = CliRunner().invoke(services_list, ["--clean", "--yes"])

    assert result.exit_code != 0
    assert "only cleans a local PostgreSQL server" in result.output


def test_yes_needs_clean():
    result = CliRunner().invoke(services_list, ["--yes"])

    assert result.exit_code == 2
    assert "only works with --clean" in result.output

import json
import signal
import zipfile
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner


def _write_archive(path: Path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/experiment.csv", "id,vars\n1,{}\n")


def _export_archive(
    path: Path, *, participant_count=0, max_response_id=0, content_token="token"
):
    from psynet.local_deployment import DatabaseExport

    _write_archive(path)
    return DatabaseExport(participant_count, max_response_id, content_token)


def local_deployment_module():
    import psynet.local_deployment

    return psynet.local_deployment


@pytest.mark.parametrize(
    "value",
    ["gibbs", "village-01", "a1", "0"],
)
def test_validate_local_id_accepts_path_safe_values(value):
    from psynet.local_deployment import validate_local_id

    assert validate_local_id(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "Gibbs", "gibbs experiment", "gibbs/one", "-gibbs", "gibbs_1"],
)
def test_validate_local_id_rejects_unsafe_values(value):
    from psynet.local_deployment import validate_local_id

    with pytest.raises(ValueError, match="lowercase letters, digits, and dashes"):
        validate_local_id(value)


def test_create_snapshot_numbers_archives_and_records_events(tmp_path):
    from psynet.local_deployment import create_snapshot

    def exporter(path):
        _write_archive(path)
        return 12

    first = create_snapshot(
        experiment_path=tmp_path,
        local_id="gibbs",
        reason="periodic",
        deployment_id="launch-1",
        resumed_from=None,
        exporter=exporter,
    )
    second = create_snapshot(
        experiment_path=tmp_path,
        local_id="gibbs",
        reason="shutdown",
        deployment_id="launch-1",
        resumed_from=None,
        exporter=exporter,
    )

    assert first.sequence == 1
    assert first.path == tmp_path / "data/snapshots/gibbs/000001.zip"
    assert second.sequence == 2
    assert second.parent_sequence == 1
    assert second.path == tmp_path / "data/snapshots/gibbs/000002.zip"
    assert not list((tmp_path / "data/snapshots/gibbs").glob("*.partial"))
    assert first.path.stat().st_mode & 0o777 == 0o600
    assert first.metadata_path.stat().st_mode & 0o777 == 0o600

    metadata = json.loads((tmp_path / "data/snapshots/gibbs/000002.json").read_text())
    assert metadata["reason"] == "shutdown"
    assert metadata["participant_count"] == 12
    assert metadata["parent_sequence"] == 1
    assert len(metadata["sha256"]) == 64

    events = [
        json.loads(line)
        for line in (tmp_path / "data/deployment-events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == [
        "snapshot.succeeded",
        "snapshot.succeeded",
    ]
    assert events[-1]["id"] == "gibbs"
    assert events[-1]["sequence"] == 2


def test_create_snapshot_records_exporter_watermark_not_a_later_read(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import DatabaseExport, create_snapshot

    def exporter(path):
        _write_archive(path)
        return DatabaseExport(
            participant_count=1, max_response_id=4, content_token="db-token"
        )

    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 99)
    snapshot = create_snapshot(
        tmp_path, "gibbs", "shutdown", "launch-1", exporter=exporter
    )
    assert snapshot.max_response_id == 4
    assert snapshot.content_token == "db-token"
    metadata = json.loads(snapshot.metadata_path.read_text(encoding="utf-8"))
    assert metadata["max_response_id"] == 4
    assert metadata["content_token"] == "db-token"


def test_create_snapshot_records_failure_without_partial_archive(tmp_path):
    from psynet.local_deployment import create_snapshot

    def exporter(path):
        path.write_bytes(b"incomplete")
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        create_snapshot(
            experiment_path=tmp_path,
            local_id="gibbs",
            reason="periodic",
            deployment_id="launch-1",
            exporter=exporter,
        )

    assert not list((tmp_path / "data/snapshots/gibbs").glob("*.zip"))
    events = [
        json.loads(line)
        for line in (tmp_path / "data/deployment-events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["event"] == "snapshot.failed"
    assert "database unavailable" in events[-1]["error"]


def test_create_snapshot_removes_archive_when_metadata_is_interrupted(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import create_snapshot

    def exporter(path):
        _write_archive(path)

    def interrupted(path, content):
        raise KeyboardInterrupt

    monkeypatch.setattr("psynet.local_deployment._write_json_atomically", interrupted)
    with pytest.raises(KeyboardInterrupt):
        create_snapshot(
            tmp_path,
            "gibbs",
            "shutdown",
            "launch-1",
            exporter=exporter,
        )

    directory = tmp_path / "data" / "snapshots" / "gibbs"
    assert list(directory.glob("*.zip")) == []
    assert list(directory.glob("*.json")) == []
    events = [
        json.loads(line)
        for line in (tmp_path / "data/deployment-events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["event"] == "snapshot.failed"
    assert "interrupted" in events[-1]["error"]


def test_export_database_snapshot_stays_in_process_without_a_wait_callback(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import DatabaseExport, export_database_snapshot

    monkeypatch.setattr(
        "psynet.local_deployment._wait_callback_installed",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.local_deployment._export_database_snapshot_in_process",
        lambda destination, db_url: DatabaseExport(1, 2, "in-process"),
    )

    def fail_subprocess(*_args, **_kwargs):
        raise AssertionError("subprocess export should not run")

    monkeypatch.setattr("psynet.local_deployment.subprocess.run", fail_subprocess)

    exported = export_database_snapshot(tmp_path / "snap.zip", db_url="postgresql://db")

    assert exported == DatabaseExport(1, 2, "in-process")


def test_export_database_snapshot_uses_a_fresh_process_when_copy_would_be_rejected(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import DatabaseExport, export_database_snapshot

    monkeypatch.setattr(
        "psynet.local_deployment._wait_callback_installed",
        lambda: True,
    )
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs["input"]
        completed = Mock()
        completed.returncode = 0
        completed.stdout = json.dumps(
            {
                "participant_count": 4,
                "max_response_id": 8,
                "content_token": "from-child",
            }
        )
        completed.stderr = ""
        return completed

    monkeypatch.setattr("psynet.local_deployment.subprocess.run", fake_run)

    exported = export_database_snapshot(tmp_path / "snap.zip", db_url="postgresql://db")

    assert exported == DatabaseExport(4, 8, "from-child")
    assert captured["args"][1:] == ["-m", "psynet.local_deployment"]
    payload = json.loads(captured["input"])
    assert payload["db_url"] == "postgresql://db"
    assert payload["destination"] == str(tmp_path / "snap.zip")


def test_export_subprocess_reports_child_failure(tmp_path, monkeypatch):
    from psynet.local_deployment import export_database_snapshot

    monkeypatch.setattr(
        "psynet.local_deployment._wait_callback_installed",
        lambda: True,
    )

    def fake_run(*_args, **_kwargs):
        completed = Mock()
        completed.returncode = 1
        completed.stdout = ""
        completed.stderr = "ProgrammingError: copy_expert cannot be used\n"
        return completed

    monkeypatch.setattr("psynet.local_deployment.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="ProgrammingError"):
        export_database_snapshot(tmp_path / "snap.zip", db_url="postgresql://db")


def test_snapshot_module_entry_point_rejects_invalid_input():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "psynet.local_deployment"],
        input="{",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "JSONDecodeError" in completed.stderr


def test_snapshot_subprocess_main_prints_export_counts(monkeypatch, capsys):
    from psynet.local_deployment import (
        DatabaseExport,
        _export_snapshot_subprocess_main,
    )

    monkeypatch.setattr(
        "psynet.local_deployment._export_database_snapshot_in_process",
        lambda destination, db_url: DatabaseExport(3, 9, "tok"),
    )
    monkeypatch.setattr(
        "sys.stdin",
        StringIO(json.dumps({"destination": "snap.zip", "db_url": "postgresql://db"})),
    )

    _export_snapshot_subprocess_main()

    assert json.loads(capsys.readouterr().out) == {
        "participant_count": 3,
        "max_response_id": 9,
        "content_token": "tok",
    }


def test_choose_snapshot_defaults_to_latest_without_a_terminal(tmp_path, monkeypatch):
    from psynet.local_deployment import choose_snapshot, create_snapshot

    def exporter(path):
        _write_archive(path)

    create_snapshot(tmp_path, "gibbs", "periodic", "launch-1", exporter=exporter)
    latest = create_snapshot(
        tmp_path, "gibbs", "shutdown", "launch-1", exporter=exporter
    )
    monkeypatch.setattr("psynet.local_deployment.sys.stdin.isatty", lambda: False)

    assert choose_snapshot(tmp_path, "gibbs").path == latest.path


def test_choose_snapshot_supports_explicit_sequence(tmp_path):
    from psynet.local_deployment import choose_snapshot, create_snapshot

    def exporter(path):
        _write_archive(path)

    first = create_snapshot(
        tmp_path, "gibbs", "periodic", "launch-1", exporter=exporter
    )
    create_snapshot(tmp_path, "gibbs", "shutdown", "launch-1", exporter=exporter)

    assert choose_snapshot(tmp_path, "gibbs", "1").path == first.path
    with pytest.raises(ValueError, match="Snapshot 9 does not exist"):
        choose_snapshot(tmp_path, "gibbs", "9")


def test_choose_snapshot_rejects_corrupted_archive(tmp_path):
    from psynet.local_deployment import choose_snapshot, create_snapshot

    def exporter(path):
        _write_archive(path)

    snapshot = create_snapshot(
        tmp_path, "gibbs", "shutdown", "launch-1", exporter=exporter
    )
    snapshot.path.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="corrupt or incomplete"):
        choose_snapshot(tmp_path, "gibbs", "latest")


def test_snapshot_without_metadata_is_not_published(tmp_path):
    from psynet.local_deployment import list_snapshots

    archive = tmp_path / "data/snapshots/gibbs/000001.zip"
    archive.parent.mkdir(parents=True)
    _write_archive(archive)

    assert list_snapshots(tmp_path, "gibbs") == []


def test_choose_snapshot_refuses_a_torn_later_archive(tmp_path):
    from psynet.local_deployment import choose_snapshot, create_snapshot

    create_snapshot(
        tmp_path,
        "gibbs",
        "shutdown",
        "launch-1",
        exporter=lambda path: _write_archive(path),
    )
    torn = tmp_path / "data/snapshots/gibbs/000002.zip"
    _write_archive(torn)

    with pytest.raises(ValueError, match="incomplete snapshots"):
        choose_snapshot(tmp_path, "gibbs", "latest")


def test_choose_snapshot_displays_rich_table(tmp_path, monkeypatch):
    from rich.console import Console

    from psynet.local_deployment import choose_snapshot, create_snapshot

    def exporter(path):
        _write_archive(path)

    snapshot = create_snapshot(
        tmp_path, "gibbs", "shutdown", "launch-1", exporter=exporter
    )
    output = StringIO()
    console = Console(file=output, width=100)
    monkeypatch.setattr("psynet.local_deployment.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "psynet.local_deployment.IntPrompt.ask", lambda *_args, **_kwargs: 1
    )

    assert choose_snapshot(tmp_path, "gibbs", console=console) == snapshot
    assert "Snapshots for local deployment 'gibbs'" in output.getvalue()
    assert "000001" in output.getvalue()


def test_deploy_local_requires_id(tmp_path):
    from psynet.command_line import psynet
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    runner = CliRunner()
    with working_directory(tmp_path):
        result = runner.invoke(psynet, ["deploy", "local"])

    assert result.exit_code == 2
    assert "Missing option '--id'" in result.output


def test_comment_writes_event_for_explicit_id(tmp_path):
    from psynet.command_line import psynet
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    runner = CliRunner()
    with working_directory(tmp_path):
        result = runner.invoke(
            psynet,
            ["comment", "--id", "gibbs", "Changed headphones."],
        )

    assert result.exit_code == 0, result.output
    event = json.loads((tmp_path / "data/deployment-events.jsonl").read_text().strip())
    assert event["event"] == "comment"
    assert event["id"] == "gibbs"
    assert event["text"] == "Changed headphones."


def test_generic_event_helper_only_writes_inside_experiment(tmp_path):
    from psynet.command_line import _append_deployment_event_if_in_experiment
    from psynet.utils import working_directory

    with working_directory(tmp_path):
        _append_deployment_event_if_in_experiment("export.succeeded")
    assert not (tmp_path / "data").exists()

    (tmp_path / "experiment.py").write_text("")
    with working_directory(tmp_path):
        _append_deployment_event_if_in_experiment("export.succeeded")
    event = json.loads((tmp_path / "data/deployment-events.jsonl").read_text().strip())
    assert event["event"] == "export.succeeded"


def test_prepare_protects_managed_database_before_reset(tmp_path, monkeypatch):
    from psynet.command_line import _prepare
    from psynet.utils import working_directory

    calls = []

    @contextmanager
    def locked(*_args):
        calls.append("lock")
        yield

    def stop_writers():
        calls.append("kill")
        return True

    monkeypatch.setattr("psynet.command_line.local_database_lock", locked)
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes", stop_writers
    )
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database",
        lambda *_args, **_kwargs: calls.append("protect"),
    )
    monkeypatch.setattr(
        "psynet.command_line._prepare_unlocked",
        lambda archive: calls.append(("prepare", archive)),
    )

    with working_directory(tmp_path):
        _prepare("snapshot.zip")

    assert calls == ["lock", "kill", "protect", ("prepare", "snapshot.zip")]


def test_prepare_refuses_reset_while_a_database_writer_is_alive(tmp_path, monkeypatch):
    from psynet.command_line import _prepare
    from psynet.utils import working_directory

    calls = []

    @contextmanager
    def locked(*_args):
        calls.append("lock")
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", locked)
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes",
        lambda: False,
    )
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database",
        lambda *_args, **_kwargs: calls.append("protect"),
    )
    monkeypatch.setattr(
        "psynet.command_line._prepare_unlocked",
        lambda archive: calls.append("reset"),
    )
    monkeypatch.setattr(
        "psynet.command_line._leftover_database_writer_message",
        lambda purpose: f"writers still running before {purpose}",
    )

    import click

    with working_directory(tmp_path):
        with pytest.raises(click.ClickException, match="writers still running"):
            _prepare("snapshot.zip")

    assert calls == ["lock"]


def test_concurrent_deployment_error_tells_operator_to_stop_the_other_experiment(
    tmp_path,
):
    from psynet.local_deployment import concurrent_deployment_error

    lock_path = tmp_path / "local-deployment.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": 4242,
                "experiment_path": "/lab/gibbs",
                "id": "gibbs",
            }
        )
    )

    message = str(concurrent_deployment_error(lock_path))
    assert message.startswith(
        "Another local PsyNet experiment is already running. "
        "Stop it first, then try again."
    )
    assert "id gibbs" in message
    assert "directory /lab/gibbs" in message
    assert "pid 4242" in message
    assert "Stop it first" in message


def test_concurrent_deployment_error_without_holder_still_asks_to_stop(tmp_path):
    from psynet.local_deployment import concurrent_deployment_error

    message = str(concurrent_deployment_error(tmp_path / "missing.lock"))
    assert message == (
        "Another local PsyNet experiment is already running. "
        "Stop it first, then try again."
    )


def test_local_database_lock_uses_concurrent_error_when_lock_is_held(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import local_database_lock

    lock_path = tmp_path / "local-deployment.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": 99,
                "experiment_path": str(tmp_path),
                "id": "first-run",
            }
        )
    )
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: lock_path,
    )

    @contextmanager
    def already_locked(*_args, **_kwargs):
        raise BlockingIOError
        yield

    monkeypatch.setattr("psynet.local_deployment.file_lock", already_locked)

    with pytest.raises(RuntimeError, match="Stop it first") as error:
        with local_database_lock(tmp_path, "second-run", wait_seconds=0):
            pass

    assert "id first-run" in str(error.value)
    assert "pid 99" in str(error.value)


def test_local_database_lock_waits_out_a_deployment_that_is_stopping(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import local_database_lock

    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: tmp_path / "local-deployment.lock",
    )
    real_file_lock = local_deployment_module().file_lock
    attempts = []

    @contextmanager
    def locked_until_second_attempt(path, **kwargs):
        attempts.append(path)
        if len(attempts) == 1:
            raise BlockingIOError
        with real_file_lock(path, **kwargs) as file:
            yield file

    monkeypatch.setattr(
        "psynet.local_deployment.file_lock", locked_until_second_attempt
    )

    with local_database_lock(tmp_path, "second-run", wait_seconds=5):
        pass

    assert len(attempts) == 2


def test_local_database_lock_serializes_threads(tmp_path, monkeypatch):
    import threading
    import time

    from psynet.local_deployment import local_database_lock

    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: tmp_path / "local-deployment.lock",
    )
    order = []
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with local_database_lock(tmp_path, "first"):
            order.append("enter-first")
            entered.set()
            release.wait(timeout=5)
            order.append("exit-first")

    def waiter():
        with local_database_lock(tmp_path, "second"):
            order.append("enter-second")

    first = threading.Thread(target=holder)
    second = threading.Thread(target=waiter)
    first.start()
    assert entered.wait(timeout=5)
    second.start()
    time.sleep(0.2)
    assert order == ["enter-first"]
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert order == ["enter-first", "exit-first", "enter-second"]


def test_local_database_lock_path_is_shared_across_users(monkeypatch):
    from psynet.local_deployment import local_database_lock_path

    monkeypatch.delenv("PSYNET_LOCAL_DATABASE_LOCK", raising=False)
    monkeypatch.setenv("HOME", "/home/someone")
    assert local_database_lock_path() == Path("/tmp/psynet-local-deployment.lock")
    monkeypatch.setenv("PSYNET_LOCAL_DATABASE_LOCK", "/var/lock/psynet.lock")
    assert local_database_lock_path() == Path("/var/lock/psynet.lock")


def test_local_database_lock_file_is_world_writable(tmp_path, monkeypatch):
    from psynet.local_deployment import local_database_lock

    lock_path = tmp_path / "local-deployment.lock"
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: lock_path,
    )
    with local_database_lock(tmp_path, "gibbs"):
        assert lock_path.stat().st_mode & 0o777 == 0o666


def test_local_database_lock_maps_permission_error(tmp_path, monkeypatch):
    from psynet.local_deployment import local_database_lock

    lock_path = tmp_path / "denied.lock"
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: lock_path,
    )

    def denied(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("psynet.deployment_events.os.open", denied)
    with pytest.raises(
        RuntimeError, match="Cannot access the local PsyNet database lock"
    ):
        with local_database_lock(tmp_path, "gibbs"):
            pass


def test_local_database_lock_does_not_follow_symlink(tmp_path, monkeypatch):
    from psynet.local_deployment import local_database_lock

    victim = tmp_path / "secret"
    victim.write_text("keep")
    victim.chmod(0o600)
    lock_path = tmp_path / "local-deployment.lock"
    lock_path.symlink_to(victim)
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: lock_path,
    )
    with pytest.raises(RuntimeError, match="symlink"):
        with local_database_lock(tmp_path, "gibbs"):
            pass
    assert victim.read_text() == "keep"
    assert victim.stat().st_mode & 0o777 == 0o600


def test_local_database_lock_retries_when_the_lock_inode_changes(tmp_path, monkeypatch):
    import psynet.deployment_events as events
    from psynet.local_deployment import local_database_lock

    lock_path = tmp_path / "local-deployment.lock"
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: lock_path,
    )
    calls = {"n": 0}
    real = events._held_lock_matches_path

    def mismatch_once(path, file):
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        return real(path, file)

    monkeypatch.setattr(events, "_held_lock_matches_path", mismatch_once)
    with local_database_lock(tmp_path, "gibbs", wait_seconds=0):
        assert lock_path.is_file()
    assert calls["n"] >= 2


def test_lock_refresh_updates_an_old_timestamp(tmp_path):
    import os

    from psynet.deployment_events import file_lock
    from psynet.local_deployment import _refresh_lock_timestamp

    path = tmp_path / "local-deployment.lock"
    with file_lock(path, world_writable=True) as file:
        stale = path.stat().st_mtime - 100_000
        os.utime(path, (stale, stale))
        _refresh_lock_timestamp(file)
        assert path.stat().st_mtime > stale


def test_lock_maintainer_logs_when_the_held_file_is_unlinked(tmp_path, caplog):
    import logging

    from psynet.deployment_events import file_lock
    from psynet.local_deployment import _maintain_lock_file

    class StopAfterOneWait:
        def is_set(self):
            return False

        def wait(self, timeout=None):
            return True

    path = tmp_path / "local-deployment.lock"
    with file_lock(path, world_writable=True) as file:
        path.unlink()
        with caplog.at_level(logging.ERROR):
            _maintain_lock_file(path, file, StopAfterOneWait())
    assert "was removed" in caplog.text


def test_local_database_lock_does_not_remap_permission_error_inside_body(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import local_database_lock

    lock_path = tmp_path / "ok.lock"
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: lock_path,
    )
    with pytest.raises(PermissionError, match="inside the lock"):
        with local_database_lock(tmp_path, "gibbs"):
            raise PermissionError("inside the lock")


def test_second_process_is_told_to_stop_the_running_experiment(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    import time

    from psynet.local_deployment import local_database_lock

    monkeypatch.setenv("HOME", str(tmp_path))
    lock_path = tmp_path / "psynet-data" / "local-deployment.lock"
    monkeypatch.setenv("PSYNET_LOCAL_DATABASE_LOCK", str(lock_path))
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time\n"
            "from pathlib import Path\n"
            "from psynet.local_deployment import local_database_lock\n"
            "with local_database_lock(Path('/lab/gibbs'), 'gibbs'):\n"
            "    time.sleep(30)\n",
        ],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PSYNET_LOCAL_DATABASE_LOCK": str(lock_path),
        },
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            if lock_path.exists() and "gibbs" in lock_path.read_text():
                break
            time.sleep(0.05)
        else:
            raise AssertionError("holder process did not write the lock file")

        with pytest.raises(RuntimeError, match="Stop it first") as error:
            with local_database_lock(tmp_path, "second-run", wait_seconds=0):
                pass

        message = str(error.value)
        assert "id gibbs" in message
        assert "directory /lab/gibbs" in message
        assert f"pid {holder.pid}" in message
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_local_runner_holds_database_lock(tmp_path, monkeypatch):
    from psynet.command_line import _run_local
    from psynet.utils import working_directory

    calls = []

    @contextmanager
    def locked(*_args):
        calls.append(("lock", _args))
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", locked)
    monkeypatch.setattr(
        "psynet.command_line._run_local_unlocked",
        lambda *_args, **_kwargs: calls.append("run"),
    )

    with working_directory(tmp_path):
        _run_local(None, False, None, False, True, "debug", Mock())

    assert calls[0][0] == "lock"
    assert calls[1] == "run"


@pytest.mark.parametrize(
    "stop_with",
    ["return", "exit0", "exitnone", "sigterm", "sigint"],
)
def test_deploy_local_restores_selected_snapshot_and_saves_shutdown(
    tmp_path, monkeypatch, stop_with
):
    from psynet.command_line import psynet
    from psynet.local_deployment import DatabaseOwner, Snapshot
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    archive = tmp_path / "data/snapshots/gibbs/000004.zip"
    archive.parent.mkdir(parents=True)
    _write_archive(archive)
    selected = Snapshot(
        sequence=4,
        path=archive,
        metadata_path=archive.with_suffix(".json"),
        created_at="2026-08-27T18:00:00Z",
        reason="shutdown",
        deployment_id="old-launch",
        parent_sequence=3,
        participant_count=12,
        sha256=None,
    )
    final = Snapshot(
        sequence=5,
        path=archive.with_name("000005.zip"),
        metadata_path=archive.with_name("000005.json"),
        created_at="2026-08-27T18:10:00Z",
        reason="shutdown",
        deployment_id="new-launch",
        parent_sequence=4,
        participant_count=13,
        sha256=None,
    )
    calls = {}
    events = []

    @contextmanager
    def unlocked(*_args):
        yield

    def run_local(*args, **kwargs):
        calls["run"] = (args, kwargs)
        if stop_with == "exit0":
            raise SystemExit(0)
        if stop_with == "exitnone":
            raise SystemExit(None)
        if stop_with == "sigterm":
            raise SystemExit(128 + signal.SIGTERM)
        if stop_with == "sigint":
            raise KeyboardInterrupt

    def create_final(*args, **kwargs):
        calls["snapshot"] = (args, kwargs)
        return final

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    ensure_services = Mock(return_value=True)
    monkeypatch.setattr("psynet.services.ensure_local_services", ensure_services)
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.choose_snapshot",
        lambda *_args, **_kwargs: selected,
    )
    monkeypatch.setattr("psynet.command_line._run_local", run_local)
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes", lambda: True
    )
    monkeypatch.setattr(
        "psynet.command_line.read_database_owner",
        lambda: DatabaseOwner("gibbs", tmp_path, "new-launch", "Example"),
    )
    monkeypatch.setattr("psynet.command_line.create_snapshot", create_final)
    monkeypatch.setattr(
        "psynet.command_line.append_deployment_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    raised = None
    with working_directory(tmp_path):
        try:
            result = CliRunner().invoke(
                psynet,
                ["deploy", "local", "--id", "gibbs", "--snapshot", "latest"],
            )
        except KeyboardInterrupt as error:
            raised = error
            result = None

    if stop_with == "sigint":
        if raised is None:
            assert result.exit_code != 0, result.output
    elif stop_with == "sigterm":
        assert raised is None
        assert result.exit_code == 128 + signal.SIGTERM, result.output
    else:
        assert raised is None
        assert result.exit_code == 0, result.output
    assert calls["run"][0][2] == str(archive)
    assert calls["run"][1]["local_id"] == "gibbs"
    assert calls["run"][1]["resumed_from"] == 4
    assert calls["run"][1]["services_ready"] is True
    ensure_services.assert_called_once_with(assume_yes=False, strict=True)
    assert calls["snapshot"][1]["reason"] == "shutdown"
    assert calls["snapshot"][1]["resumed_from"] == 4
    assert [args[1] for args, _kwargs in events] == [
        "deploy.requested",
        "deploy.stopped",
    ]


def test_second_interrupt_during_shutdown_snapshot_is_not_a_clean_exit(
    tmp_path, monkeypatch
):
    from psynet.command_line import psynet
    from psynet.local_deployment import DatabaseOwner, Snapshot
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    archive = tmp_path / "data" / "snapshots" / "gibbs" / "000001.zip"
    archive.parent.mkdir(parents=True)
    _write_archive(archive)
    selected = Snapshot(
        sequence=1,
        path=archive,
        metadata_path=archive.with_suffix(".json"),
        created_at="2026-08-27T18:00:00Z",
        reason="shutdown",
        deployment_id="old-launch",
        parent_sequence=None,
        participant_count=1,
        sha256=None,
    )
    seen = {}

    def exit_cleanly(signum, frame):
        raise SystemExit(0)

    def create_final(*_args, **_kwargs):
        seen["handler"] = signal.getsignal(signal.SIGINT)
        raise KeyboardInterrupt

    @contextmanager
    def unlocked(*_args):
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    monkeypatch.setattr("psynet.services.ensure_local_services", lambda **_kwargs: True)
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "psynet.command_line.choose_snapshot", lambda *_a, **_k: selected
    )
    monkeypatch.setattr("psynet.command_line._run_local", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes", lambda: True
    )
    monkeypatch.setattr(
        "psynet.command_line.read_database_owner",
        lambda: DatabaseOwner("gibbs", tmp_path, "new-launch", "Example"),
    )
    monkeypatch.setattr("psynet.command_line.create_snapshot", create_final)
    monkeypatch.setattr(
        "psynet.command_line.append_deployment_event", lambda *_a, **_k: None
    )

    previous = signal.signal(signal.SIGINT, exit_cleanly)
    raised = None
    try:
        with working_directory(tmp_path):
            try:
                result = CliRunner().invoke(
                    psynet, ["deploy", "local", "--id", "gibbs"]
                )
            except KeyboardInterrupt as error:
                raised = error
                result = None
    finally:
        signal.signal(signal.SIGINT, previous)

    assert seen["handler"] is not exit_cleanly
    assert signal.getsignal(signal.SIGINT) is previous
    if raised is None:
        assert result.exit_code != 0


def test_protect_existing_database_recovers_interrupted_owner(tmp_path, monkeypatch):
    from psynet.local_deployment import (
        DatabaseOwner,
        Snapshot,
        protect_existing_database,
    )

    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    recovered = Mock(spec=Snapshot)
    create_snapshot = Mock(return_value=recovered)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner("first", owner_path, "launch-1", "Example"),
    )
    monkeypatch.setattr("psynet.local_deployment.list_snapshots", lambda *_args: [])
    monkeypatch.setattr(
        "psynet.local_deployment.create_snapshot",
        create_snapshot,
    )

    result = protect_existing_database(tmp_path / "new", "second")

    assert result is recovered
    create_snapshot.assert_called_once_with(
        owner_path,
        "first",
        reason="recovery-before-reset",
        deployment_id="launch-1",
    )


@pytest.mark.parametrize(
    "rows,expected_unmanaged",
    [
        ([], False),
        ([("{}",), ("{}",)], True),
        ([("not-serialized-psynet-data",)], True),
    ],
)
def test_read_database_owner_treats_unreadable_state_as_unmanaged(
    monkeypatch, rows, expected_unmanaged
):
    import psycopg2

    from psynet.local_deployment import UNREADABLE_DATABASE_OWNER, read_database_owner

    cursor = Mock()
    cursor.fetchall.return_value = rows
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(psycopg2, "connect", lambda **_kwargs: connection)

    owner = read_database_owner(db_url="postgresql://example")

    if expected_unmanaged:
        assert owner is UNREADABLE_DATABASE_OWNER
        assert not owner.managed
    else:
        assert owner is None


def test_read_database_owner_survives_a_locked_experiment_table(monkeypatch):
    import psycopg2

    from psynet.local_deployment import UNREADABLE_DATABASE_OWNER, read_database_owner

    cursor = Mock()
    cursor.execute.side_effect = psycopg2.errors.QueryCanceled("statement timeout")
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(psycopg2, "connect", lambda **_kwargs: connection)

    assert read_database_owner(db_url="postgresql://example") is (
        UNREADABLE_DATABASE_OWNER
    )


@pytest.mark.parametrize(
    "deployment_id,disposable",
    [
        ("gibbs-demo__mode=debug__launch=2026-08-29--16-37-05", True),
        (None, True),
        ("gibbs-demo__mode=live__launch=2026-08-29--16-37-05", False),
        ("gibbs-demo__mode=sandbox__launch=2026-08-29--16-37-05", False),
        ("legacy-experiment-without-mode", False),
        ("gibbs-demo__mode=__launch=2026-08-29--16-37-05", False),
        ("gibbs-demo__mode=bot__launch=2026-08-29--16-37-05", False),
    ],
)
def test_protect_existing_database_discards_disposable_databases(
    tmp_path, monkeypatch, capsys, deployment_id, disposable
):
    from psynet.local_deployment import DatabaseOwner, protect_existing_database

    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(None, None, deployment_id, "Gibbs demo"),
    )
    create_snapshot = Mock()
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    if disposable:
        assert protect_existing_database(tmp_path, "yolo") is None
        assert "Discarding the local database" in capsys.readouterr().out
    else:
        with pytest.raises(RuntimeError, match="--adopt-existing"):
            protect_existing_database(tmp_path, "yolo")
    create_snapshot.assert_not_called()


def test_protect_existing_database_adopts_unmanaged_live(tmp_path, monkeypatch):
    from psynet.local_deployment import (
        DatabaseOwner,
        Snapshot,
        protect_existing_database,
    )

    adopted = Mock(spec=Snapshot)
    events = []
    create_snapshot = Mock(return_value=adopted)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(
            None,
            None,
            "gibbs-demo__mode=live__launch=2026-08-29--16-37-05",
            "Gibbs demo",
        ),
    )
    monkeypatch.setattr(
        "psynet.local_deployment.append_deployment_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    result = protect_existing_database(tmp_path, "gibbs", adopt_existing=True)

    assert result is adopted
    assert events[0][0][1] == "database.adopted"
    assert events[0][0][2] == "gibbs"
    create_snapshot.assert_called_once_with(
        tmp_path.resolve(),
        "gibbs",
        reason="adopt-existing",
        deployment_id="gibbs-demo__mode=live__launch=2026-08-29--16-37-05",
    )


def test_protect_existing_database_skips_second_call_under_the_lock(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import (
        DatabaseOwner,
        local_database_lock,
        protect_existing_database,
    )

    adopted = Mock()
    create_snapshot = Mock(return_value=adopted)
    monkeypatch.setattr(
        "psynet.local_deployment.local_database_lock_path",
        lambda: tmp_path / "local-deployment.lock",
    )
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(
            None,
            None,
            "gibbs-demo__mode=live__launch=2026-08-29--16-37-05",
            "Gibbs demo",
        ),
    )
    monkeypatch.setattr(
        "psynet.local_deployment.append_deployment_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    with local_database_lock(tmp_path, "gibbs"):
        assert (
            protect_existing_database(tmp_path, "gibbs", adopt_existing=True) is adopted
        )
        assert (
            protect_existing_database(tmp_path, "prepare", ignore_disposable=True)
            is None
        )
    create_snapshot.assert_called_once()
    with pytest.raises(RuntimeError, match="--adopt-existing"):
        protect_existing_database(tmp_path, "gibbs")


def test_deploy_local_passes_adopt_existing_to_protect(tmp_path, monkeypatch):
    from psynet.command_line import psynet
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    calls = []

    @contextmanager
    def unlocked(*_args):
        yield

    def protect(*_args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop-after-protect")

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    monkeypatch.setattr(
        "psynet.services.ensure_local_services", Mock(return_value=True)
    )
    monkeypatch.setattr("psynet.command_line.protect_existing_database", protect)

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["deploy", "local", "--id", "gibbs", "--adopt-existing"],
        )

    assert calls == [{"adopt_existing": True}]
    assert result.exit_code != 0
    assert "stop-after-protect" in result.output


def test_protect_existing_database_ignore_disposable_does_not_discard_live(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import DatabaseOwner, protect_existing_database

    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(
            None,
            None,
            "gibbs-demo__mode=live__launch=2026-08-29--16-37-05",
            "Gibbs demo",
        ),
    )
    create_snapshot = Mock()
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    with pytest.raises(RuntimeError, match="--adopt-existing"):
        protect_existing_database(tmp_path, "yolo", ignore_disposable=True)
    create_snapshot.assert_not_called()


def test_protect_existing_database_ignore_disposable_still_discards_debug(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import DatabaseOwner, protect_existing_database

    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(
            None,
            None,
            "gibbs-demo__mode=debug__launch=2026-08-29--16-37-05",
            "Gibbs demo",
        ),
    )
    create_snapshot = Mock()
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    assert protect_existing_database(tmp_path, "yolo", ignore_disposable=True) is None
    create_snapshot.assert_not_called()


def test_protect_existing_database_never_discards_an_unreadable_database(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import (
        UNREADABLE_DATABASE_OWNER,
        protect_existing_database,
    )

    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: UNREADABLE_DATABASE_OWNER,
    )

    with pytest.raises(RuntimeError, match="identity unreadable"):
        protect_existing_database(tmp_path, "yolo")
    with pytest.raises(RuntimeError, match="identity unreadable"):
        protect_existing_database(tmp_path, "yolo", ignore_disposable=True)


def test_protect_existing_database_skips_clean_participant_finish(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import (
        DatabaseOwner,
        protect_existing_database,
    )
    from psynet.local_deployment import (
        create_snapshot as save_snapshot,
    )

    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    save_snapshot(
        owner_path,
        "first",
        reason="participant_finished",
        deployment_id="launch-1",
        exporter=_export_archive,
    )
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 0)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_content_token", lambda: "token"
    )
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(
            "first",
            owner_path,
            "launch-1",
            "Example",
            snapshot_needed_on_shutdown=False,
        ),
    )
    create_snapshot = Mock()
    monkeypatch.setattr(
        "psynet.local_deployment.create_snapshot",
        create_snapshot,
    )

    assert protect_existing_database(tmp_path / "new", "second") is None
    create_snapshot.assert_not_called()


def test_protect_existing_database_recovers_after_finish_if_someone_started(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import (
        DatabaseOwner,
        Snapshot,
        protect_existing_database,
    )
    from psynet.local_deployment import (
        create_snapshot as save_snapshot,
    )

    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    save_snapshot(
        owner_path,
        "first",
        reason="participant_finished",
        deployment_id="launch-1",
        exporter=lambda path: _write_archive(path),
    )
    recovered = Mock(spec=Snapshot)
    create_snapshot = Mock(return_value=recovered)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner(
            "first",
            owner_path,
            "launch-1",
            "Example",
            snapshot_needed_on_shutdown=True,
        ),
    )
    monkeypatch.setattr(
        "psynet.local_deployment.create_snapshot",
        create_snapshot,
    )

    assert protect_existing_database(tmp_path / "new", "second") is recovered
    create_snapshot.assert_called_once_with(
        owner_path,
        "first",
        reason="recovery-before-reset",
        deployment_id="launch-1",
    )


def test_protect_existing_database_skips_clean_shutdown(tmp_path, monkeypatch):
    from psynet.local_deployment import (
        DatabaseOwner,
        protect_existing_database,
    )
    from psynet.local_deployment import (
        create_snapshot as save_snapshot,
    )

    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    save_snapshot(
        owner_path,
        "first",
        reason="shutdown",
        deployment_id="launch-1",
        exporter=_export_archive,
    )
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 0)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_content_token", lambda: "token"
    )
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner("first", owner_path, "launch-1", "Example"),
    )
    create_snapshot = Mock()
    monkeypatch.setattr(
        "psynet.local_deployment.create_snapshot",
        create_snapshot,
    )

    assert protect_existing_database(tmp_path / "new", "second") is None
    create_snapshot.assert_not_called()


def test_protect_existing_database_recovers_when_a_later_snapshot_is_torn(
    tmp_path, monkeypatch
):
    from psynet.local_deployment import (
        DatabaseOwner,
        Snapshot,
        protect_existing_database,
    )
    from psynet.local_deployment import (
        create_snapshot as save_snapshot,
    )

    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    save_snapshot(
        owner_path,
        "first",
        reason="shutdown",
        deployment_id="launch-1",
        exporter=_export_archive,
    )
    torn = owner_path / "data/snapshots/first/000002.zip"
    _write_archive(torn)
    recovered = Mock(spec=Snapshot)
    create_snapshot = Mock(return_value=recovered)
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 0)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_content_token", lambda: "token"
    )
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_owner",
        lambda: DatabaseOwner("first", owner_path, "launch-1", "Example"),
    )
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    assert protect_existing_database(tmp_path / "new", "second") is recovered
    create_snapshot.assert_called_once_with(
        owner_path,
        "first",
        reason="recovery-before-reset",
        deployment_id="launch-1",
    )


def test_latest_snapshot_does_not_cover_owner_when_responses_arrived(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from psynet.local_deployment import (
        DatabaseOwner,
        latest_snapshot_covers_owner,
    )
    from psynet.local_deployment import (
        create_snapshot as save_snapshot,
    )

    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    snapshot = save_snapshot(
        owner_path,
        "first",
        reason="shutdown",
        deployment_id="launch-1",
        exporter=lambda path: _write_archive(path),
    )
    snapshot = replace(snapshot, max_response_id=4, content_token="db")
    owner = DatabaseOwner("first", owner_path, "launch-1", "Example")
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_content_token", lambda: "db"
    )
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 9)
    assert not latest_snapshot_covers_owner(owner, snapshot)
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 4)
    assert latest_snapshot_covers_owner(owner, snapshot)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_content_token", lambda: "changed"
    )
    assert not latest_snapshot_covers_owner(owner, snapshot)
    monkeypatch.setattr(
        "psynet.local_deployment.read_database_content_token", lambda: "db"
    )
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: None)
    assert not latest_snapshot_covers_owner(owner, snapshot)
    snapshot = replace(snapshot, max_response_id=None)
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 4)
    assert not latest_snapshot_covers_owner(owner, snapshot)
    snapshot = replace(snapshot, max_response_id=4, content_token=None)
    assert not latest_snapshot_covers_owner(owner, snapshot)


def test_managed_local_live_deployment_requires_id_and_live_mode():
    from psynet.local_deployment import is_managed_local_live_deployment

    assert not is_managed_local_live_deployment({})
    assert not is_managed_local_live_deployment(
        {
            "is_local_deployment": True,
            "mode": "debug",
            "local_id": "gibbs",
            "local_experiment_path": "/tmp/exp",
        }
    )
    assert is_managed_local_live_deployment(
        {
            "is_local_deployment": True,
            "mode": "live",
            "local_id": "gibbs",
            "local_experiment_path": "/tmp/exp",
        }
    )


def test_should_skip_shutdown_snapshot_only_after_finish_with_no_new_start(tmp_path):
    from psynet.local_deployment import DatabaseOwner, should_skip_shutdown_snapshot

    owner = DatabaseOwner("gibbs", tmp_path, "launch-1", "Example")
    assert not should_skip_shutdown_snapshot(owner)
    assert not should_skip_shutdown_snapshot(None)
    assert should_skip_shutdown_snapshot(
        DatabaseOwner(
            "gibbs",
            tmp_path,
            "launch-1",
            "Example",
            snapshot_needed_on_shutdown=False,
        )
    )
    assert not should_skip_shutdown_snapshot(
        DatabaseOwner(
            None,
            None,
            "launch-1",
            "Example",
            snapshot_needed_on_shutdown=False,
        )
    )


def test_deploy_local_skips_redundant_shutdown_snapshot(tmp_path, monkeypatch):
    from psynet.command_line import psynet
    from psynet.local_deployment import DatabaseOwner, Snapshot
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    archive = tmp_path / "data/snapshots/gibbs/000004.zip"
    archive.parent.mkdir(parents=True)
    _write_archive(archive)
    latest = Snapshot(
        sequence=4,
        path=archive,
        metadata_path=archive.with_suffix(".json"),
        created_at="2026-09-13T12:00:00Z",
        reason="participant_finished",
        deployment_id="launch-1",
        parent_sequence=3,
        participant_count=1,
        sha256=None,
    )
    events = []
    snapshot_calls = []

    @contextmanager
    def unlocked(*_args):
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    monkeypatch.setattr(
        "psynet.services.ensure_local_services", Mock(return_value=True)
    )
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.choose_snapshot", lambda *_args, **_kwargs: latest
    )
    monkeypatch.setattr(
        "psynet.command_line._run_local", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes", lambda: True
    )
    monkeypatch.setattr(
        "psynet.command_line.latest_snapshot_covers_owner",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "psynet.command_line.read_database_owner",
        lambda: DatabaseOwner(
            "gibbs",
            tmp_path,
            "launch-1",
            "Example",
            snapshot_needed_on_shutdown=False,
        ),
    )
    monkeypatch.setattr(
        "psynet.command_line.list_snapshots", lambda *_args, **_kwargs: [latest]
    )
    monkeypatch.setattr(
        "psynet.command_line.create_snapshot",
        lambda *args, **kwargs: snapshot_calls.append((args, kwargs)) or latest,
    )
    monkeypatch.setattr(
        "psynet.command_line.append_deployment_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["deploy", "local", "--id", "gibbs", "--snapshot", "latest"],
        )

    assert result.exit_code == 0, result.output
    assert snapshot_calls == []
    assert [args[1] for args, _kwargs in events] == [
        "deploy.requested",
        "deploy.stopped",
    ]
    stopped = events[-1][1]
    assert stopped["saved"] is True
    assert stopped["snapshot"] == 4
    assert stopped["shutdown_snapshot"] is False


def test_deploy_local_writes_shutdown_snapshot_if_workers_survive(
    tmp_path, monkeypatch
):
    from psynet.command_line import psynet
    from psynet.local_deployment import DatabaseOwner, Snapshot
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    archive = tmp_path / "data/snapshots/gibbs/000004.zip"
    archive.parent.mkdir(parents=True)
    _write_archive(archive)
    latest = Snapshot(
        sequence=4,
        path=archive,
        metadata_path=archive.with_suffix(".json"),
        created_at="2026-09-13T12:00:00Z",
        reason="participant_finished",
        deployment_id="launch-1",
        parent_sequence=3,
        participant_count=1,
        sha256=None,
    )
    snapshot_calls = []

    @contextmanager
    def unlocked(*_args):
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    monkeypatch.setattr(
        "psynet.services.ensure_local_services", Mock(return_value=True)
    )
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.choose_snapshot", lambda *_args, **_kwargs: latest
    )
    monkeypatch.setattr(
        "psynet.command_line._run_local", lambda *_args, **_kwargs: None
    )
    kill_results = iter((True, False))
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes",
        lambda: next(kill_results),
    )
    monkeypatch.setattr(
        "psynet.command_line.latest_snapshot_covers_owner",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "psynet.command_line.read_database_owner",
        lambda: DatabaseOwner(
            "gibbs",
            tmp_path,
            "launch-1",
            "Example",
            snapshot_needed_on_shutdown=False,
        ),
    )
    monkeypatch.setattr(
        "psynet.command_line.list_snapshots", lambda *_args, **_kwargs: [latest]
    )
    monkeypatch.setattr(
        "psynet.command_line.create_snapshot",
        lambda *args, **kwargs: snapshot_calls.append((args, kwargs)) or latest,
    )
    monkeypatch.setattr(
        "psynet.command_line.append_deployment_event",
        lambda *args, **kwargs: None,
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["deploy", "local", "--id", "gibbs", "--snapshot", "latest"],
        )

    assert result.exit_code == 0, result.output
    assert snapshot_calls
    assert snapshot_calls[0][1]["reason"] == "shutdown"


def test_deploy_local_refuses_to_snapshot_while_workers_survive(tmp_path, monkeypatch):
    from psynet.command_line import psynet
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    protect = Mock()

    @contextmanager
    def unlocked(*_args):
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    monkeypatch.setattr(
        "psynet.services.ensure_local_services", Mock(return_value=True)
    )
    monkeypatch.setattr("psynet.command_line.protect_existing_database", protect)
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes", lambda: False
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(psynet, ["deploy", "local", "--id", "gibbs"])

    assert result.exit_code != 0
    assert "worker" in result.output.lower()
    protect.assert_not_called()


def test_deploy_local_saves_shutdown_under_owner_id_on_mismatch(tmp_path, monkeypatch):
    from psynet.command_line import psynet
    from psynet.local_deployment import DatabaseOwner, Snapshot
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    owner_path = tmp_path / "owner"
    owner_path.mkdir()
    archive = tmp_path / "data/snapshots/gibbs/000001.zip"
    archive.parent.mkdir(parents=True)
    _write_archive(archive)
    latest = Snapshot(
        sequence=1,
        path=archive,
        metadata_path=archive.with_suffix(".json"),
        created_at="2026-09-15T12:00:00Z",
        reason="periodic",
        deployment_id="launch-1",
        parent_sequence=None,
        participant_count=1,
        sha256=None,
    )
    snapshot_calls = []

    @contextmanager
    def unlocked(*_args):
        yield

    monkeypatch.setattr("psynet.command_line.local_database_lock", unlocked)
    monkeypatch.setattr(
        "psynet.services.ensure_local_services", Mock(return_value=True)
    )
    monkeypatch.setattr(
        "psynet.command_line.protect_existing_database", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.choose_snapshot", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line._run_local", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "psynet.command_line.kill_psynet_worker_processes", lambda: True
    )
    monkeypatch.setattr(
        "psynet.command_line.read_database_owner",
        lambda: DatabaseOwner("other", owner_path, "launch-1", "Example"),
    )
    monkeypatch.setattr(
        "psynet.command_line.create_snapshot",
        lambda *args, **kwargs: snapshot_calls.append((args, kwargs)) or latest,
    )
    monkeypatch.setattr(
        "psynet.command_line.append_deployment_event",
        lambda *args, **kwargs: None,
    )

    with working_directory(tmp_path):
        result = CliRunner().invoke(
            psynet,
            ["deploy", "local", "--id", "gibbs"],
        )

    assert result.exit_code != 0
    assert snapshot_calls
    assert snapshot_calls[0][0][0] == owner_path
    assert snapshot_calls[0][0][1] == "other"
    assert snapshot_calls[0][1]["reason"] == "shutdown"
    assert "Saved shutdown snapshot" in result.output


def test_maybe_snapshot_after_participant_finish_clears_shutdown_need(monkeypatch):
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    snapshot = Mock()
    config = Mock()
    config.get.return_value = True
    monkeypatch.setattr("psynet.experiment.get_config", lambda: config)
    session = Mock()
    monkeypatch.setattr("psynet.experiment.db.session", session)

    class Dummy:
        var = SimpleNamespace()

        def _managed_local_live_deployment_info(self):
            return {"local_id": "gibbs"}

        def create_local_deployment_snapshot(self, reason):
            assert reason == "participant_finished"
            assert self.var.local_snapshot_needed_on_shutdown is False
            return snapshot

        def _has_unfinished_participants(self, excluding=None):
            return False

        maybe_snapshot_after_participant_finish = (
            Experiment.maybe_snapshot_after_participant_finish
        )
        _create_participant_finish_snapshot = (
            Experiment._create_participant_finish_snapshot
        )

    dummy = Dummy()
    assert dummy.maybe_snapshot_after_participant_finish(Mock(id=1)) is snapshot
    assert dummy.var.local_snapshot_needed_on_shutdown is False
    assert session.commit.call_count >= 1


def test_maybe_snapshot_after_participant_finish_can_be_disabled(monkeypatch):
    from psynet.experiment import Experiment

    config = Mock()
    config.get.return_value = False
    monkeypatch.setattr("psynet.experiment.get_config", lambda: config)

    class Dummy:
        create_local_deployment_snapshot = Mock()
        maybe_snapshot_after_participant_finish = (
            Experiment.maybe_snapshot_after_participant_finish
        )

    dummy = Dummy()
    assert dummy.maybe_snapshot_after_participant_finish() is None
    dummy.create_local_deployment_snapshot.assert_not_called()


def test_maybe_snapshot_keeps_shutdown_need_when_another_participant_is_working(
    monkeypatch,
):
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    config = Mock()
    config.get.return_value = True
    monkeypatch.setattr("psynet.experiment.get_config", lambda: config)
    monkeypatch.setattr("psynet.experiment.db.session", Mock())

    class Dummy:
        var = SimpleNamespace(local_snapshot_needed_on_shutdown=True)
        create_local_deployment_snapshot = Mock(return_value=Mock())
        _has_unfinished_participants = Mock(return_value=True)
        _managed_local_live_deployment_info = Mock(return_value={"local_id": "gibbs"})
        maybe_snapshot_after_participant_finish = (
            Experiment.maybe_snapshot_after_participant_finish
        )
        _create_participant_finish_snapshot = (
            Experiment._create_participant_finish_snapshot
        )

    dummy = Dummy()
    dummy.maybe_snapshot_after_participant_finish(Mock(id=1))
    assert dummy.var.local_snapshot_needed_on_shutdown is True
    dummy._has_unfinished_participants.assert_called_once()


def test_maybe_snapshot_skips_when_out_of_request_commit_fails(monkeypatch):
    from psynet.experiment import Experiment

    config = Mock()
    config.get.return_value = True
    monkeypatch.setattr("psynet.experiment.get_config", lambda: config)
    session = Mock()
    session.commit.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr("psynet.experiment.db.session", session)

    class Dummy:
        create_local_deployment_snapshot = Mock()
        _managed_local_live_deployment_info = Mock(return_value={"local_id": "gibbs"})
        maybe_snapshot_after_participant_finish = (
            Experiment.maybe_snapshot_after_participant_finish
        )

    dummy = Dummy()
    assert dummy.maybe_snapshot_after_participant_finish(Mock(id=1)) is None
    dummy.create_local_deployment_snapshot.assert_not_called()


def test_maybe_snapshot_skips_when_not_a_managed_local_live_run(monkeypatch):
    from psynet.experiment import Experiment

    config = Mock()
    config.get.return_value = True
    monkeypatch.setattr("psynet.experiment.get_config", lambda: config)
    session = Mock()
    monkeypatch.setattr("psynet.experiment.db.session", session)

    class Dummy:
        create_local_deployment_snapshot = Mock()
        _managed_local_live_deployment_info = Mock(return_value=None)
        maybe_snapshot_after_participant_finish = (
            Experiment.maybe_snapshot_after_participant_finish
        )

    dummy = Dummy()
    assert dummy.maybe_snapshot_after_participant_finish(Mock(id=1)) is None
    dummy.create_local_deployment_snapshot.assert_not_called()
    session.commit.assert_not_called()


def test_maybe_snapshot_defers_until_after_request_commit(monkeypatch):
    from types import SimpleNamespace

    from flask import Flask

    from psynet.experiment import Experiment

    snapshot = Mock()
    config = Mock()
    config.get.return_value = True
    monkeypatch.setattr("psynet.experiment.get_config", lambda: config)

    snapshot_calls = []

    class Dummy:
        var = SimpleNamespace(local_snapshot_needed_on_shutdown=True)

        def create_local_deployment_snapshot(self, reason):
            assert self.var.local_snapshot_needed_on_shutdown is False
            snapshot_calls.append(reason)
            return snapshot

        _has_unfinished_participants = Mock(return_value=False)
        _managed_local_live_deployment_info = Mock(return_value={"local_id": "gibbs"})
        maybe_snapshot_after_participant_finish = (
            Experiment.maybe_snapshot_after_participant_finish
        )
        _create_participant_finish_snapshot = (
            Experiment._create_participant_finish_snapshot
        )

    dummy = Dummy()
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: dummy)
    session = Mock()
    monkeypatch.setattr("psynet.experiment.db.session", session)
    participant = Mock(id=7)

    class FakeQuery:
        def get(self, id_):
            assert id_ == 7
            return participant

    monkeypatch.setattr(
        "psynet.participant.Participant",
        SimpleNamespace(query=FakeQuery()),
    )

    app = Flask(__name__)
    with app.test_request_context("/timeline"):
        assert dummy.maybe_snapshot_after_participant_finish(participant) is None
        assert snapshot_calls == []
        assert dummy.var.local_snapshot_needed_on_shutdown is True
        result = Experiment._run_deferred_participant_finish_snapshot()

    assert result is snapshot
    assert snapshot_calls == ["participant_finished"]
    assert dummy.var.local_snapshot_needed_on_shutdown is False
    assert session.commit.call_count >= 1


def test_after_request_skips_finish_snapshot_on_error(monkeypatch):
    from flask import Flask, g

    from psynet.experiment import Experiment

    session = Mock()
    monkeypatch.setattr("psynet.experiment.db.session", session)
    started = []
    monkeypatch.setattr(
        "psynet.experiment.threading.Thread",
        lambda *args, **kwargs: started.append(kwargs) or Mock(),
    )

    app = Flask(__name__)
    with app.test_request_context("/timeline"):
        g.psynet_finish_snapshot_needed = True
        response = Experiment._after_request_with_finish_snapshot(
            app.response_class(status=500)
        )
        assert g.psynet_finish_snapshot_needed is True

    assert response.status_code == 500
    session.commit.assert_not_called()
    assert started == []


def test_after_request_snapshots_off_the_request_thread(monkeypatch):
    from flask import Flask, g

    from psynet.experiment import Experiment

    session = Mock()
    monkeypatch.setattr("psynet.experiment.db.session", session)
    created = []

    class FakeThread:
        def __init__(self, target, args=(), **kwargs):
            created.append((target, args))

        def start(self):
            created.append("started")

    monkeypatch.setattr("psynet.experiment.threading.Thread", FakeThread)
    monkeypatch.setattr(
        "psynet.experiment.get_experiment",
        lambda: Mock(_create_participant_finish_snapshot=Mock()),
    )

    app = Flask(__name__)
    with app.test_request_context("/timeline"):
        g.psynet_finish_snapshot_needed = True
        g.psynet_finish_snapshot_participant_id = 7
        response = Experiment._after_request_with_finish_snapshot(
            app.response_class(status=200)
        )
        assert g.psynet_finish_snapshot_needed is False

    assert response.status_code == 200
    session.commit.assert_called_once()
    assert created[0][0] == Experiment._participant_finish_snapshot_off_request
    assert created[0][1][1] == 7
    assert created[1] == "started"


def test_create_local_deployment_snapshot_ignores_non_live_runs(monkeypatch):
    from psynet.experiment import Experiment

    monkeypatch.setattr("psynet.experiment.deployment_info.is_available", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment.deployment_info.read_all",
        lambda: {
            "is_local_deployment": True,
            "mode": "debug",
            "local_id": "gibbs",
            "local_experiment_path": "/tmp/exp",
        },
    )
    create_snapshot = Mock()
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    assert Experiment.create_local_deployment_snapshot("participant_finished") is None
    create_snapshot.assert_not_called()


def test_create_local_deployment_snapshot_writes_for_live_runs(monkeypatch):
    from psynet.experiment import Experiment

    snapshot = Mock()
    monkeypatch.setattr("psynet.experiment.deployment_info.is_available", lambda: True)
    monkeypatch.setattr(
        "psynet.experiment.deployment_info.read_all",
        lambda: {
            "is_local_deployment": True,
            "mode": "live",
            "local_id": "gibbs",
            "local_experiment_path": "/tmp/exp",
            "deployment_id": "launch-1",
            "resumed_from": 3,
        },
    )
    create_snapshot = Mock(return_value=snapshot)
    monkeypatch.setattr("psynet.local_deployment.create_snapshot", create_snapshot)

    assert (
        Experiment.create_local_deployment_snapshot("participant_finished") is snapshot
    )
    create_snapshot.assert_called_once_with(
        "/tmp/exp",
        "gibbs",
        reason="participant_finished",
        deployment_id="launch-1",
        resumed_from=3,
    )


def test_end_logic_snapshots_after_the_debrief():
    import inspect

    from psynet.end import EndLogic

    source = inspect.getsource(EndLogic.resolve)
    assert "snapshot_after_participant_finish" in source


def test_stamp_deployment_identity_overwrites_restored_archive_identity(monkeypatch):
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    monkeypatch.setattr(
        "psynet.experiment.deployment_info.read_all",
        lambda: {
            "deployment_id": "launch-new",
            "local_id": "gibbs",
            "local_experiment_path": "/tmp/exp",
            "git_commit_sha": "abc",
            "git_dirty": False,
        },
    )

    class Dummy:
        label = "Demo"
        var = SimpleNamespace(
            deployment_id="launch-old",
            local_deployment_id="other",
            local_experiment_path="/tmp/other",
        )
        _stamp_deployment_identity = Experiment._stamp_deployment_identity

    dummy = Dummy()
    assert dummy._stamp_deployment_identity() == "gibbs"
    assert dummy.var.deployment_id == "launch-new"
    assert dummy.var.local_deployment_id == "gibbs"
    assert dummy.var.local_experiment_path == "/tmp/exp"
    assert dummy.var.label == "Demo"
    assert dummy.var.git_commit_sha == "abc"
    assert dummy.var.git_dirty is False


def test_starting_a_participant_marks_shutdown_snapshot_needed():
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    class Dummy:
        var = SimpleNamespace()
        _managed_local_live_deployment_info = staticmethod(
            lambda: {"local_id": "gibbs"}
        )
        mark_local_snapshot_needed_on_shutdown = (
            Experiment.mark_local_snapshot_needed_on_shutdown
        )

    dummy = Dummy()
    dummy.mark_local_snapshot_needed_on_shutdown()
    assert dummy.var.local_snapshot_needed_on_shutdown is True


def test_starting_a_participant_does_not_mark_debug_runs():
    from types import SimpleNamespace

    from psynet.experiment import Experiment

    class Dummy:
        var = SimpleNamespace()
        _managed_local_live_deployment_info = staticmethod(lambda: None)
        mark_local_snapshot_needed_on_shutdown = (
            Experiment.mark_local_snapshot_needed_on_shutdown
        )

    dummy = Dummy()
    dummy.mark_local_snapshot_needed_on_shutdown()
    assert not hasattr(dummy.var, "local_snapshot_needed_on_shutdown")

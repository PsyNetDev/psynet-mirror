"""Isolated tests for ``psynet simulate --audit`` packaging."""

from pathlib import Path
from zipfile import ZipFile

import click
import pytest


def _write_export_tree(root: Path) -> Path:
    export_dir = root / "data" / "simulated_data"
    csv_dir = export_dir / "regular" / "data"
    csv_dir.mkdir(parents=True)
    (csv_dir / "AnimalTrial.csv").write_text("id\n1\n", encoding="utf-8")
    return export_dir


def test_resolve_audit_artifact_path_creates_artifacts(tmp_path, monkeypatch):
    from psynet.command_line import (
        AUDIT_SIMULATED_DATA_ZIP,
        resolve_audit_artifact_path,
    )

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "audit.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_audit_artifact_path(AUDIT_SIMULATED_DATA_ZIP)
    assert (
        resolved.resolve() == (audit_dir / "artifacts" / "simulated_data.zip").resolve()
    )
    assert (audit_dir / "artifacts").is_dir()


def test_resolve_audit_artifact_path_autodetects_nested_audit(tmp_path, monkeypatch):
    from psynet.command_line import (
        AUDIT_SIMULATED_DATA_ZIP,
        resolve_audit_artifact_path,
    )

    experiment = tmp_path / "exp"
    audit_dir = experiment / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(experiment)

    resolved = resolve_audit_artifact_path(AUDIT_SIMULATED_DATA_ZIP)
    assert (
        resolved.resolve() == (audit_dir / "artifacts" / "simulated_data.zip").resolve()
    )


def test_write_directory_zip_preserves_data_prefix(tmp_path, monkeypatch):
    from psynet.command_line import write_directory_zip

    monkeypatch.chdir(tmp_path)
    export_dir = _write_export_tree(tmp_path)
    zip_path = tmp_path / "out" / "simulated_data.zip"

    write_directory_zip(export_dir, zip_path)

    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "data/simulated_data/regular/data/AnimalTrial.csv" in names


def test_write_directory_zip_overwrites_existing_archive(tmp_path, monkeypatch):
    from psynet.command_line import write_directory_zip

    monkeypatch.chdir(tmp_path)
    export_dir = _write_export_tree(tmp_path)
    zip_path = tmp_path / "simulated_data.zip"
    zip_path.write_bytes(b"stale")

    write_directory_zip(export_dir, zip_path)

    with ZipFile(zip_path) as archive:
        assert "data/simulated_data/regular/data/AnimalTrial.csv" in archive.namelist()


def test_write_directory_zip_requires_directory(tmp_path):
    from psynet.command_line import write_directory_zip

    with pytest.raises(click.UsageError, match="is not a directory"):
        write_directory_zip(tmp_path / "missing", tmp_path / "out.zip")


def test_write_directory_zip_rejects_empty_tree(tmp_path, monkeypatch):
    from psynet.command_line import write_directory_zip

    monkeypatch.chdir(tmp_path)
    empty = tmp_path / "data" / "simulated_data"
    empty.mkdir(parents=True)
    (empty / "regular").mkdir()
    zip_path = tmp_path / "artifacts" / "simulated_data.zip"

    with pytest.raises(click.UsageError, match="contains no files"):
        write_directory_zip(empty, zip_path)

    assert not zip_path.exists()
    assert not zip_path.with_name(zip_path.name + ".partial").exists()


def test_run_simulate_audit_requires_packet_before_test(tmp_path, monkeypatch):
    from psynet.command_line import _run_simulate

    monkeypatch.chdir(tmp_path)
    calls = []

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            calls.append(cmd)

    with pytest.raises(click.UsageError, match="No audit packet found"):
        _run_simulate(DummyCtx(), audit=True)

    assert calls == []


def test_resolve_audit_root_from_inside_audit_errors(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import resolve_audit_root

    experiment = tmp_path / "exp"
    init_audit(experiment / "audit")
    monkeypatch.chdir(experiment / "audit")

    with pytest.raises(click.UsageError, match="not from audit/"):
        resolve_audit_root()


def test_run_simulate_without_audit_does_not_zip(tmp_path, monkeypatch):
    from psynet.command_line import (
        _run_simulate,
        export__local,
        test__local,
    )

    monkeypatch.chdir(tmp_path)
    calls = []

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd is export__local:
                _write_export_tree(tmp_path)

    _run_simulate(DummyCtx(), audit=False)

    assert [cmd for cmd, _ in calls] == [test__local, export__local]
    assert not list(tmp_path.glob("**/*.zip"))


def test_run_simulate_audit_zips_export_and_marks_present(tmp_path, monkeypatch):
    import json

    from psynet.audit.cli import init_audit
    from psynet.command_line import _run_simulate, export__local

    experiment = tmp_path / "exp"
    audit_dir = experiment / "audit"
    init_audit(audit_dir)
    monkeypatch.chdir(experiment)

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            if cmd is export__local:
                _write_export_tree(experiment)

    _run_simulate(DummyCtx(), audit=True)

    zip_path = audit_dir / "artifacts" / "simulated_data.zip"
    assert zip_path.is_file()
    with ZipFile(zip_path) as archive:
        assert "data/simulated_data/regular/data/AnimalTrial.csv" in archive.namelist()
    assert (
        experiment / "data" / "simulated_data" / "regular" / "data" / "AnimalTrial.csv"
    ).is_file()
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "simulation_export")
    assert artifact["status"] == "present"
    assert all(b["artifact_id"] != "simulation_export" for b in manifest["blockers"])


def test_run_simulate_audit_can_skip_mark_present(tmp_path, monkeypatch):
    import json

    from psynet.audit.cli import init_audit
    from psynet.command_line import _run_simulate, export__local

    experiment = tmp_path / "exp"
    audit_dir = experiment / "audit"
    init_audit(audit_dir)
    monkeypatch.chdir(experiment)

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            if cmd is export__local:
                _write_export_tree(experiment)

    _run_simulate(DummyCtx(), audit=True, mark_present=False)

    assert (audit_dir / "artifacts" / "simulated_data.zip").is_file()
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "simulation_export")
    assert artifact["status"] == "blocked"
    assert any(b["artifact_id"] == "simulation_export" for b in manifest["blockers"])


def test_mark_audit_artifact_present_updates_declared_path(tmp_path, monkeypatch):
    import json

    from psynet.audit.cli import init_audit
    from psynet.command_line import (
        AUDIT_PERFORMANCE_JSON,
        mark_audit_artifact_present,
    )

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    manifest_path = audit_dir / "audit.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "performance_result")
    artifact["path"] = "artifacts/custom_performance.json"
    (audit_dir / "artifacts" / "custom_performance.json").write_text(
        "{}\n", encoding="utf-8"
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (audit_dir / "artifacts" / "performance.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    mark_audit_artifact_present(AUDIT_PERFORMANCE_JSON)

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = next(a for a in updated["artifacts"] if a["id"] == "performance_result")
    assert artifact["status"] == "present"
    assert artifact["path"] == "artifacts/performance.json"


def test_mark_audit_artifact_present_updates_performance_result(tmp_path, monkeypatch):
    import json

    from psynet.audit.cli import init_audit
    from psynet.command_line import (
        AUDIT_PERFORMANCE_JSON,
        mark_audit_artifact_present,
    )

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    (audit_dir / "artifacts" / "performance.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    mark_audit_artifact_present(AUDIT_PERFORMANCE_JSON)

    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "performance_result")
    assert artifact["status"] == "present"
    assert all(b["artifact_id"] != "performance_result" for b in manifest["blockers"])


def test_no_mark_present_requires_audit():
    from psynet.command_line import require_audit_when_skipping_mark_present

    require_audit_when_skipping_mark_present(True, True)
    with pytest.raises(click.UsageError, match="requires --audit"):
        require_audit_when_skipping_mark_present(False, True)


def test_simulate_no_mark_present_without_audit_errors(monkeypatch):
    from click.testing import CliRunner

    from psynet.command_line import simulate

    monkeypatch.setattr("psynet.utils.experiment_available", lambda: True)
    monkeypatch.setattr(
        "psynet.utils.ensure_experiment_directory_name_does_not_conflict",
        lambda: None,
    )

    result = CliRunner().invoke(simulate, ["--no-mark-present"])
    assert result.exit_code != 0
    assert "requires --audit" in result.output


def test_performance_results_have_successful_bots():
    from psynet.command_line import performance_results_have_successful_bots

    assert not performance_results_have_successful_bots([])
    assert not performance_results_have_successful_bots(
        [{"n_bots": 2, "bots_succeeded": 0}]
    )
    assert performance_results_have_successful_bots(
        [
            {"n_bots": 1, "bots_succeeded": 0},
            {"n_bots": 2, "bots_succeeded": 1},
        ]
    )


def test_maybe_mark_performance_result_skips_zero_success(
    tmp_path, capsys, monkeypatch
):
    import json

    from psynet.audit.cli import init_audit
    from psynet.command_line import maybe_mark_performance_result_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    (audit_dir / "artifacts" / "performance.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    maybe_mark_performance_result_present(
        True,
        [{"n_bots": 2, "bots_succeeded": 0}],
        mark_present=True,
    )

    captured = capsys.readouterr()
    assert "no bots succeeded" in captured.err
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "performance_result")
    assert artifact["status"] == "blocked"


def test_simulate_help_documents_audit_option():
    from click.testing import CliRunner

    from psynet.command_line import simulate

    result = CliRunner().invoke(simulate, ["--help"])
    assert result.exit_code == 0
    assert "--audit" in result.output
    assert "simulated_data.zip" in result.output
    assert "--no-mark-present" in result.output
    assert "simulation_export" in result.output


def test_performance_test_ssh_help_documents_no_mark_present(monkeypatch):
    from click.testing import CliRunner

    from psynet.command_line import performance_test__docker_ssh

    monkeypatch.setattr("psynet.utils.experiment_available", lambda: True)
    monkeypatch.setattr(
        "psynet.utils.ensure_experiment_directory_name_does_not_conflict",
        lambda: None,
    )

    result = CliRunner().invoke(performance_test__docker_ssh, ["--help"])
    assert result.exit_code == 0
    assert "--no-mark-present" in result.output
    assert "--audit" in result.output


def test_performance_test_ssh_rejects_audit():
    from psynet.command_line import performance_test__docker_ssh

    with click.Context(performance_test__docker_ssh):
        with pytest.raises(click.UsageError, match="not yet implemented for SSH mode"):
            performance_test__docker_ssh.callback(
                app="example",
                server="example",
                audit=True,
            )

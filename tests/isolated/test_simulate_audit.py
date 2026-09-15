"""Isolated tests for audit simulation and performance evidence."""

import json
from pathlib import Path

import click
import pytest


def _write_export_tree(export_dir: Path) -> Path:
    csv_dir = export_dir / "database"
    csv_dir.mkdir(parents=True)
    (csv_dir / "AnimalTrial.csv").write_text("id\n1\n", encoding="utf-8")
    return export_dir


def test_resolve_simulated_export_path(tmp_path, monkeypatch):
    from psynet.command_line import (
        SIMULATED_EXPORT_PATH,
        resolve_audit_artifact_path,
    )

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "audit.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_audit_artifact_path(SIMULATED_EXPORT_PATH)

    assert (
        resolved.resolve()
        == (audit_dir / "simulate" / "analysis" / "simulated_export").resolve()
    )
    assert resolved.parent.is_dir()


def test_run_simulate_requires_audit_packet_before_test(tmp_path, monkeypatch):
    from psynet.command_line import _run_simulate

    monkeypatch.chdir(tmp_path)
    calls = []

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            calls.append(cmd)

    with pytest.raises(click.UsageError, match="No audit packet found"):
        _run_simulate(DummyCtx())

    assert calls == []


def test_resolve_audit_root_from_inside_audit_errors(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import resolve_audit_root

    experiment = tmp_path / "exp"
    init_audit(experiment / "audit")
    monkeypatch.chdir(experiment / "audit")

    with pytest.raises(click.UsageError, match="not from audit/"):
        resolve_audit_root()


def test_run_simulate_writes_only_audit_export_and_marks_present(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import _run_simulate, export__local

    experiment = tmp_path / "exp"
    audit_dir = experiment / "audit"
    init_audit(audit_dir)
    monkeypatch.chdir(experiment)
    stale = audit_dir / "simulate" / "analysis" / "simulated_export" / "stale.csv"
    stale.parent.mkdir(parents=True)
    stale.write_text("obsolete\n", encoding="utf-8")

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            if cmd is export__local:
                _write_export_tree(Path(kwargs["path"]))

    _run_simulate(DummyCtx())

    export = audit_dir / "simulate" / "analysis" / "simulated_export"
    assert (export / "database" / "AnimalTrial.csv").is_file()
    assert not stale.exists()
    assert not (experiment / "data" / "simulated_data").exists()
    assert not list(audit_dir.glob("**/*.zip"))
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "simulate_export")
    assert artifact["status"] == "present"
    assert all(b["artifact_id"] != "simulate_export" for b in manifest["blockers"])


def test_run_simulate_rejects_an_empty_export(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import _run_simulate

    experiment = tmp_path / "exp"
    init_audit(experiment / "audit")
    monkeypatch.chdir(experiment)

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            pass

    with pytest.raises(
        click.ClickException, match=r"produced no files in .+\.simulated_export"
    ):
        _run_simulate(DummyCtx())


def test_run_simulate_keeps_previous_export_when_export_fails(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit, mark_artifact_present
    from psynet.command_line import SIMULATED_EXPORT_PATH, _run_simulate, export__local

    experiment = tmp_path / "exp"
    audit_dir = experiment / "audit"
    init_audit(audit_dir)
    previous = _write_export_tree(audit_dir / SIMULATED_EXPORT_PATH)
    mark_artifact_present(audit_dir, "simulate_export")
    monkeypatch.chdir(experiment)

    class DummyCtx:
        def invoke(self, cmd, **kwargs):
            if cmd is export__local:
                raise click.ClickException("export failed")

    with pytest.raises(click.ClickException, match="export failed"):
        _run_simulate(DummyCtx())

    assert (previous / "database" / "AnimalTrial.csv").is_file()
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "simulate_export")
    assert artifact["status"] == "present"
    staging_dirs = list(
        (audit_dir / "simulate" / "analysis").glob(".simulated_export*")
    )
    assert staging_dirs == []


def test_mark_present_accepts_nonempty_directory(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import SIMULATED_EXPORT_PATH, mark_audit_artifact_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    _write_export_tree(audit_dir / SIMULATED_EXPORT_PATH)
    monkeypatch.chdir(tmp_path)

    mark_audit_artifact_present(SIMULATED_EXPORT_PATH)

    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "simulate_export")
    assert artifact["status"] == "present"


def test_mark_present_rejects_empty_directory(tmp_path, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import SIMULATED_EXPORT_PATH, mark_audit_artifact_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    (audit_dir / SIMULATED_EXPORT_PATH).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(click.ClickException, match="missing or empty"):
        mark_audit_artifact_present(SIMULATED_EXPORT_PATH)


def test_mark_audit_artifact_present_updates_declared_path(tmp_path, monkeypatch):
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
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (audit_dir / "artifacts" / "performance.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    mark_audit_artifact_present(AUDIT_PERFORMANCE_JSON)

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = next(a for a in updated["artifacts"] if a["id"] == "performance_result")
    assert artifact["status"] == "present"
    assert artifact["path"] == "artifacts/performance.json"


def test_mark_audit_artifact_present_updates_performance_result(tmp_path, monkeypatch):
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


def test_mark_performance_result_skips_zero_success(tmp_path, capsys, monkeypatch):
    from psynet.audit.cli import init_audit
    from psynet.command_line import mark_performance_result_present

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    (audit_dir / "artifacts" / "performance.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    mark_performance_result_present([{"n_bots": 2, "bots_succeeded": 0}])

    captured = capsys.readouterr()
    assert "no bots succeeded" in captured.err
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(a for a in manifest["artifacts"] if a["id"] == "performance_result")
    assert artifact["status"] == "blocked"


def test_simulate_help_describes_canonical_output():
    from click.testing import CliRunner

    from psynet.command_line import psynet

    result = CliRunner().invoke(psynet, ["audit", "simulate", "--help"])

    assert result.exit_code == 0
    assert "write the simulated export into the audit packet" in result.output


def test_top_level_simulate_command_is_removed():
    from click.testing import CliRunner

    from psynet.command_line import psynet

    result = CliRunner().invoke(psynet, ["simulate"])

    assert result.exit_code != 0
    assert "No such command 'simulate'" in result.output


def test_performance_test_routes_separate_measurement_and_audit_output(monkeypatch):
    from click.testing import CliRunner

    from psynet.command_line import psynet

    monkeypatch.setattr("psynet.utils.experiment_available", lambda: True)
    monkeypatch.setattr(
        "psynet.utils.ensure_experiment_directory_name_does_not_conflict",
        lambda: None,
    )
    runner = CliRunner()
    measurement = runner.invoke(psynet, ["performance-test", "local", "--help"])
    evidence = runner.invoke(psynet, ["audit", "performance-test", "--help"])

    assert measurement.exit_code == 0
    assert "--json-output" in measurement.output
    assert "--audit" not in measurement.output
    assert evidence.exit_code == 0
    assert "--json-output" not in evidence.output
    assert "--audit" not in evidence.output
    assert "Commands:" not in evidence.output


def test_audit_performance_test_writes_canonical_output_and_marks_present(
    tmp_path, monkeypatch
):
    from click.testing import CliRunner

    from psynet.audit.cli import init_audit
    from psynet.command_line import psynet

    audit_dir = tmp_path / "audit"
    init_audit(audit_dir)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("psynet.utils.experiment_available", lambda: True)
    monkeypatch.setattr(
        "psynet.utils.ensure_experiment_directory_name_does_not_conflict",
        lambda: None,
    )

    def run_performance_test(**kwargs):
        Path(kwargs["json_output"]).write_text("{}\n", encoding="utf-8")
        return [{"bots_succeeded": 1}]

    monkeypatch.setattr(
        "psynet.command_line._run_performance_test_local",
        run_performance_test,
    )

    result = CliRunner().invoke(
        psynet,
        ["audit", "performance-test", "--n-bots", "5"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert (audit_dir / "artifacts" / "performance.json").is_file()
    manifest = json.loads((audit_dir / "audit.json").read_text(encoding="utf-8"))
    artifact = next(
        item for item in manifest["artifacts"] if item["id"] == "performance_result"
    )
    assert artifact["status"] == "present"
    assert "Marked performance_result present" in result.output


def test_performance_test_ssh_rejects_json_output():
    from psynet.command_line import performance_test__docker_ssh

    with click.Context(performance_test__docker_ssh):
        with pytest.raises(click.UsageError, match="not yet implemented for SSH mode"):
            performance_test__docker_ssh.callback(
                app="example",
                server="example",
                json_output="results.json",
            )

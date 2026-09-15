"""Tests for experiment deployment event history."""

import json
import sys
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from rich.console import Console


def test_append_event_includes_comment_and_argv(tmp_path):
    from psynet.deployment_events import append_deployment_event, load_deployment_events

    append_deployment_event(
        tmp_path,
        "export.failed",
        comment="End of day",
        argv=["psynet", "export", "ssh", "--app", "demo"],
        error="connection refused",
        target="ssh",
        app="demo",
    )
    events = load_deployment_events(tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "export.failed"
    assert event["comment"] == "End of day"
    assert event["argv"] == ["psynet", "export", "ssh", "--app", "demo"]
    assert event["error"] == "connection refused"
    assert event["app"] == "demo"


def test_event_details_redacts_password_and_username():
    from psynet.deployment_events import event_details, redact_command_argv

    assert redact_command_argv(
        ["psynet", "export", "ssh", "--password", "s3cret", "--app", "demo"]
    ) == [
        "psynet",
        "export",
        "ssh",
        "--password",
        "<redacted>",
        "--app",
        "demo",
    ]
    assert redact_command_argv(
        ["psynet", "export", "ssh", "--password=s3cret", "--username=lab"]
    ) == [
        "psynet",
        "export",
        "ssh",
        "--password=<redacted>",
        "--username=<redacted>",
    ]
    details = event_details(argv=["psynet", "export", "local", "--password", "hunter2"])
    assert details["argv"] == [
        "psynet",
        "export",
        "local",
        "--password",
        "<redacted>",
    ]
    assert "hunter2" not in details["argv"]


def test_load_deployment_events_records_truncated_tail(tmp_path):
    from psynet.deployment_events import (
        append_deployment_event,
        deployment_event_log,
        load_deployment_events,
    )

    append_deployment_event(tmp_path, "deploy.succeeded", argv=["psynet", "deploy"])
    path = deployment_event_log(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8") + '{"event":"deploy.fai', encoding="utf-8"
    )
    events = load_deployment_events(tmp_path)
    assert events[0]["event"] == "deploy.succeeded"
    assert events[-1]["event"] == "log.truncated"
    assert "Truncated event" in events[-1]["error"]


def test_comment_is_free_floating(tmp_path):
    from psynet.command_line import psynet
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    runner = CliRunner()
    with working_directory(tmp_path):
        result = runner.invoke(psynet, ["comment", "Changed headphones."])

    assert result.exit_code == 0, result.output
    event = json.loads((tmp_path / "data/deployment-events.jsonl").read_text().strip())
    assert event["event"] == "comment"
    assert event["text"] == "Changed headphones."
    assert "id" not in event
    assert "argv" in event


def test_comment_optional_app_association(tmp_path):
    from psynet.command_line import psynet
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    runner = CliRunner()
    with working_directory(tmp_path):
        result = runner.invoke(
            psynet,
            ["comment", "--app", "my-app", "Paused recruitment."],
        )

    assert result.exit_code == 0, result.output
    event = json.loads((tmp_path / "data/deployment-events.jsonl").read_text().strip())
    assert event["app"] == "my-app"
    assert event["text"] == "Paused recruitment."


def test_history_highlights_comments(tmp_path):
    from psynet.deployment_events import (
        append_deployment_event,
        load_deployment_events,
        render_deployment_history,
    )

    append_deployment_event(
        tmp_path,
        "deploy.succeeded",
        target="ssh",
        app="demo",
        comment="Go live",
        argv=["psynet", "deploy", "ssh"],
    )
    append_deployment_event(
        tmp_path,
        "comment",
        text="Changed headphones.",
        author="alice@lab",
        argv=["psynet", "comment", "Changed headphones."],
    )
    append_deployment_event(
        tmp_path,
        "export.failed",
        error="disk full",
        argv=["psynet", "export", "local"],
    )

    console = Console(record=True, width=120, color_system=None)
    render_deployment_history(load_deployment_events(tmp_path), console=console)
    plain = console.export_text()
    assert "Changed headphones." in plain
    assert "deploy.succeeded" in plain
    assert "export.failed" in plain
    assert "disk full" in plain
    assert "Go live" in plain
    assert "✎" in plain


def test_history_command_json_and_empty(tmp_path):
    from psynet.command_line import psynet
    from psynet.deployment_events import append_deployment_event
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    runner = CliRunner()
    with working_directory(tmp_path):
        empty = runner.invoke(psynet, ["history"])
        assert empty.exit_code == 0, empty.output
        assert "No deployment events yet" in empty.output

        append_deployment_event(
            tmp_path,
            "sandbox.succeeded",
            mode="sandbox",
            target="heroku",
            app="sandbox-app",
            argv=["psynet", "debug", "heroku"],
        )
        result = runner.invoke(psynet, ["history", "--json"])

    assert result.exit_code == 0, result.output
    event = json.loads(result.output.strip())
    assert event["event"] == "sandbox.succeeded"
    assert event["mode"] == "sandbox"


def test_post_deploy_records_sandbox_succeeded(monkeypatch, tmp_path):
    from psynet.command_line import _post_deploy
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")

    monkeypatch.setattr(
        "psynet.command_line.export_launch_data",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.command_line.deployment_info.read",
        lambda key: "deployment-1",
    )
    monkeypatch.setattr(
        "psynet.command_line.deployment_info.read_all",
        lambda: {
            "mode": "sandbox",
            "is_ssh_deployment": False,
            "app": "sandbox-app",
            "server": None,
            "deployment_id": "deployment-1",
        },
    )

    with working_directory(tmp_path):
        _post_deploy(
            {"dashboard_user": "u", "dashboard_password": "p"},
            comment="Sandbox check",
            argv=["psynet", "debug", "heroku", "--app", "sandbox-app"],
        )

    event = json.loads((tmp_path / "data/deployment-events.jsonl").read_text().strip())
    assert event["event"] == "sandbox.succeeded"
    assert event["comment"] == "Sandbox check"
    assert event["argv"][0:3] == ["psynet", "debug", "heroku"]


def test_post_deploy_records_generated_app_name(monkeypatch, tmp_path):
    from psynet.command_line import _post_deploy
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    written = {}
    monkeypatch.setattr(
        "psynet.command_line.export_launch_data",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "psynet.command_line.deployment_info.read",
        lambda key: "deployment-1",
    )
    monkeypatch.setattr(
        "psynet.command_line.deployment_info.read_all",
        lambda: {
            "mode": "live",
            "is_ssh_deployment": True,
            "app": None,
            "server": "lab",
            "deployment_id": "deployment-1",
        },
    )
    monkeypatch.setattr(
        "psynet.command_line.deployment_info.write",
        lambda **kwargs: written.update(kwargs),
    )

    with working_directory(tmp_path):
        _post_deploy(
            {
                "dashboard_user": "u",
                "dashboard_password": "p",
                "dashboard_link": "https://u:p@dlgr-a1b2c3d4.lab.example.com/dashboard",
            },
            argv=["psynet", "deploy", "ssh"],
        )

    event = json.loads((tmp_path / "data/deployment-events.jsonl").read_text().strip())
    assert event["event"] == "deploy.succeeded"
    assert event["app"] == "dlgr-a1b2c3d4"
    assert written["app"] == "dlgr-a1b2c3d4"


def test_destroy_records_comment_on_success(monkeypatch, tmp_path):
    from psynet.command_line import _destroy
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")

    class DummyCtx:
        def invoke(self, f_destroy, **kwargs):
            return f_destroy(**kwargs)

    def fake_destroy(**kwargs):
        assert kwargs["app"] == "demo-app"
        return None

    monkeypatch.setattr("psynet.command_line.user_confirms", lambda *a, **k: True)
    monkeypatch.setattr("psynet.command_line.get_args", lambda func: ())

    with working_directory(tmp_path):
        _destroy(
            DummyCtx(),
            fake_destroy,
            app="demo-app",
            comment="Wrong country",
        )

    events = [
        json.loads(line)
        for line in (tmp_path / "data/deployment-events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == [
        "destroy.requested",
        "destroy.succeeded",
    ]
    assert events[-1]["comment"] == "Wrong country"
    assert events[-1]["app"] == "demo-app"
    assert "argv" in events[-1]


def test_destroy_records_failure_for_generic_exceptions(monkeypatch, tmp_path):
    from psynet.command_line import _destroy
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")

    class DummyCtx:
        def invoke(self, f_destroy, **kwargs):
            return f_destroy(**kwargs)

    def fake_destroy(**kwargs):
        raise RuntimeError("SSH connection reset")

    monkeypatch.setattr("psynet.command_line.user_confirms", lambda *a, **k: True)
    monkeypatch.setattr("psynet.command_line.get_args", lambda func: ())

    with working_directory(tmp_path):
        with pytest.raises(RuntimeError, match="SSH connection reset"):
            _destroy(
                DummyCtx(),
                fake_destroy,
                app="demo-app",
            )

    events = [
        json.loads(line)
        for line in (tmp_path / "data/deployment-events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == [
        "destroy.requested",
        "destroy.failed",
    ]
    assert "SSH connection reset" in events[-1]["error"]


def test_filter_deployment_events_by_type_and_command():
    from psynet.deployment_events import filter_deployment_events

    events = [
        {"event": "deploy.succeeded", "argv": ["psynet", "deploy", "ssh"]},
        {
            "event": "export.failed",
            "error": "boom",
            "argv": ["psynet", "export", "ssh"],
        },
        {"event": "comment", "text": "note", "argv": ["psynet", "comment"]},
        {
            "event": "destroy.succeeded",
            "comment": "cleanup",
            "argv": ["psynet", "destroy", "ssh"],
        },
        {"event": "sandbox.failed", "argv": ["psynet", "debug", "heroku"]},
        {"event": "snapshot.succeeded", "reason": "participant_finished"},
    ]

    failures = filter_deployment_events(events, type_filter="failures")
    assert [event["event"] for event in failures] == [
        "export.failed",
        "sandbox.failed",
    ]

    comments = filter_deployment_events(events, type_filter="comments")
    assert [event["event"] for event in comments] == ["comment", "destroy.succeeded"]

    exports = filter_deployment_events(events, command_filter="export")
    assert [event["event"] for event in exports] == ["export.failed"]

    snapshots = filter_deployment_events(events, command_filter="snapshot")
    assert [event["event"] for event in snapshots] == ["snapshot.succeeded"]


def test_browse_falls_back_to_static_when_not_a_tty(tmp_path, monkeypatch):
    from io import StringIO

    from rich.console import Console

    from psynet.deployment_events import (
        append_deployment_event,
        browse_deployment_history,
        load_deployment_events,
    )

    append_deployment_event(
        tmp_path,
        "deploy.succeeded",
        argv=["psynet", "deploy", "local", "--id", "gibbs"],
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None)
    monkeypatch.setattr(sys, "stdin", StringIO())

    browse_deployment_history(load_deployment_events(tmp_path), console=console)
    assert "deploy.succeeded" in output.getvalue()


def test_textual_history_app_filters_and_arrows():
    import asyncio

    from psynet.deployment_history_app import DeploymentHistoryApp

    events = [
        {
            "event": "deploy.succeeded",
            "at": "2026-01-01T00:00:00Z",
            "argv": ["psynet", "deploy", "ssh"],
        },
        {
            "event": "export.failed",
            "at": "2026-01-01T00:01:00Z",
            "error": "boom",
            "argv": ["psynet", "export", "ssh"],
        },
        {
            "event": "comment",
            "at": "2026-01-01T00:02:00Z",
            "text": "hi",
            "argv": ["psynet", "comment"],
        },
    ]

    async def run():
        app = DeploymentHistoryApp(events)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.type_filter == "all"
            await pilot.press("f")
            await pilot.pause()
            assert app.type_filter == "failures"
            assert len(app._visible_events()) == 1
            await pilot.press("up")
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert app.type_filter == "comments"
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            assert app.command_filter == "export"
            assert [e["event"] for e in app._visible_events()] == ["export.failed"]

    asyncio.run(run())


def test_history_no_interactive_flag(tmp_path):
    from psynet.command_line import psynet
    from psynet.deployment_events import append_deployment_event
    from psynet.utils import working_directory

    (tmp_path / "experiment.py").write_text("")
    append_deployment_event(
        tmp_path,
        "export.succeeded",
        argv=["psynet", "export", "local"],
    )
    runner = CliRunner()
    with working_directory(tmp_path):
        result = runner.invoke(psynet, ["history", "--no-interactive"])

    assert result.exit_code == 0, result.output
    assert "export.succeeded" in result.output


def test_periodic_local_snapshot_skips_when_no_new_responses(monkeypatch):
    from psynet.experiment import Experiment
    from psynet.local_deployment import Snapshot

    monkeypatch.setattr(
        "psynet.experiment.Experiment._managed_local_live_deployment_info",
        staticmethod(
            lambda: {
                "local_experiment_path": "/tmp/exp",
                "local_id": "gibbs",
                "deployment_id": "launch-1",
            }
        ),
    )
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 4)
    latest = Snapshot(
        sequence=2,
        path=None,
        metadata_path=None,
        created_at="2026-09-15T12:00:00Z",
        reason="periodic",
        deployment_id="launch-1",
        parent_sequence=1,
        participant_count=1,
        sha256="abc",
        max_response_id=4,
    )
    monkeypatch.setattr(
        "psynet.local_deployment.list_snapshots", lambda *_args, **_kwargs: [latest]
    )
    create = Mock()
    monkeypatch.setattr(
        "psynet.experiment.Experiment.create_local_deployment_snapshot", create
    )
    assert Experiment.maybe_create_periodic_local_snapshot() is None
    create.assert_not_called()


def test_periodic_local_snapshot_writes_when_responses_grew(monkeypatch):
    from psynet.experiment import Experiment
    from psynet.local_deployment import Snapshot

    snapshot = Mock()
    monkeypatch.setattr(
        "psynet.experiment.Experiment._managed_local_live_deployment_info",
        staticmethod(
            lambda: {
                "local_experiment_path": "/tmp/exp",
                "local_id": "gibbs",
                "deployment_id": "launch-1",
            }
        ),
    )
    monkeypatch.setattr("psynet.local_deployment.read_response_watermark", lambda: 9)
    latest = Snapshot(
        sequence=2,
        path=None,
        metadata_path=None,
        created_at="2026-09-15T12:00:00Z",
        reason="periodic",
        deployment_id="launch-1",
        parent_sequence=1,
        participant_count=1,
        sha256="abc",
        max_response_id=4,
    )
    monkeypatch.setattr(
        "psynet.local_deployment.list_snapshots", lambda *_args, **_kwargs: [latest]
    )
    monkeypatch.setattr(
        "psynet.experiment.Experiment.create_local_deployment_snapshot",
        Mock(return_value=snapshot),
    )
    assert Experiment.maybe_create_periodic_local_snapshot() is snapshot
    Experiment.create_local_deployment_snapshot.assert_called_once_with("periodic")

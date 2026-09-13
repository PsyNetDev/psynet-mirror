"""Tests for experiment deployment event history."""

import json

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

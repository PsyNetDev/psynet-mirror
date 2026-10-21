import logging
from unittest.mock import Mock

import pytest

from psynet.notifier import LoggerNotifier, Notifier


def test_logger_notifier_redacts_dashboard_password():
    args = (
        "Experiment dashboard",
        "http://localhost:5000/dashboard",
        "admin",
        "s3cr3t",
    )
    assert "s3cr3t" in Notifier.format_credentials(*args)

    message = LoggerNotifier.format_credentials(*args)
    assert "s3cr3t" not in message
    assert "Username: `admin`" in message
    assert (
        "Password: not shown in logs "
        "(printed by the command that launched the experiment)" in message
    )


def test_logger_notifier_leaves_local_dashboard_details_to_the_banner(
    monkeypatch, caplog
):
    monkeypatch.setattr(
        "psynet.notifier.deployment_info.read_all",
        lambda: {"secret": "abc", "is_local_deployment": True},
    )

    class _DemoNotifier(LoggerNotifier):
        exp = Mock(label="Demo")

    with caplog.at_level(logging.INFO):
        _DemoNotifier().on_launch()

    assert 'Launched experiment "Demo" locally' in caplog.text
    assert "abc" not in caplog.text
    assert "Password:" not in caplog.text


@pytest.mark.parametrize(
    "ingress, logs_command, dns_record, expected",
    [
        (None, None, {}, "https://logs.lab"),
        ("classic", None, {}, "https://logs.lab"),
        (
            "classic",
            None,
            {"server_dns_host": "lab.example.org"},
            "https://logs.lab.example.org",
        ),
        # A deploy that found no DNS name for the server has no Dozzle link.
        ("classic", "ssh lab logs", {"server_dns_host": None}, "`ssh lab logs`"),
        ("cloudflare", "ssh lab logs", {}, "`ssh lab logs`"),
        ("cloudflare", None, {}, "printed at the end of the deployment"),
    ],
)
def test_logs_message_follows_the_app_ingress(
    monkeypatch, ingress, logs_command, dns_record, expected
):
    info = {
        "server": "lab",
        "ingress": ingress,
        "logs_command": logs_command,
        **dns_record,
    }
    monkeypatch.setattr("psynet.deployment_info.read_all", lambda: info)
    monkeypatch.setattr(
        "psynet.notifier.get_config", lambda: {"dashboard_password": "pw"}
    )

    message = Notifier().logs_message

    assert expected in message
    assert ("Dozzle" in message) is expected.startswith("https://")

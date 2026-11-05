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

    with caplog.at_level(logging.DEBUG):
        _DemoNotifier().on_launch()

    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("DEBUG", 'Launched experiment "Demo" locally')
    ]
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


def test_worker_message_skips_workers_that_exit_while_listed(monkeypatch):
    import psutil

    live = Mock()
    live.memory_info.return_value.rss = 50 * 1024**2
    live.create_time.return_value = 0
    live.name.return_value = "gunicorn"
    zombie = Mock()
    zombie.memory_info.side_effect = psutil.ZombieProcess(2)
    zombie.create_time.side_effect = psutil.ZombieProcess(2)
    monkeypatch.setattr(
        Notifier,
        "_get_worker_processes",
        staticmethod(lambda: [(2, zombie), (1, live)]),
    )

    message = Notifier()._get_worker_processes_message("ram")

    assert "gunicorn (1)" in message
    assert "(2)" not in message


def test_cpu_warning_lists_measured_worker_usage_busiest_first(monkeypatch):
    def worker(name, percent):
        proc = Mock()
        proc.create_time.return_value = 0
        proc.name.return_value = name
        proc.cpu_percent.side_effect = [0.0, percent]
        return proc

    monkeypatch.setattr("psynet.notifier._CPU_SAMPLE_SECONDS", 0)
    monkeypatch.setattr(
        Notifier,
        "_get_worker_processes",
        staticmethod(lambda: [(1, worker("idle", 2.0)), (2, worker("busy", 80.0))]),
    )

    message = Notifier()._get_worker_processes_message("cpu")

    assert "busy (2) running for" in message and "80.0% CPU" in message
    assert message.index("busy") < message.index("idle")

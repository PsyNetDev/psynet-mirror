import pytest
from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

from psynet.notifier import Notifier
from psynet.server_logs import where_to_read_logs

LOGS_COMMAND = (
    'ssh ubuntu@lab.example "docker compose -f '
    '~/dallinger/study/docker-compose.yml logs -f"'
)


@pytest.mark.parametrize(
    "default_ingress, expected",
    [
        (None, "in Dozzle at https://logs.lab"),
        ("cloudflare", f"with '{LOGS_COMMAND}'"),
    ],
)
def test_where_to_read_logs_follows_the_server_ingress(
    monkeypatch, default_ingress, expected
):
    host = {"host": "lab.example", "user": "ubuntu"}
    if default_ingress:
        host["default_ingress"] = default_ingress
    monkeypatch.setitem(CONFIGURED_HOSTS, "lab", host)

    assert where_to_read_logs("lab", "study") == expected


@pytest.mark.parametrize(
    "ingress, expected",
    [
        (None, "https://logs.lab"),
        ("classic", "https://logs.lab"),
        ("cloudflare", LOGS_COMMAND),
    ],
)
def test_notifier_logs_message_follows_the_app_ingress(monkeypatch, ingress, expected):
    info = {"server": "lab", "app": "study", "ssh_host": "lab.example"}
    info["ssh_user"] = "ubuntu"
    if ingress:
        info["ingress"] = ingress
    monkeypatch.setattr("psynet.deployment_info.read_all", lambda: info)
    monkeypatch.setattr(
        "psynet.notifier.get_config", lambda: {"dashboard_password": "pw"}
    )

    message = Notifier().logs_message

    assert expected in message
    assert ("Dozzle" in message) is (ingress != "cloudflare")

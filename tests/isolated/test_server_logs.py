from pathlib import Path

import pytest
from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

from psynet.server_logs import server_ingress, where_to_read_logs

CLOUDFLARE_HOST = {"host": "lab.example:2222", "default_ingress": "cloudflare"}
COMPOSE_LOGS = '"docker compose -f ~/dallinger/study/docker-compose.yml logs -f"'


@pytest.mark.parametrize(
    "server_info, option, expected",
    [
        ({}, None, "classic"),
        ({"default_ingress": "cloudflare"}, None, "cloudflare"),
        ({"default_ingress": "cloudflare"}, "classic", "classic"),
    ],
)
def test_server_ingress_prefers_the_option_to_the_server_default(
    server_info, option, expected
):
    assert server_ingress(server_info, option) == expected


@pytest.mark.parametrize(
    "host, pem, expected",
    [
        ({"host": "lab"}, "/keys/lab.pem", "in Dozzle at https://logs.lab"),
        (
            CLOUDFLARE_HOST,
            "/keys/lab.pem",
            f"with 'ssh -p 2222 -i /keys/lab.pem ubuntu@lab.example {COMPOSE_LOGS}'",
        ),
        (
            CLOUDFLARE_HOST,
            Path.home() / ".ssh" / "lab key.pem",
            f"with 'ssh -p 2222 -i ~/'.ssh/lab key.pem' ubuntu@lab.example {COMPOSE_LOGS}'",
        ),
    ],
)
def test_where_to_read_logs_follows_the_server_ingress(
    monkeypatch, host, pem, expected
):
    monkeypatch.setitem(CONFIGURED_HOSTS, "lab", {**host, "user": "ubuntu"})
    monkeypatch.setattr("dallinger.command_line.utils.get_server_pem_path", lambda: pem)

    assert where_to_read_logs("lab", "study") == expected

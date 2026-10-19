from pathlib import Path

import pytest
from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

from psynet import deployment_info
from psynet.server_logs import server_ingress, where_to_read_logs

CLOUDFLARE_HOST = {"host": "lab.example:2222", "default_ingress": "cloudflare"}
COMPOSE_LOGS = '"docker compose -f ~/dallinger/study/docker-compose.yml logs -f"'
CLOUDFLARE_LOGS = (
    f"with 'ssh -p 2222 -i /keys/lab.pem ubuntu@lab.example {COMPOSE_LOGS}'"
)


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
    "host, pem, record, expected",
    [
        (
            {"host": "lab"},
            "/keys/lab.pem",
            None,
            "probably in Dozzle at https://logs.lab",
        ),
        (CLOUDFLARE_HOST, "/keys/lab.pem", None, f"probably {CLOUDFLARE_LOGS}"),
        (
            CLOUDFLARE_HOST,
            Path.home() / ".ssh" / "lab key.pem",
            None,
            f"probably with 'ssh -p 2222 -i ~/'.ssh/lab key.pem' ubuntu@lab.example {COMPOSE_LOGS}'",
        ),
        # Recorded deployments of this app win over the server's default.
        (
            CLOUDFLARE_HOST,
            "/keys/lab.pem",
            ("study", "classic"),
            "in Dozzle at https://logs.lab",
        ),
        (
            {**CLOUDFLARE_HOST, "default_ingress": "classic"},
            "/keys/lab.pem",
            ("study", "cloudflare"),
            CLOUDFLARE_LOGS,
        ),
        (
            CLOUDFLARE_HOST,
            "/keys/lab.pem",
            ("other", "classic"),
            f"probably {CLOUDFLARE_LOGS}",
        ),
    ],
)
def test_where_to_read_logs_follows_the_app_ingress(
    monkeypatch, tmp_path, host, pem, record, expected
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(CONFIGURED_HOSTS, "lab", {**host, "user": "ubuntu"})
    monkeypatch.setattr("dallinger.command_line.utils.get_server_pem_path", lambda: pem)
    if record:
        app, ingress = record
        deployment_info.write_all({"server": "lab", "app": app, "ingress": ingress})

    assert where_to_read_logs("lab", "study") == expected

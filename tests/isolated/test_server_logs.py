from pathlib import Path

import pytest
from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

from psynet import deployment_info
from psynet.server_logs import server_dns_host, server_ingress, where_to_read_logs

CLOUDFLARE_HOST = {"host": "lab.example:2222", "default_ingress": "cloudflare"}
COMPOSE_LOGS = '"docker compose -f ~/dallinger/study/docker-compose.yml logs -f"'
CLOUDFLARE_LOGS = (
    f"with 'ssh -p 2222 -i /keys/lab.pem ubuntu@lab.example {COMPOSE_LOGS}'"
)
GUESSED = ", assuming it uses the server's default ingress"


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
    "server_info, dns_host, expected",
    [
        ({"host": "lab.example.org"}, None, "lab.example.org"),
        (
            {"host": "1.2.3.4", "dns_host": "lab.example.org"},
            "x.org",
            "lab.example.org",
        ),
        ({"host": "1.2.3.4:2222"}, "lab.example.org", "lab.example.org"),
        ({"host": "1.2.3.4"}, "nip.io", "1.2.3.4.nip.io"),
    ],
)
def test_server_dns_host_prefers_the_saved_name(server_info, dns_host, expected):
    assert server_dns_host(server_info, dns_host) == expected


@pytest.mark.parametrize(
    "host, pem, record, expected",
    [
        (
            {"host": "lab"},
            "/keys/lab.pem",
            None,
            f"in Dozzle at https://logs.lab{GUESSED}",
        ),
        (
            {"host": "1.2.3.4", "dns_host": "lab.example.org"},
            "/keys/lab.pem",
            None,
            f"in Dozzle at https://logs.lab.example.org{GUESSED}",
        ),
        (CLOUDFLARE_HOST, "/keys/lab.pem", None, CLOUDFLARE_LOGS + GUESSED),
        (
            CLOUDFLARE_HOST,
            Path.home() / ".ssh" / "lab key.pem",
            None,
            f"with 'ssh -p 2222 -i ~/'.ssh/lab key.pem' ubuntu@lab.example {COMPOSE_LOGS}'"
            + GUESSED,
        ),
        # Recorded deployments of this app win over the server's default.
        (
            CLOUDFLARE_HOST,
            "/keys/lab.pem",
            ("study", "classic"),
            "in Dozzle at https://logs.lab.example",
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
            CLOUDFLARE_LOGS + GUESSED,
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

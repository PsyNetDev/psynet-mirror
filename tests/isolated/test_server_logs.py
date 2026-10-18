import pytest
from dallinger.command_line.docker_ssh import CONFIGURED_HOSTS

from psynet.server_logs import server_ingress, where_to_read_logs


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
    "host, expected",
    [
        ({"host": "lab"}, "in Dozzle at https://logs.lab"),
        (
            {"host": "lab.example:2222", "default_ingress": "cloudflare"},
            "with 'ssh -p 2222 -i /keys/lab.pem ubuntu@lab.example "
            '"docker compose -f ~/dallinger/study/docker-compose.yml logs -f"\'',
        ),
    ],
)
def test_where_to_read_logs_follows_the_server_ingress(monkeypatch, host, expected):
    monkeypatch.setitem(CONFIGURED_HOSTS, "lab", {**host, "user": "ubuntu"})
    monkeypatch.setattr(
        "dallinger.command_line.utils.get_server_pem_path", lambda: "/keys/lab.pem"
    )

    assert where_to_read_logs("lab", "study") == expected

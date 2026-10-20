"""SSH export uses the deployment's public origin."""

import json
import subprocess

import pytest

from psynet.command_line import _ssh_dashboard_endpoint


def _config():
    class Config:
        def get(self, key, default=None):
            return {
                "dashboard_user": "local",
                "dashboard_password": "local-secret",
            }.get(key, default)

    return Config()


def _write_launch(root, name, payload, mtime):
    directory = root / "psynet-data" / "launch-data" / name
    directory.mkdir(parents=True)
    path = directory / "launch-info.json"
    path.write_text(json.dumps(payload))
    os_utime = __import__("os").utime
    os_utime(path, (mtime, mtime))


def test_ssh_export_uses_the_newest_public_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    shared = {
        "app": "rrpsy",
        "server": "rr-pc01.example",
        "dashboard_user": "admin",
        "dashboard_password": "deploy-secret",
    }
    _write_launch(
        tmp_path,
        "older",
        {**shared, "public_origin": "https://old.example"},
        10,
    )
    _write_launch(
        tmp_path,
        "newer",
        {**shared, "public_origin": "https://rrpsy.science-of-music.org/"},
        20,
    )
    _write_launch(
        tmp_path,
        "other",
        {**shared, "app": "other", "public_origin": "https://other.example"},
        30,
    )

    endpoint = _ssh_dashboard_endpoint("rrpsy", "rr-pc01.example", _config())

    assert endpoint.base_url == "https://rrpsy.science-of-music.org"
    assert endpoint.auth == ("admin", "deploy-secret")


def test_ssh_export_uses_launch_credentials_without_local_config(tmp_path, monkeypatch):
    class NoCredentials:
        def get(self, key, *default):
            if default:
                return default[0]
            raise KeyError(key)

    monkeypatch.setenv("HOME", str(tmp_path))
    launch = {
        "app": "rrpsy",
        "server": "rr-pc01.example",
        "dashboard_user": "admin",
        "dashboard_password": "deploy-secret",
        "public_origin": "https://rrpsy.example",
    }
    _write_launch(tmp_path, "only", launch, 10)

    endpoint = _ssh_dashboard_endpoint("rrpsy", "rr-pc01.example", NoCredentials())

    assert endpoint.auth == ("admin", "deploy-secret")


def test_ssh_export_reads_the_server_manifest_when_launch_info_is_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "psynet.command_line._remote_public_origin",
        lambda app, server: "https://rrpsy.science-of-music.org",
    )

    endpoint = _ssh_dashboard_endpoint("rrpsy", "rr-pc01.example", _config())

    assert endpoint.base_url == "https://rrpsy.science-of-music.org"
    assert endpoint.auth == ("local", "local-secret")


def test_ssh_export_keeps_the_app_server_name_for_classic_slots(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "psynet.command_line._remote_public_origin", lambda app, server: None
    )
    monkeypatch.setattr(
        "psynet.command_line.get_experiment_url",
        lambda app, server: f"https://{app}.{server}",
    )

    endpoint = _ssh_dashboard_endpoint("psynet-07", "musix.mus.cam.ac.uk", _config())

    assert endpoint.base_url == "https://psynet-07.musix.mus.cam.ac.uk"


OLD_ROOT_CADDYFILE = (
    "# Caddy\n{\n    grace_period 30s\n}\n\nmusix.example {\n    tls internal\n"
    "    handle /logs* {\n        reverse_proxy dozzle:8080\n    }\n"
    "    handle {\n        reverse_proxy dlgr-d8f9f2c4_web:5000\n    }\n}\n"
)
SERVER_CADDYFILE = (
    "{\n    grace_period 30s\n}\n\nmusix.example {\n    respond /health-check 200\n"
    "    tls internal\n    import root.d/*\n}\n\nlogs.musix.example {\n"
    "    reverse_proxy dozzle:8080\n}\n\nimport caddy.d/*\n"
)


@pytest.mark.parametrize(
    "files, origin",
    [
        # Released Dallinger routes the root domain in the Caddyfile itself.
        ({"Caddyfile": OLD_ROOT_CADDYFILE}, "https://musix.example"),
        # Newer Dallinger routes it with a root.d file.
        (
            {"Caddyfile": SERVER_CADDYFILE, "root.d/dlgr-d8f9f2c4": "reverse_proxy"},
            "https://musix.example",
        ),
        (
            {
                "Caddyfile": SERVER_CADDYFILE,
                "caddy.d/dlgr-d8f9f2c4": "lab.example.org {\n    tls internal\n"
                "    reverse_proxy dlgr-d8f9f2c4_web:5000\n}",
            },
            "https://lab.example.org",
        ),
        (
            {
                "Caddyfile": OLD_ROOT_CADDYFILE,
                "dlgr-d8f9f2c4/deployment.json": json.dumps(
                    {"public_origin": "https://exp.example.org"}
                ),
            },
            "https://exp.example.org",
        ),
    ],
)
def test_ssh_export_finds_classic_apps_from_the_servers_caddy_routes(
    tmp_path, monkeypatch, files, origin
):
    """Without a launch note, the server's routes give the app's address."""
    for name, text in files.items():
        path = tmp_path / "dallinger" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    class Server:
        """Runs the SSH commands locally, with the server's home in ``tmp_path``."""

        def __init__(self, server):
            self.executor = self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run(self, cmd, raise_=True):
            return subprocess.run(
                cmd, shell=True, capture_output=True, text=True
            ).stdout

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("psynet.export.client.SshSession", Server)

    endpoint = _ssh_dashboard_endpoint("dlgr-d8f9f2c4", "musix.example", _config())

    assert endpoint.base_url == origin

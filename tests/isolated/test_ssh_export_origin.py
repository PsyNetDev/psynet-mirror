"""SSH export uses the deployment's public origin."""

import json

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

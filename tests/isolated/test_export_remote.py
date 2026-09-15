"""Tests for remote export identity rechecks, fallback, and SSH lifetime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from psynet.export.client import SshSession, TransferError


@pytest.fixture
def stub_ssh_connection():
    """Stub the SSH machinery used by export, sharing one connection."""
    executor = Mock()
    executor.run.return_value = "/home/testuser\n"
    with (
        patch(
            "dallinger.command_line.docker_ssh.CONFIGURED_HOSTS",
            {"test-server": {"host": "test-host", "user": "test-user"}},
        ),
        patch(
            "dallinger.command_line.docker_ssh.Executor", return_value=executor
        ) as connect,
    ):
        yield executor, connect


def test_ssh_session_closes_after_a_failed_step(stub_ssh_connection):
    executor, _connect = stub_ssh_connection
    with pytest.raises(RuntimeError):
        with SshSession("test-server") as session:
            assert session.executor is executor
            raise RuntimeError("download failed")
    executor.client.close.assert_called_once()


def test_ssh_session_closes_after_an_identity_rejection(stub_ssh_connection):
    executor, _connect = stub_ssh_connection
    with pytest.raises(TransferError):
        with SshSession("test-server") as session:
            _ = session.executor
            raise TransferError("identity mismatch")
    executor.client.close.assert_called_once()


def _remote_export_env(tmp_path, monkeypatch, *, preflight, manifest, docker_ssh=True):
    from psynet.command_line import _fetch_remote_export

    export_path = tmp_path / "staging"
    experiment_class = Mock(label="demo")
    config = Mock()
    config.get.side_effect = lambda key, default=None: {
        "dashboard_user": "admin",
        "dashboard_password": "secret",
    }.get(key, default)

    def fake_extract(archive_path, staging_dir):
        Path(staging_dir).mkdir(parents=True, exist_ok=True)
        (Path(staging_dir) / "database").mkdir(exist_ok=True)
        (Path(staging_dir) / "manifest.json").write_text("{}")
        return manifest

    monkeypatch.setattr(
        "psynet.command_line.get_experiment_url", lambda app, server: "https://ex.test"
    )
    monkeypatch.setattr(
        "psynet.export.client.fetch_preflight", lambda endpoint: preflight
    )
    monkeypatch.setattr(
        "psynet.export.client.download_archive", lambda *args, **kwargs: "export.zip"
    )
    monkeypatch.setattr("psynet.export.client.extract_archive", fake_extract)

    return _fetch_remote_export, experiment_class, config, str(export_path)


def test_downloaded_manifest_is_checked_even_after_preflight(tmp_path, monkeypatch):
    _fetch_remote_export, experiment_class, config, export_path = _remote_export_env(
        tmp_path,
        monkeypatch,
        preflight={
            "experiment_label": "demo",
            "deployment_id": "one",
            "export_format_version": 1,
        },
        manifest={
            "experiment_label": "demo",
            "deployment_id": "two",
            "export_format_version": 1,
        },
        docker_ssh=False,
    )

    with pytest.raises(TransferError, match="does not match the deployment"):
        _fetch_remote_export(
            experiment_class,
            export_path,
            app="app",
            server=None,
            docker_ssh=False,
            config=config,
            assets="none",
            transfer="archive",
            allow_project_mismatch=True,
        )


def test_matching_downloaded_manifest_does_not_reprompt_identity(tmp_path, monkeypatch):
    identity = {
        "experiment_label": "demo",
        "deployment_id": "one",
        "export_format_version": 1,
    }
    _fetch_remote_export, experiment_class, config, export_path = _remote_export_env(
        tmp_path,
        monkeypatch,
        preflight=identity,
        manifest=identity,
        docker_ssh=False,
    )
    prompts = []

    def tracking_confirm(*args, **kwargs):
        prompts.append(args[1] if len(args) > 1 else kwargs.get("remote"))

    monkeypatch.setattr(
        "psynet.export.identity.confirm_project_identity", tracking_confirm
    )
    monkeypatch.setattr("psynet.export.client.fetch_logs", lambda *a, **k: None)

    _fetch_remote_export(
        experiment_class,
        export_path,
        app="app",
        server=None,
        docker_ssh=False,
        config=config,
        assets="none",
        transfer="archive",
        allow_project_mismatch=False,
    )

    assert len(prompts) == 1


def test_incremental_oserror_falls_back_to_the_complete_archive(
    tmp_path, monkeypatch, stub_ssh_connection
):
    downloads = []

    def fake_download(endpoint, destination_file, **kwargs):
        downloads.append(kwargs.get("asset_bytes"))
        Path(destination_file).write_bytes(b"zip")
        return destination_file

    def fake_extract(archive_path, staging_dir):
        Path(staging_dir).mkdir(parents=True, exist_ok=True)
        (Path(staging_dir) / "database").mkdir(exist_ok=True)
        return {
            "experiment_label": "demo",
            "deployment_id": "one",
            "export_format_version": 1,
        }

    monkeypatch.setattr(
        "psynet.command_line.get_experiment_url", lambda app, server: "https://ex.test"
    )
    monkeypatch.setattr(
        "psynet.export.client.fetch_preflight",
        lambda endpoint: {
            "experiment_label": "demo",
            "deployment_id": "one",
            "export_format_version": 1,
            "incremental_asset_modes": ("none", "collected"),
        },
    )
    monkeypatch.setattr("psynet.export.client.download_archive", fake_download)
    monkeypatch.setattr("psynet.export.client.extract_archive", fake_extract)
    monkeypatch.setattr(
        "psynet.export.client.ssh_rsync_available", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "psynet.export.client.ssh_rsync_source",
        lambda *a, **k: ("src/", []),
    )
    monkeypatch.setattr(
        "psynet.export.client.hydrate_assets",
        lambda *a, **k: (_ for _ in ()).throw(OSError("ssh dropped")),
    )
    monkeypatch.setattr("psynet.export.client.fetch_logs", lambda *a, **k: None)

    from psynet.command_line import _fetch_remote_export

    _fetch_remote_export(
        Mock(label="demo"),
        str(tmp_path / "staging"),
        app="app",
        server="test-server",
        docker_ssh=True,
        config=Mock(
            get=lambda key, default=None: {
                "dashboard_user": "admin",
                "dashboard_password": "secret",
            }.get(key, default)
        ),
        assets="collected",
        transfer="auto",
        allow_project_mismatch=True,
    )

    assert downloads == ["manifest", "include"]


def test_export_local_does_not_construct_an_ssh_session(tmp_path, monkeypatch):
    from psynet.command_line import export_

    deployment_id = "timeline-demo__mode=debug__launch=test"
    launch_info_dir = tmp_path / "psynet-data" / "launch-data" / deployment_id
    launch_info_dir.mkdir(parents=True)
    (launch_info_dir / "launch-info.json").write_text(
        '{"dashboard_user": "admin", "dashboard_password": "generated-password"}'
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    config = Mock()
    config.ready = True
    config.values = {}
    config.extend.side_effect = config.values.update
    config.get.side_effect = lambda key, default=None: config.values.get(key, default)
    experiment_class = Mock(label="Timeline demo")
    destination = tmp_path / "exports" / "latest"

    def fake_build(export_path, **kwargs):
        Path(export_path).mkdir(parents=True, exist_ok=True)
        (Path(export_path) / "manifest.json").write_text("{}")
        return export_path

    with (
        patch(
            "psynet.experiment.import_local_experiment",
            return_value={"class": experiment_class},
        ),
        patch("psynet.command_line.get_config", return_value=config),
        patch("psynet.command_line.redis_vars.get", return_value=None),
        patch("psynet.export.service.build_export_tree", side_effect=fake_build),
        patch("psynet.export.client.SshSession") as ssh_session,
    ):
        export_(
            ctx=Mock(),
            get_exp_variables=lambda: {
                "deployment_id": deployment_id,
                "label": "Timeline demo",
            },
            local=True,
            path=str(destination),
            assets="collected",
        )

    ssh_session.assert_not_called()

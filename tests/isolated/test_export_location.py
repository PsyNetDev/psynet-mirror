"""Tests for export transport, publication, and export directory rotation."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import click
import pytest
from flask import Flask

from psynet.command_line import export_
from psynet.experiment import Experiment


def test_export_path_uses_experiment_exports_latest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    path = Path(Experiment.export_path())

    assert path == tmp_path / "exports" / "latest"
    assert not path.exists()


def test_rotate_export_history_moves_previous_latest_to_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "exports" / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text("{}\n")

    archived = Path(Experiment.rotate_export_history(Experiment.export_path()))

    assert not latest.exists()
    history = list((tmp_path / "exports" / "history").iterdir())
    assert history == [archived]
    assert (archived / "manifest.json").read_text() == "{}\n"


def test_rotate_export_history_is_a_no_op_without_a_previous_export(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    assert Experiment.rotate_export_history(Experiment.export_path()) is None
    assert not (tmp_path / "exports").exists()


def _export_zip(experiment_label="timeline-demo", export_format_version=1):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "experiment_label": experiment_label,
                    "export_format_version": export_format_version,
                }
            ),
        )
        archive.writestr("database/participant.csv", "id\n1\n")
    return buffer.getvalue()


class _StreamedResponse:
    """Minimal stand-in for a streamed ``requests`` response."""

    def __init__(self, status_code=200, reason="OK", content=b"", payload=None):
        self.status_code = status_code
        self.reason = reason
        self._content = content
        self._payload = payload

    def iter_content(self, chunk_size=None):
        yield self._content

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON payload")
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _run_remote_export(
    get_exp_variables,
    download_response,
    *,
    preflight=None,
    assets="none",
):
    """Run a server-built SSH export against stubbed dashboard responses."""
    experiment_class = Mock(
        label="timeline-demo",
        export_path=Experiment.export_path,
        rotate_export_history=Experiment.rotate_export_history,
    )
    config = Mock(ready=True)
    config.get.side_effect = lambda key, default=None: {
        "dashboard_user": "admin",
        "dashboard_password": "secret",
    }.get(key, default)

    if preflight is None:
        preflight = {
            "experiment_label": "timeline-demo",
            "export_format_version": 1,
            "incremental_asset_modes": ["none"],
        }

    with (
        patch(
            "psynet.experiment.import_local_experiment",
            return_value={"class": experiment_class},
        ),
        patch("psynet.command_line.get_config", return_value=config),
        patch(
            "psynet.command_line.get_experiment_url",
            return_value="https://example.test",
        ),
        patch("psynet.export.client.fetch_preflight", return_value=preflight),
        patch("psynet.export.client.fetch_logs", return_value=None),
        patch("requests.get", return_value=download_response),
    ):
        export_(
            ctx=Mock(),
            get_exp_variables=get_exp_variables,
            app="psynet-02",
            server="example.test",
            docker_ssh=True,
            assets=assets,
        )


def test_remote_export_does_not_read_the_experiment_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def refuse():
        raise AssertionError(
            "the server-built export should not need experiment variables"
        )

    _run_remote_export(refuse, _StreamedResponse(content=_export_zip()))

    latest = tmp_path / "exports" / "latest"
    assert json.loads((latest / "manifest.json").read_text())["experiment_label"] == (
        "timeline-demo"
    )
    assert (latest / "database" / "participant.csv").exists()


def test_remote_export_streams_without_buffering_the_whole_archive(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    class _ExplodingContent(_StreamedResponse):
        @property
        def content(self):
            raise AssertionError("the export download must not read response.content")

    _run_remote_export(Mock(), _ExplodingContent(content=_export_zip()))

    assert (tmp_path / "exports" / "latest" / "manifest.json").exists()


def test_failed_remote_export_keeps_the_previous_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "exports" / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text('{"kept": true}')

    with pytest.raises(click.Abort):
        _run_remote_export(
            Mock(),
            _StreamedResponse(
                status_code=502,
                reason="Bad Gateway",
                payload={"message": "dashboard unavailable"},
            ),
        )

    assert json.loads((latest / "manifest.json").read_text()) == {"kept": True}
    assert not (tmp_path / "exports" / "history").exists()
    assert list((tmp_path / "exports").iterdir()) == [latest]


def test_corrupt_download_keeps_the_previous_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "exports" / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text('{"kept": true}')

    with pytest.raises(click.Abort):
        _run_remote_export(Mock(), _StreamedResponse(content=b"not a zip file"))

    assert json.loads((latest / "manifest.json").read_text()) == {"kept": True}
    assert not (tmp_path / "exports" / "history").exists()


def test_remote_export_refuses_a_deployment_without_preflight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "exports" / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text('{"kept": true}')

    experiment_class = Mock(
        label="timeline-demo",
        export_path=Experiment.export_path,
        rotate_export_history=Experiment.rotate_export_history,
    )
    config = Mock(ready=True)
    config.get.side_effect = lambda key, default=None: {
        "dashboard_user": "admin",
        "dashboard_password": "secret",
    }.get(key, default)
    urls = []

    def record_get(url, **kwargs):
        urls.append(url)
        return _StreamedResponse(status_code=404, reason="Not Found")

    with (
        patch(
            "psynet.experiment.import_local_experiment",
            return_value={"class": experiment_class},
        ),
        patch("psynet.command_line.get_config", return_value=config),
        patch(
            "psynet.command_line.get_experiment_url",
            return_value="https://example.test",
        ),
        patch("psynet.export.client.fetch_logs", return_value=None),
        patch("requests.get", side_effect=record_get),
    ):
        with pytest.raises(click.Abort):
            export_(
                ctx=Mock(),
                get_exp_variables=Mock(),
                app="psynet-02",
                server="example.test",
                docker_ssh=True,
                assets="none",
            )

    assert any("/dashboard/export/preflight" in url for url in urls)
    assert not any("/dashboard/export/download" in url for url in urls)
    assert json.loads((latest / "manifest.json").read_text()) == {"kept": True}


def test_remote_export_from_the_wrong_experiment_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "exports" / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text('{"kept": true}')

    with pytest.raises(click.Abort):
        _run_remote_export(
            Mock(),
            _StreamedResponse(content=_export_zip()),
            preflight={
                "experiment_label": "some-other-demo",
                "export_format_version": 1,
            },
        )

    assert json.loads((latest / "manifest.json").read_text()) == {"kept": True}
    assert not (tmp_path / "exports" / "history").exists()


def test_remote_export_refuses_an_unreadable_export_format(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(click.Abort):
        _run_remote_export(
            Mock(),
            _StreamedResponse(content=_export_zip()),
            preflight={
                "experiment_label": "timeline-demo",
                "export_format_version": 99,
            },
        )

    assert not (tmp_path / "exports").exists()


def test_successful_remote_export_rotates_the_previous_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    latest = tmp_path / "exports" / "latest"
    latest.mkdir(parents=True)
    (latest / "manifest.json").write_text('{"previous": true}')

    _run_remote_export(Mock(), _StreamedResponse(content=_export_zip()))

    (archived,) = list((tmp_path / "exports" / "history").iterdir())
    assert json.loads((archived / "manifest.json").read_text()) == {"previous": True}
    assert (latest / "database" / "participant.csv").exists()


def test_export_falls_back_to_an_archive_when_asset_transfer_fails(
    tmp_path, monkeypatch
):
    """A failed rsync must not lose the export: the server can still send it all."""
    from psynet.export.client import TransferError

    monkeypatch.chdir(tmp_path)
    experiment_class = Mock(
        label="timeline-demo",
        export_path=Experiment.export_path,
        rotate_export_history=Experiment.rotate_export_history,
    )
    config = Mock(ready=True)
    config.get.side_effect = lambda key, default=None: {
        "dashboard_user": "admin",
        "dashboard_password": "secret",
    }.get(key, default)
    downloads = []

    def record_download(url, **kwargs):
        downloads.append(parse_qs(urlparse(url).query).get("asset_bytes", [None])[0])
        return _StreamedResponse(content=_export_zip())

    with (
        patch(
            "psynet.experiment.import_local_experiment",
            return_value={"class": experiment_class},
        ),
        patch("psynet.command_line.get_config", return_value=config),
        patch(
            "psynet.command_line.get_experiment_url",
            return_value="https://example.test",
        ),
        patch(
            "psynet.export.client.fetch_preflight",
            return_value={
                "experiment_label": "timeline-demo",
                "export_format_version": 1,
                "incremental_asset_modes": ["none", "collected"],
            },
        ),
        patch("psynet.export.client.fetch_logs", return_value=None),
        patch("psynet.export.client.ssh_rsync_available", return_value=True),
        patch(
            "psynet.export.client.ssh_rsync_source", return_value=("remote:/src/", [])
        ),
        patch("psynet.export.client.plan_asset_transfer", return_value=Mock()),
        patch(
            "psynet.export.client.hydrate_assets",
            side_effect=TransferError("rsync exited with status 23"),
        ),
        patch("requests.get", side_effect=record_download),
    ):
        export_(
            ctx=Mock(),
            get_exp_variables=Mock(),
            app="psynet-02",
            server="example.test",
            docker_ssh=True,
            assets="collected",
        )

    assert downloads == ["manifest", "include"]
    assert (tmp_path / "exports" / "latest" / "database" / "participant.csv").exists()


def test_dashboard_export_writes_zip_beside_tree_not_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "scratch"
    export_dir = root / "export"
    export_dir.mkdir(parents=True)

    def fake_build_tree(path, **kwargs):
        (Path(path) / "manifest.json").write_text("{}\n")
        return path

    monkeypatch.setattr("psynet.export.service.build_export_tree", fake_build_tree)

    storage = Mock()
    experiment = Mock()
    experiment.deployment_id = "dep-1"
    experiment.artifact_storage = storage
    experiment.notifier.notify = Mock()
    experiment.notifier.url = Mock(return_value="here")
    experiment.get_artifact_url = Mock(return_value="https://example.test/export.zip")
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)

    zip_path = Path(Experiment._export(str(export_dir)))

    assert zip_path == root / "export.zip"
    assert zip_path.is_file()
    assert not (tmp_path / "export.zip").exists()
    storage.upload_export.assert_called_once()
    assert Path(storage.upload_export.call_args.args[0]) == zip_path


def test_download_export_sends_zip_bytes_after_tempdir_would_have_closed(
    tmp_path, monkeypatch
):
    payload = b"PK\x03\x04export-bytes"

    def fake_build(export_dir, **kwargs):
        zip_path = Path(export_dir).parent / "export.zip"
        zip_path.write_bytes(payload)
        return str(zip_path)

    experiment = Mock()
    experiment.build_export_archive.side_effect = fake_build
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(
        "psynet.export.service.store_latest_archive", lambda zip_path: None
    )

    app = Flask(__name__)

    @app.route("/download")
    def download():
        return Experiment._download_export(assets="none")

    with app.test_client() as client:
        response = client.get("/download")
        assert response.status_code == 200
        assert response.data == payload
        response.close()


def test_manifest_only_download_does_not_replace_the_stored_artifact(
    tmp_path, monkeypatch
):
    """A core snapshot is incomplete, so it must not become the latest artifact."""
    stored = []

    def fake_build(export_dir, **kwargs):
        zip_path = Path(export_dir).parent / "export.zip"
        zip_path.write_bytes(b"PK\x03\x04core")
        return str(zip_path)

    experiment = Mock()
    experiment.build_export_archive.side_effect = fake_build
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(
        "psynet.export.service.store_latest_archive", lambda zip_path: stored.append(1)
    )

    app = Flask(__name__)

    @app.route("/download")
    def download():
        return Experiment._download_export(assets="collected", asset_bytes="manifest")

    with app.test_client() as client:
        client.get("/download").close()

    assert stored == []

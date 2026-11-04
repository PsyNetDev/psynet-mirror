"""Tests for asset subpath safety and LocalStorage serving."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.http import parse_options_header

from psynet.asset import (
    Asset,
    LocalStorage,
    ManagedAsset,
    OnDemandAsset,
    S3Storage,
    _safe_asset_subpath,
)
from psynet.experiment import _redacted_asset_request_path


def test_safe_asset_subpath_none_and_empty():
    assert _safe_asset_subpath(None) is None
    assert _safe_asset_subpath("") is None
    assert _safe_asset_subpath(".") is None


def test_safe_asset_subpath_normalizes_relative_path():
    assert _safe_asset_subpath("a/b.txt") == "a/b.txt"
    assert _safe_asset_subpath("/a/b.txt") == "a/b.txt"
    assert _safe_asset_subpath("a/./b.txt") == "a/b.txt"


@pytest.mark.parametrize(
    "subpath",
    [
        "..",
        "../secret.txt",
        "a/../../secret.txt",
        "a/../b/../../x",
    ],
)
def test_safe_asset_subpath_rejects_traversal(subpath):
    with pytest.raises(ValueError, match="Unsafe asset subpath"):
        _safe_asset_subpath(subpath)


def test_asset_serve_rejects_unsafe_subpath_with_http_400():
    asset = Asset.__new__(Asset)
    app = Flask("test-asset-serve-unsafe")
    with app.test_request_context("/"):
        with pytest.raises(Exception) as exc:
            asset.serve("../secret.txt")
        assert getattr(exc.value, "code", None) == 400


def test_redacted_asset_request_path():
    assert _redacted_asset_request_path("/asset/tok_abc123") == "/asset/<access_token>"
    assert (
        _redacted_asset_request_path("/asset/tok_abc123/sub/file.wav")
        == "/asset/<access_token>/sub/file.wav"
    )
    assert _redacted_asset_request_path("/timeline") == "/timeline"


@pytest.mark.parametrize("asset_extension", [".png", "png"])
def test_local_storage_serve_file(tmp_path, asset_extension):
    root = tmp_path / "storage"
    object_rel = "objects/sha256/abc123"
    stored = root / object_rel
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"payload")

    class _Asset:
        object_path = object_rel
        host_path = object_rel
        is_folder = False
        extension = asset_extension

    storage = LocalStorage(root=str(root))
    app = Flask("test-local-storage-serve")
    with app.test_request_context("/"):
        response = storage.serve(_Asset())
        try:
            assert response.status_code == 200
            # The stored object has no extension; the asset's own one decides.
            assert response.mimetype == "image/png"
            _, options = parse_options_header(response.headers["Content-Disposition"])
            assert options["filename"].endswith(".png")
            assert response.cache_control.private
            assert not response.cache_control.public
            assert response.cache_control.max_age == 31_536_000
            assert response.cache_control.immutable
            response.direct_passthrough = False
            assert response.get_data() == b"payload"
        finally:
            # A real WSGI server closes the response; without this the file
            # handle opened by send_file leaks into pytest's teardown.
            response.close()


@pytest.mark.parametrize(
    "extension, disposition, policy",
    [
        (".html", "attachment", "sandbox"),
        (".svg", "attachment", "sandbox"),
        (".xsl", "attachment", "sandbox"),
        (".png", "inline", "sandbox"),
        (".pdf", "inline", None),
        (".wav", "inline", None),
        (".gz", "inline", "sandbox"),
    ],
)
def test_asset_serve_sandboxes_active_types(tmp_path, extension, disposition, policy):
    """An uploaded HTML or SVG asset must not run as a page on the experiment's origin."""
    root = tmp_path / "storage"
    (root / "objects").mkdir(parents=True)
    (root / "objects/abc123").write_bytes(b"<svg onload=alert(1)>")
    storage = LocalStorage(root=str(root))
    asset = SimpleNamespace(
        deposited=True,
        storage=storage,
        object_path="objects/abc123",
        host_path="objects/abc123",
        is_folder=False,
        extension=extension,
    )

    with Flask("test-asset-serve-sandbox").test_request_context("/"):
        response = Asset.serve(asset)
        try:
            assert response.headers.get("Content-Security-Policy") == policy
            assert "Content-Encoding" not in response.headers
            value, options = parse_options_header(
                response.headers["Content-Disposition"]
            )
            assert value == disposition
            assert options["filename"] == "abc123" + extension
        finally:
            response.close()


def _write_html_page(path):
    Path(path).write_text("<script>alert(1)</script>")


def test_on_demand_asset_serve_is_sandboxed(tmp_path, monkeypatch):
    # Flask's test request context never runs the temp-file cleanup.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    asset = OnDemandAsset(function=_write_html_page, extension=".html")

    with Flask("test-on-demand-asset-sandbox").test_request_context("/"):
        response = asset.serve()
        try:
            assert response.headers["Content-Security-Policy"] == "sandbox"
            assert response.headers["Content-Disposition"].startswith("attachment")
        finally:
            response.close()


def test_local_storage_serve_rejects_subpath_on_file(tmp_path):
    root = tmp_path / "storage"
    object_rel = "objects/sha256/abc123"
    stored = root / object_rel
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"payload")

    class _Asset:
        object_path = object_rel
        host_path = object_rel
        is_folder = False
        extension = None

    storage = LocalStorage(root=str(root))
    app = Flask("test-local-storage-serve-subpath")
    with app.test_request_context("/"):
        with pytest.raises(Exception) as exc:
            storage.serve(_Asset(), "child.txt")
        # Flask abort(400) raises werkzeug.exceptions.BadRequest
        assert getattr(exc.value, "code", None) == 400


def test_s3_storage_serve_redirects_to_public_url():

    storage = S3Storage("my-bucket", "prefix")
    asset = MagicMock()
    asset.object_path = "objects/sha256/deadbeef"
    asset.host_path = asset.object_path
    asset.is_folder = False

    app = Flask("test-s3-serve-redirect")
    with app.test_request_context("/"):
        response = storage.serve(asset)
        assert response.status_code in (301, 302)
        assert response.location.startswith(
            "https://s3.amazonaws.com/my-bucket/prefix/objects/sha256/deadbeef"
        )


def test_managed_asset_s3_get_url_is_direct_public_object():

    storage = S3Storage("my-bucket", "prefix")

    class Stub:
        def __init__(self):
            self.storage = storage
            self.default_storage = storage
            self.object_path = "objects/sha256/abcd"
            self.host_path = self.object_path
            self.access_token = "tok_should_not_appear"

        def access_url(self, subpath=None):
            return f"/asset/{self.access_token}"

    url = ManagedAsset.get_url(Stub())
    assert url.startswith("https://s3.amazonaws.com/my-bucket/")
    assert "objects/sha256/abcd" in url
    assert "tok_should_not_appear" not in url
    assert not url.startswith("/asset/")


def test_managed_asset_rotates_access_token_when_contents_change():
    asset = SimpleNamespace(
        sha256_contents="old-digest",
        access_token="old-token",
        get_sha256_contents=lambda: "new-digest",
        get_md5_contents=lambda: "new-md5",
        rotate_access_token=MagicMock(),
    )

    ManagedAsset._assign_content_addressed_paths(asset)

    asset.rotate_access_token.assert_called_once_with()
    assert asset.object_path == "objects/sha256/new-digest"


def test_managed_asset_recomputes_digests_when_same_path_changes(tmp_path):
    source = tmp_path / "stimulus.txt"
    source.write_text("first", encoding="utf-8")
    asset = object.__new__(ManagedAsset)

    first_sha256 = asset._get_sha256_contents(str(source), False)
    first_md5 = asset._get_md5_contents(str(source), False)
    source.write_text("second", encoding="utf-8")

    assert asset._get_sha256_contents(str(source), False) != first_sha256
    assert asset._get_md5_contents(str(source), False) != first_md5

    folder = tmp_path / "stimuli"
    folder.mkdir()
    nested = folder / "item.txt"
    nested.write_text("first", encoding="utf-8")
    first_folder_sha256 = asset._get_sha256_contents(str(folder), True)
    nested.write_text("second", encoding="utf-8")
    assert asset._get_sha256_contents(str(folder), True) != first_folder_sha256


def test_local_storage_launch_removes_a_legacy_static_assets_link(
    tmp_path, monkeypatch
):
    """Flask would serve every stored object through this link unchecked."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "static").mkdir()
    (tmp_path / "static/assets").symlink_to(tmp_path, target_is_directory=True)
    storage = LocalStorage(root=str(tmp_path / "storage"))
    monkeypatch.setattr(storage, "on_deployed_server", lambda: True)

    storage.on_every_launch()

    assert not (tmp_path / "static/assets").is_symlink()
    assert (tmp_path / "storage").is_dir()

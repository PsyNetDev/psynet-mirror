"""Tests for asset subpath safety and LocalStorage serving."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from psynet.asset import (
    Asset,
    LocalStorage,
    ManagedAsset,
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


def test_local_storage_serve_file(tmp_path):
    root = tmp_path / "storage"
    object_rel = "objects/sha256/abc123"
    stored = root / object_rel
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"payload")

    class _Asset:
        object_path = object_rel
        host_path = object_rel
        is_folder = False

    storage = LocalStorage(root=str(root))
    app = Flask("test-local-storage-serve")
    with app.test_request_context("/"):
        response = storage.serve(_Asset())
        try:
            assert response.status_code == 200
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

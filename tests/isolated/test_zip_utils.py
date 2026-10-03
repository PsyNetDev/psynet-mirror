"""Unit tests for :mod:`psynet.export.zip_utils`.

These tests exercise the compression-choice logic and the archive builder
without requiring a database or running experiment.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from psynet.export.zip_utils import (
    _STORED_EXTENSIONS,
    _compression_for,
    build_zip_from_dir,
)

# ---------------------------------------------------------------------------
# _compression_for – compression selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arcname",
    [
        "audio.mp3",
        "clip.mp4",
        "sound.wav",
        "archive.zip",
        "compressed.gz",
        "image.png",
        "photo.jpg",
        "photo.jpeg",
        "modern.webp",
        "video.webm",
        "lossless.flac",
        "vorbis.ogg",
        # Case insensitivity
        "UPPER.MP3",
        "Mixed.Zip",
        # Nested path
        "assets/objects/sha256/abcdef.mp4",
        "exports/database.zip",
    ],
)
def test_compression_for_stored_extensions(arcname):
    """Already-compressed formats should be stored without DEFLATE."""
    assert _compression_for(arcname) == zipfile.ZIP_STORED


@pytest.mark.parametrize(
    "arcname",
    [
        "assets/objects/sha256/abcdef0123456789",
        "objects/sha256/deadbeef",
        "export/assets/objects/sha256/cafebabe",
    ],
)
def test_compression_for_content_addressed_objects_without_extension(arcname):
    """Bare SHA-256 object paths have no extension; store them uncompressed."""
    assert _compression_for(arcname) == zipfile.ZIP_STORED


@pytest.mark.parametrize(
    "arcname",
    [
        "data.csv",
        "manifest.json",
        "participant_identifiers.csv",
        "notes.txt",
        "README.md",
        "basic_data.json",
        "table.html",
        "script.py",
        # No extension
        "no_extension",
        # Nested path
        "assets/manifest.csv",
    ],
)
def test_compression_for_deflate_extensions(arcname):
    """Text / compressible formats should use DEFLATE."""
    assert _compression_for(arcname) == zipfile.ZIP_DEFLATED


def test_stored_extensions_are_lowercase():
    """All entries in _STORED_EXTENSIONS must have a leading dot and be lower-case."""
    for ext in _STORED_EXTENSIONS:
        assert ext.startswith("."), f"{ext!r} should start with '.'"
        assert ext == ext.lower(), f"{ext!r} should be lower-case"


# ---------------------------------------------------------------------------
# build_zip_from_dir – archive construction
# ---------------------------------------------------------------------------


def _make_source_tree(root: Path) -> None:
    """Populate a small source tree that mimics a PsyNet export directory."""
    (root / "participant_identifiers.csv").write_text("id,worker_id\n1,w1\n")
    (root / "manifest.json").write_text('{"psynet_version": "0.0.0"}\n')
    # Simulate a nested database zip (already compressed)
    inner_zip = root / "database.zip"
    with zipfile.ZipFile(str(inner_zip), "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("data/participant.csv", "id,worker_id\n1,w1\n")
    # Simulate a media asset under the content-addressed objects layout
    assets_dir = root / "assets" / "objects" / "sha256"
    assets_dir.mkdir(parents=True)
    (assets_dir / "abcdef1234567890abcdef").write_bytes(b"\xff\xfb\x90\x00" * 64)
    (assets_dir / "abcdef1234567890abcdef").rename(
        assets_dir / "abcdef1234567890abcdef"
    )
    # Rename to an mp3-like name via a manifest-style name (digest only, no ext)
    fake_mp3 = root / "assets" / "objects" / "sha256" / "cafebabe.mp3"
    fake_mp3.write_bytes(b"\xff\xfb\x90\x00" * 64)
    # Assets manifest CSV
    (root / "assets" / "manifest.csv").write_text("id,sha256\n1,cafebabe\n")


def test_build_zip_from_dir_creates_archive(tmp_path):
    """build_zip_from_dir should create a readable ZIP at zip_path."""
    src = tmp_path / "export"
    src.mkdir()
    _make_source_tree(src)

    zip_path = tmp_path / "output.zip"
    result = build_zip_from_dir(str(src), str(zip_path))

    assert result == str(zip_path)
    assert zip_path.exists()
    with zipfile.ZipFile(str(zip_path)) as zf:
        assert zf.testzip() is None  # no corrupt members


def test_build_zip_from_dir_member_paths(tmp_path):
    """Archive member names should be relative to source_dir (no leading slash)."""
    src = tmp_path / "export"
    src.mkdir()
    _make_source_tree(src)

    zip_path = tmp_path / "output.zip"
    build_zip_from_dir(str(src), str(zip_path))

    with zipfile.ZipFile(str(zip_path)) as zf:
        names = zf.namelist()

    # Paths must be relative (no drive or leading slash)
    for name in names:
        assert not name.startswith("/"), f"Absolute arcname: {name!r}"
    assert "manifest.json" in names
    assert "participant_identifiers.csv" in names
    assert "database.zip" in names


def test_build_zip_stored_for_nested_zip(tmp_path):
    """Nested .zip members must use ZIP_STORED."""
    src = tmp_path / "export"
    src.mkdir()
    _make_source_tree(src)

    zip_path = tmp_path / "output.zip"
    build_zip_from_dir(str(src), str(zip_path))

    with zipfile.ZipFile(str(zip_path)) as zf:
        info = zf.getinfo("database.zip")
    assert info.compress_type == zipfile.ZIP_STORED


def test_build_zip_stored_for_media_asset(tmp_path):
    """Media asset files (e.g. .mp3) must use ZIP_STORED."""
    src = tmp_path / "export"
    src.mkdir()
    _make_source_tree(src)

    zip_path = tmp_path / "output.zip"
    build_zip_from_dir(str(src), str(zip_path))

    with zipfile.ZipFile(str(zip_path)) as zf:
        info = zf.getinfo("assets/objects/sha256/cafebabe.mp3")
    assert info.compress_type == zipfile.ZIP_STORED


def test_build_zip_deflated_for_text_files(tmp_path):
    """CSV and JSON members must use ZIP_DEFLATED."""
    src = tmp_path / "export"
    src.mkdir()
    _make_source_tree(src)

    zip_path = tmp_path / "output.zip"
    build_zip_from_dir(str(src), str(zip_path))

    with zipfile.ZipFile(str(zip_path)) as zf:
        csv_info = zf.getinfo("participant_identifiers.csv")
        json_info = zf.getinfo("manifest.json")
    assert csv_info.compress_type == zipfile.ZIP_DEFLATED
    assert json_info.compress_type == zipfile.ZIP_DEFLATED


def test_build_zip_returns_absolute_path(tmp_path):
    """build_zip_from_dir must return an absolute path."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello")
    zip_path = tmp_path / "out.zip"
    result = build_zip_from_dir(str(src), str(zip_path))
    assert Path(result).is_absolute()


def test_build_zip_empty_dir(tmp_path):
    """An empty source_dir should produce a valid empty ZIP."""
    src = tmp_path / "empty"
    src.mkdir()
    zip_path = tmp_path / "empty.zip"
    build_zip_from_dir(str(src), str(zip_path))
    with zipfile.ZipFile(str(zip_path)) as zf:
        assert zf.namelist() == []

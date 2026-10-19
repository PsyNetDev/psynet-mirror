"""Tests for export archive path safety and contained extraction."""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from psynet.export.path_safety import (
    AmbiguousArchiveLayoutError,
    UnsafePathError,
    assert_semantic_asset_path,
    classify_table_csv_member,
    extract_zip_contained,
    find_table_member,
    table_csv_members,
)

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from export_test_helpers import write_zip_with_duplicate_member  # noqa: E402


def _archive(tmp_path: Path, members: dict[str, str]) -> zipfile.ZipFile:
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as handle:
        for name, payload in members.items():
            handle.writestr(name, payload)
    return zipfile.ZipFile(path, "r")


def test_nested_database_lookalike_is_not_a_table_csv():
    assert classify_table_csv_member("assets/database/private.csv") is None
    assert classify_table_csv_member("database/trial.csv") == ("database", "trial")
    assert classify_table_csv_member("data/trial.csv") == ("data", "trial")


def test_table_csv_members_ignore_nested_lookalikes(tmp_path):
    with _archive(
        tmp_path,
        {
            "database/trial.csv": "id\n1\n",
            "assets/database/private.csv": "secret\n",
            "participant_identifiers.csv": "id\n",
        },
    ) as archive:
        assert table_csv_members(archive) == ["database/trial.csv"]
        assert find_table_member(archive, "private") is None
        assert find_table_member(archive, "trial") == "database/trial.csv"


def test_mixed_canonical_and_legacy_layouts_are_rejected(tmp_path):
    with _archive(
        tmp_path,
        {
            "database/trial.csv": "id\nnew\n",
            "data/participant.csv": "id\nlegacy\n",
        },
    ) as archive:
        with pytest.raises(AmbiguousArchiveLayoutError, match="mixes"):
            table_csv_members(archive)


def test_duplicate_table_members_are_rejected(tmp_path):
    path = write_zip_with_duplicate_member(
        tmp_path / "dup.zip",
        [
            ("database/trial.csv", "id\n1\n"),
            ("database/trial.csv", "id\n2\n"),
        ],
    )
    with zipfile.ZipFile(path, "r") as archive:
        with pytest.raises(AmbiguousArchiveLayoutError, match="more than once"):
            table_csv_members(archive)


def test_traversal_members_are_rejected(tmp_path):
    with _archive(tmp_path, {"database/../../secret.csv": "x\n"}) as archive:
        with pytest.raises(UnsafePathError):
            table_csv_members(archive)


def test_extract_zip_contained_keeps_files_inside_the_destination(tmp_path):
    dest = tmp_path / "out"
    with _archive(
        tmp_path,
        {"database/trial.csv": "id\n1\n", "manifest.json": "{}\n"},
    ) as archive:
        extract_zip_contained(archive, str(dest))
    assert (dest / "database" / "trial.csv").read_text() == "id\n1\n"
    assert (dest / "manifest.json").read_text() == "{}\n"


def test_extract_zip_contained_streams_member_bytes(tmp_path):
    dest = tmp_path / "out"
    with _archive(tmp_path, {"assets/large.bin": "payload"}) as archive:
        with patch(
            "psynet.export.path_safety.shutil.copyfileobj",
            wraps=shutil.copyfileobj,
        ) as copyfileobj:
            extract_zip_contained(archive, str(dest))

    copyfileobj.assert_called_once()
    assert (dest / "assets" / "large.bin").read_text() == "payload"


def test_extract_zip_contained_rejects_zip_slip(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    with _archive(tmp_path, {"../outside.txt": "nope\n"}) as archive:
        with pytest.raises(UnsafePathError):
            extract_zip_contained(archive, str(dest))
    assert not (tmp_path / "outside.txt").exists()


def test_extract_zip_contained_rejects_normalized_aliases_before_writing(tmp_path):
    dest = tmp_path / "out"
    with _archive(
        tmp_path,
        {
            "manifest.json": '{"experiment_label": "expected"}',
            "./manifest.json": '{"experiment_label": "overwritten"}',
        },
    ) as archive:
        with pytest.raises(AmbiguousArchiveLayoutError, match="same path"):
            extract_zip_contained(archive, str(dest))
    assert not (dest / "manifest.json").exists()


def test_semantic_asset_paths_must_stay_relative():
    assert assert_semantic_asset_path("module/a.wav") == "module/a.wav"
    with pytest.raises(UnsafePathError):
        assert_semantic_asset_path("../secret.wav")
    with pytest.raises(UnsafePathError):
        assert_semantic_asset_path("/tmp/a.wav")

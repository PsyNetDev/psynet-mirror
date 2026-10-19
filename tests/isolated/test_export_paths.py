"""Tests for export archive path resolution."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from psynet.export.paths import (
    dashboard_export_zip_path,
    find_table_member_in_zip,
    resolve_database_dir,
)


def test_resolve_database_dir_variants(tmp_path: Path):
    database = tmp_path / "database"
    database.mkdir()
    (database / "trial.csv").write_text("id\n1\n")
    assert resolve_database_dir(str(database)) == str(database.resolve())

    export_dir = tmp_path / "export"
    nested = export_dir / "database"
    nested.mkdir(parents=True)
    (nested / "participant.csv").write_text("id\n1\n")
    assert resolve_database_dir(str(export_dir)) == str(nested.resolve())


def test_resolve_database_dir_rejects_zip(tmp_path: Path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("database/trial.csv", "id\n1\n")
    with pytest.raises(ValueError, match="zip archive"):
        resolve_database_dir(str(archive))


def test_resolve_database_dir_rejects_mixed_extracted_layouts(tmp_path: Path):
    database = tmp_path / "database"
    database.mkdir()
    (database / "trial.csv").write_text("id\n1\n")
    legacy = tmp_path / "data"
    legacy.mkdir()
    (legacy / "participant.csv").write_text("id\n1\n")

    with pytest.raises(ValueError, match="mixes database/ and data/"):
        resolve_database_dir(str(tmp_path))


def test_find_table_member_prefers_database_layout(tmp_path: Path):
    archive_path = tmp_path / "canonical.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("database/trial.csv", "id\nnew\n")
        zf.writestr("assets/database/private.csv", "secret\n")
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert find_table_member_in_zip(archive, "trial") == "database/trial.csv"
        assert find_table_member_in_zip(archive, "private") is None


def test_find_table_member_accepts_legacy_data_layout(tmp_path: Path):
    archive_path = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/trial.csv", "id\nlegacy\n")
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert find_table_member_in_zip(archive, "trial") == "data/trial.csv"


def test_find_table_member_rejects_mixed_layouts(tmp_path: Path):
    from psynet.export.path_safety import AmbiguousArchiveLayoutError

    archive_path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("data/trial.csv", "id\nlegacy\n")
        zf.writestr("database/trial.csv", "id\nnew\n")
    with zipfile.ZipFile(archive_path, "r") as archive:
        with pytest.raises(AmbiguousArchiveLayoutError):
            find_table_member_in_zip(archive, "trial")


def test_dashboard_export_zip_path_is_sibling_of_export_tree(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    export_dir = tmp_path / "scratch" / "export"
    export_dir.mkdir(parents=True)
    zip_path = dashboard_export_zip_path(str(export_dir))
    assert zip_path == str((tmp_path / "scratch" / "export.zip").resolve())
    assert zip_path != str((tmp_path / "export.zip").resolve())


def test_dashboard_export_zip_path_rejects_process_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    with pytest.raises(ValueError, match="working directory"):
        dashboard_export_zip_path(str(export_dir))

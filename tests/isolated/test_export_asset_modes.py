"""Tests for the supported export asset selections."""

from pathlib import Path

import pytest

from psynet.export.service import (
    ASSET_MODES,
    REMOVED_ASSETS_ALL,
    build_export_tree,
    validate_asset_mode,
)


def test_asset_modes_are_none_and_collected():
    assert ASSET_MODES == ("none", "collected")


def test_validate_asset_mode_accepts_supported_values():
    assert validate_asset_mode("none") == "none"
    assert validate_asset_mode("collected") == "collected"


def test_validate_asset_mode_rejects_all_with_a_migration_message():
    with pytest.raises(
        ValueError, match="asset selection 'all' has been removed"
    ) as exc:
        validate_asset_mode("all")
    assert str(exc.value) == REMOVED_ASSETS_ALL
    assert "--assets" not in str(exc.value)


def test_validate_asset_mode_rejects_unknown_values():
    with pytest.raises(ValueError, match="must be one of none, collected") as exc:
        validate_asset_mode("experiment")
    assert "--assets" not in str(exc.value)


def test_build_export_tree_rejects_all_before_touching_the_database(
    tmp_path, monkeypatch
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("database export must not run for an invalid asset mode")

    monkeypatch.setattr(
        "psynet.export.database.export_database_snapshot", fail_if_called
    )
    monkeypatch.setattr("psynet.export.service.write_basic_data", fail_if_called)

    with pytest.raises(ValueError, match="asset selection 'all' has been removed"):
        build_export_tree(str(tmp_path / "export"), assets="all")

    assert not Path(tmp_path / "export").exists()


def test_dashboard_export_template_omits_the_all_option():
    template = (
        Path(__file__).resolve().parents[2] / "psynet/templates/dashboard_export.html"
    ).read_text()
    assert 'value="all"' not in template
    assert "input-assets-all" not in template
    assert 'value="collected"' in template
    assert 'value="none"' in template

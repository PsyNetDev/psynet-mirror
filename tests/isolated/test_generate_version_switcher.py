import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "docs" / "scripts" / "generate_version_switcher.py"


spec = importlib.util.spec_from_file_location(
    "generate_version_switcher", GENERATOR_PATH
)
generate_version_switcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate_version_switcher)


def test_alpha_switcher_name_uses_base_version():
    assert generate_version_switcher.format_alpha_name("13.3.0a0") == "13.3.0 alpha"
    assert generate_version_switcher.format_alpha_name("13.4.2a7") == "13.4.2 alpha"


def test_alpha_switcher_name_rejects_non_alpha_version():
    with pytest.raises(ValueError, match="Expected an alpha version"):
        generate_version_switcher.format_alpha_name("13.3.0")


def test_is_alpha_version():
    assert generate_version_switcher.is_alpha_version("13.4.0a0")
    assert not generate_version_switcher.is_alpha_version("13.3.0")
    assert not generate_version_switcher.is_alpha_version("13.3.0rc1")


def test_entries_omit_alpha_during_post_release_window():
    """After the release merge-back, master briefly carries a stable version;
    the switcher must then omit the alpha entry instead of crashing."""
    entries = generate_version_switcher.build_entries(
        "https://psynetdev.gitlab.io/PsyNet",
        tags=["v13.3.0", "v13.2.0"],
        alpha_version=None,
    )

    assert [entry["version"] for entry in entries] == ["v13.3.0", "v13.2.0"]
    assert entries[0]["preferred"] is True


def test_prerelease_switcher_name_matches_alpha_style():
    assert (
        generate_version_switcher.format_prerelease_name("v13.3.0rc0") == "13.3.0 rc0"
    )
    assert generate_version_switcher.format_prerelease_name("v13.4.0a1") == "13.4.0 a1"


def test_prerelease_switcher_name_rejects_stable_tag():
    with pytest.raises(ValueError, match="Expected a prerelease tag"):
        generate_version_switcher.format_prerelease_name("v13.3.0")


def test_rc_switcher_entry_keeps_raw_version_for_matching():
    entries = generate_version_switcher.build_entries(
        "https://psynetdev.gitlab.io/PsyNet",
        tags=["v13.2.0"],
        alpha_version="13.3.0a0",
        latest_rc_tag="v13.3.0rc0",
    )

    assert entries[1] == {
        "name": "13.3.0 rc0",
        "version": "v13.3.0rc0",
        "url": "https://psynetdev.gitlab.io/PsyNet/rc/v13.3.0rc0/",
    }


def test_alpha_switcher_entry_keeps_raw_version_for_matching():
    entries = generate_version_switcher.build_entries(
        "https://psynetdev.gitlab.io/PsyNet",
        tags=["v13.2.0"],
        alpha_version="13.3.0a0",
    )

    assert entries[0] == {
        "name": "13.3.0 alpha",
        "version": "13.3.0a0",
        "url": "https://psynetdev.gitlab.io/PsyNet/alpha/",
    }

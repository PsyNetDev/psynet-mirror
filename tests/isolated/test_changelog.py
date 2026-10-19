import subprocess

import pytest

from psynet.dev import changelog as changelog_module

BASE_CHANGELOG = """# CHANGELOG

## [13.1.1](url) Release - 2026-02-18
"""


@pytest.fixture
def changelog(tmp_path, monkeypatch):
    fragments_dir = tmp_path / "changelog.d"
    fragments_dir.mkdir()
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(BASE_CHANGELOG, encoding="utf-8")

    monkeypatch.setattr(changelog_module, "FRAGMENTS_DIR", fragments_dir)
    monkeypatch.setattr(changelog_module, "CHANGELOG_PATH", changelog_path)
    return changelog_module


def read_changelog(changelog):
    return changelog.CHANGELOG_PATH.read_text(encoding="utf-8")


def test_build_command_previews_fragments_without_consuming_them(changelog, capsys):
    added = changelog.FRAGMENTS_DIR / "20260513-added-alpha.added.md"
    fixed = changelog.FRAGMENTS_DIR / "20260513-fixed-beta.fixed.md"
    added.write_text("Added alpha\n", encoding="utf-8")
    fixed.write_text("Fixed beta\n", encoding="utf-8")

    assert changelog.build_command() == 0

    rendered = capsys.readouterr().out
    assert "### Added\n\n- Added alpha" in rendered
    assert "### Fixed\n\n- Fixed beta" in rendered
    assert rendered.index("Added alpha") < rendered.index("Fixed beta")
    assert "Added alpha" not in read_changelog(changelog)
    assert added.exists()
    assert fixed.exists()


def test_build_command_reports_when_there_are_no_fragments(changelog, capsys):
    assert changelog.build_command() == 0

    assert "No changelog fragments found" in capsys.readouterr().out


def test_new_command_creates_date_prefixed_slug_and_detects_collisions(
    changelog, monkeypatch
):
    monkeypatch.setattr(changelog.time, "strftime", lambda _format: "20260516")

    assert changelog.new_command("fixed", "Fix Selenium flake!") == 0
    fragment = changelog.FRAGMENTS_DIR / "20260516-fix-selenium-flake.fixed.md"
    assert fragment.read_text(encoding="utf-8") == "Fix Selenium flake!\n"

    with pytest.raises(ValueError, match="already exists"):
        changelog.new_command("fixed", "Fix Selenium flake!")


def test_alpha_release_is_rejected_and_keeps_fragments(changelog):
    fragment = changelog.FRAGMENTS_DIR / "20260516-keep-until-rc.fixed.md"
    fragment.write_text("Fixed later thing\n", encoding="utf-8")
    before = read_changelog(changelog)

    with pytest.raises(ValueError, match="Alpha versions do not get changelog"):
        changelog.release_command("13.2.0a0", "2026-05-16")

    assert read_changelog(changelog) == before
    assert fragment.exists()


def test_release_candidate_consumes_fragments_without_placeholder_block(
    changelog,
):
    fragment = changelog.FRAGMENTS_DIR / "20260516-rc-fragment.fixed.md"
    fragment.write_text("RC fixed entry\n", encoding="utf-8")

    assert changelog.release_command("13.2.0rc1", "2026-05-16") == 0

    text = read_changelog(changelog)
    assert text.startswith("# CHANGELOG\n\n## [13.2.0rc1]")
    assert text.count("\n## ") == 2
    assert "Release candidate - 2026-05-16" in text
    assert "- RC fixed entry" in text
    assert not fragment.exists()


def test_stable_release_consumes_prerelease_sections_and_remaining_fragments(
    changelog,
):
    changelog.CHANGELOG_PATH.write_text(
        """# CHANGELOG

## [13.2.0rc1](url) Release candidate - 2026-05-07

### Changed

- RC1 changed entry

### Fixed

- RC1 fixed entry

## [13.2.0rc0](url) Release candidate - 2026-04-27

### Added

- RC0 added entry

### Fixed

- RC0 fixed entry

## [13.2.0b0](url) Beta - 2026-04-20

### Added

- Beta0 added entry

## [13.1.1](url) Release - 2026-02-18
""",
        encoding="utf-8",
    )
    fragment = changelog.FRAGMENTS_DIR / "20260516-final-leftover.fixed.md"
    fragment.write_text("Final leftover fixed entry\n", encoding="utf-8")

    assert changelog.release_command("13.2.0", "2026-05-16") == 0

    text = read_changelog(changelog)
    assert text.startswith("# CHANGELOG\n\n## [13.2.0]")
    assert "## [13.2.0b0]" not in text
    assert "## [13.2.0rc1]" not in text
    assert "## [13.2.0rc0]" not in text
    assert "## [13.1.1]" in text

    final_section = text.split("## [13.2.0]", 1)[1].split("## [13.1.1]", 1)[0]
    assert "- Beta0 added entry" in final_section
    assert "- RC0 added entry" in final_section
    assert "- RC0 fixed entry" in final_section
    assert "- RC1 fixed entry" in final_section
    assert "- Final leftover fixed entry" in final_section
    assert (
        final_section.index("- Beta0 added entry")
        < final_section.index("- RC0 fixed entry")
        < final_section.index("- RC1 fixed entry")
        < final_section.index("- Final leftover fixed entry")
    )
    assert not fragment.exists()


def test_stable_release_requires_fragments_or_matching_prerelease_sections(
    changelog,
):
    with pytest.raises(
        ValueError, match="No changelog fragments or matching prerelease sections found"
    ):
        changelog.release_command("13.2.0", "2026-05-16")


def test_fragment_listing_edge_cases(changelog, monkeypatch, tmp_path):
    missing_dir = tmp_path / "missing"
    monkeypatch.setattr(changelog, "FRAGMENTS_DIR", missing_dir)
    assert changelog.list_fragment_paths() == []

    fragments_dir = tmp_path / "fragments"
    fragments_dir.mkdir()
    monkeypatch.setattr(changelog, "FRAGMENTS_DIR", fragments_dir)
    (fragments_dir / "README.md").write_text("docs\n", encoding="utf-8")
    (fragments_dir / ".ignored.md").write_text("hidden\n", encoding="utf-8")
    (fragments_dir / "subdir").mkdir()
    valid = fragments_dir / "20260516-valid.fixed.md"
    valid.write_text("Fixed bug\n", encoding="utf-8")
    assert changelog.list_fragment_paths() == [valid]

    (fragments_dir / "1.fixed.md").write_text("bad\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid changelog fragment filename"):
        changelog.list_fragment_paths()


def test_empty_fragment_and_empty_entry_errors(changelog):
    with pytest.raises(ValueError, match="Fragment is empty"):
        changelog.format_entry("")

    empty = changelog.FRAGMENTS_DIR / "20260516-empty.fixed.md"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="is empty"):
        changelog.load_fragments()


def test_section_entry_parsing_edge_cases(changelog):
    assert changelog.parse_section_entries(
        "\n- First line\n  continuation\n\n- Second line\n"
    ) == ["- First line\n  continuation", "- Second line"]

    with pytest.raises(ValueError, match="Unexpected content before first"):
        changelog.parse_section_entries("not a bullet")

    with pytest.raises(ValueError, match="Unexpected changelog line format"):
        changelog.parse_section_entries("- First\nbad continuation")

    with pytest.raises(ValueError, match="Unsupported changelog subsection"):
        changelog.parse_sectioned_entries("### Security\n\n- Secret fix\n")


def test_release_labels_and_insertion_without_existing_release(changelog):
    assert changelog.classify_release("13.2.0b1") == "Beta"

    changelog_text = "# CHANGELOG\n"
    inserted = changelog.insert_release_section(
        changelog_text,
        changelog.build_release_section(
            "13.2.0b1", "2026-05-16", {"fixed": ["- Fixed beta"]}
        ),
    )
    assert inserted.endswith("### Fixed\n\n- Fixed beta\n\n")


def test_slugify_and_new_command_validation(changelog):
    with pytest.raises(ValueError, match="at least one alphanumeric"):
        changelog.slugify("!!!")

    long_slug = changelog.slugify("a" * 80)
    assert long_slug == "a" * changelog.MAX_SLUG_LENGTH

    with pytest.raises(ValueError, match="Unknown category"):
        changelog.new_command("security", "Fix issue")


def test_changed_files_uses_git_diff(changelog, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="a.py\n\nb.py\n")

    monkeypatch.setattr(changelog.subprocess, "run", fake_run)

    assert changelog.changed_files("base", "head") == ["a.py", "b.py"]
    assert calls == [
        (
            ["git", "diff", "--name-only", "base", "head"],
            {"check": True, "capture_output": True, "text": True},
        )
    ]


def test_check_mr_command_validates_current_fragments(changelog, monkeypatch):
    fragment = changelog.FRAGMENTS_DIR / "20260516-valid.fixed.md"
    fragment.write_text("Fixed valid thing\n", encoding="utf-8")
    monkeypatch.setattr(
        changelog,
        "changed_files",
        lambda _base, _head: ["changelog.d/20260516-valid.fixed.md"],
    )

    assert changelog.check_mr_command("base", "head") == 0


def test_check_mr_command_requires_fragment_path(changelog, monkeypatch):
    monkeypatch.setattr(
        changelog,
        "changed_files",
        lambda _base, _head: ["psynet/module.py"],
    )

    with pytest.raises(ValueError, match="MR must add or delete a changelog fragment"):
        changelog.check_mr_command("base", "head")


def test_check_mr_command_rejects_empty_fragment(changelog, monkeypatch):
    fragment = changelog.FRAGMENTS_DIR / "20260516-empty.fixed.md"
    fragment.write_text("\n", encoding="utf-8")
    monkeypatch.setattr(
        changelog,
        "changed_files",
        lambda _base, _head: ["changelog.d/20260516-empty.fixed.md"],
    )

    with pytest.raises(ValueError, match="is empty"):
        changelog.check_mr_command("base", "head")


def test_check_mr_command_rejects_invalid_extra_fragment(changelog, monkeypatch):
    fragment = changelog.FRAGMENTS_DIR / "20260516-valid.fixed.md"
    fragment.write_text("Fixed valid thing\n", encoding="utf-8")
    invalid = changelog.FRAGMENTS_DIR / "invalid.fixed.md"
    invalid.write_text("Fixed invalid thing\n", encoding="utf-8")
    monkeypatch.setattr(
        changelog,
        "changed_files",
        lambda _base, _head: ["changelog.d/20260516-valid.fixed.md"],
    )

    with pytest.raises(ValueError, match="Invalid changelog fragment filename"):
        changelog.check_mr_command("base", "head")


def test_check_mr_command_allows_changelog_with_only_releases(changelog, monkeypatch):
    fragment = changelog.FRAGMENTS_DIR / "20260516-valid.fixed.md"
    fragment.write_text("Fixed valid thing\n", encoding="utf-8")
    changelog.CHANGELOG_PATH.write_text(
        "# CHANGELOG\n\n## [13.2.0](url)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        changelog,
        "changed_files",
        lambda _base, _head: ["changelog.d/20260516-valid.fixed.md"],
    )

    assert changelog.check_mr_command("base", "head") == 0


def test_check_mr_command_rejects_changelog_edit_even_with_fragment(
    changelog, monkeypatch
):
    fragment = changelog.FRAGMENTS_DIR / "20260516-valid.fixed.md"
    fragment.write_text("Fixed valid thing\n", encoding="utf-8")
    monkeypatch.setattr(
        changelog,
        "changed_files",
        lambda _base, _head: [
            "CHANGELOG.md",
            "changelog.d/20260516-valid.fixed.md",
        ],
    )

    with pytest.raises(ValueError, match="must not edit CHANGELOG.md directly"):
        changelog.check_mr_command("base", "head")


def test_build_command_previews_fragments_when_changelog_has_releases(
    changelog, capsys
):
    fragment = changelog.FRAGMENTS_DIR / "20260516-valid.fixed.md"
    fragment.write_text("Fixed valid thing\n", encoding="utf-8")
    changelog.CHANGELOG_PATH.write_text(
        "# CHANGELOG\n\n## [13.2.0](url)\n",
        encoding="utf-8",
    )

    assert changelog.build_command() == 0

    assert capsys.readouterr().out == "### Fixed\n\n- Fixed valid thing\n"
    assert read_changelog(changelog) == "# CHANGELOG\n\n## [13.2.0](url)\n"


def test_build_command_previews_fragments_without_changelog(changelog, capsys):
    fragment = changelog.FRAGMENTS_DIR / "20260516-valid.fixed.md"
    fragment.write_text("Fixed valid thing\n", encoding="utf-8")
    changelog.CHANGELOG_PATH.unlink()

    assert changelog.build_command() == 0

    assert capsys.readouterr().out == "### Fixed\n\n- Fixed valid thing\n"

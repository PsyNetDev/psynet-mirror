"""
Translation tests for PsyNet.

To run translation tests locally:

    pytest tests/isolated/translation/test_translations.py -v

To check if translations are up to date (only runs on release branches):

    CI_COMMIT_REF_NAME=release-test pytest tests/isolated/translation/test_translations.py::test_psynet_translations_up_to_date -v

"""

import polib
import pytest

from psynet.translation.check import (
    assert_variable_names_match,
    translation_contains_same_variables,
)
from psynet.translation.check import check_translations as check_translations_internal
from psynet.translation.translate import check_translations
from psynet.utils import get_psynet_root, is_release_branch, working_directory


def make_entry(msgid="", msgstr=""):
    """Create a translation entry with source and translated text."""
    return type("Entry", (), {"msgid": msgid, "msgstr": msgstr})


def make_entries(source_text, translated_text):
    """Create matching pot and po entries for testing."""
    key = (source_text, None)
    return (
        {key: make_entry(msgid=source_text)},  # pot entries
        {key: make_entry(msgid=source_text, msgstr=translated_text)},  # po entries
    )


def test_matching_variables():
    """Test that translations with matching variables pass."""
    # Basic variable matching
    pot_entries, po_entries = make_entries("Hello %(name)s", "Bonjour %(name)s")
    assert_variable_names_match(pot_entries, po_entries)

    # Multiple variables
    pot_entries, po_entries = make_entries(
        "%(greeting)s %(name)s", "%(name)s %(greeting)s"
    )
    assert_variable_names_match(pot_entries, po_entries)

    # Jinja style variables
    pot_entries, po_entries = make_entries("Hello {name}", "Bonjour {name}")
    assert_variable_names_match(pot_entries, po_entries)

    # Empty strings
    pot_entries, po_entries = make_entries("", "")
    assert_variable_names_match(pot_entries, po_entries)


def test_mismatched_variables():
    """Test that translations with mismatched variables raise ValueError."""
    # Wrong variable name
    pot_entries, po_entries = make_entries("Hello %(name)s", "Bonjour %(wrong)s")
    with pytest.raises(ValueError):
        assert_variable_names_match(pot_entries, po_entries)

    # Missing variable
    pot_entries, po_entries = make_entries("Hello %(name)s", "Bonjour")
    with pytest.raises(ValueError):
        assert_variable_names_match(pot_entries, po_entries)

    # Extra variable
    pot_entries, po_entries = make_entries("Hello", "Bonjour %(extra)s")
    with pytest.raises(ValueError):
        assert_variable_names_match(pot_entries, po_entries)


def test_multiple_entries():
    """Test checking multiple translations at once."""
    pot_entries = {
        ("Hello %(name)s", None): make_entry("Hello %(name)s"),
        ("Bye %(name)s", None): make_entry("Bye %(name)s"),
    }

    # All correct
    po_entries = {
        ("Hello %(name)s", None): make_entry(
            msgid="Hello %(name)s", msgstr="Hola %(name)s"
        ),
        ("Bye %(name)s", None): make_entry(
            msgid="Bye %(name)s", msgstr="Adios %(name)s"
        ),
    }
    assert_variable_names_match(pot_entries, po_entries)

    # One wrong
    po_entries_one_wrong = {
        ("Hello %(name)s", None): make_entry(
            msgid="Hello %(name)s", msgstr="Hola %(wrong)s"
        ),
        ("Bye %(name)s", None): make_entry(
            msgid="Bye %(name)s", msgstr="Adios %(name)s"
        ),
    }
    with pytest.raises(ValueError):
        assert_variable_names_match(pot_entries, po_entries_one_wrong)


@pytest.mark.skipif(
    not is_release_branch(),
    reason="This test only runs on release branches",
)
def test_psynet_translations_up_to_date():
    """
    Verify all PsyNet package translations are up-to-date with source code.

    This does NOT call the translation API - it only checks that existing
    translations are complete and valid.

    Only runs on release branches (where CI_COMMIT_REF_NAME starts with "release-").
    """
    with working_directory(get_psynet_root()):
        check_translations_internal(path=".", recreate_pot=True)


@pytest.mark.skip
def test_run():
    VARIABLE_PLACEHOLDERS = {
        "BASE_PAYMENT": 0.1,
        "TIME_REWARD": 0.1,
        "CURRENCY": "$",
        "EMAIL": "dummy@email.com",
        "MIN_ACCUMULATED_REWARD_FOR_ABORT": 2,
        "PERFORMANCE_REWARD": 1.2,
        "TERMINATION_TIME": 120,
        "AGE": 12,
        "HIDE_AFTER": 2,
    }
    check_translations(variable_placeholders=VARIABLE_PLACEHOLDERS)


class TestTranslationContainsSameVariables:
    """Tests for translation_contains_same_variables function."""

    def test_all_checks_are_evaluated(self):
        """Verify that all variable checks are evaluated, not just the first one.

        This test would pass with a bug where only the first check (Jinja pattern)
        is evaluated, but should fail when all checks (including HTML tags) are
        properly evaluated.
        """
        # Jinja variables match, but HTML tags don't match
        original = "Hello {NAME}"
        translation = "Bonjour {NAME} <b>extra</b>"

        # Should return False because HTML tag check fails
        assert translation_contains_same_variables(original, translation) is False

    def test_matching_jinja_variables(self):
        """Test that matching Jinja variables pass."""
        assert translation_contains_same_variables("Hello {NAME}", "Bonjour {NAME}")

    def test_matching_html_tags(self):
        """Test that matching HTML tags pass."""
        assert translation_contains_same_variables(
            "<b>Hello</b> world", "<b>Bonjour</b> monde"
        )

    def test_mismatched_html_tags(self):
        """Test that mismatched HTML tags fail."""
        assert not translation_contains_same_variables("<b>Hello</b>", "<i>Bonjour</i>")

    def test_format_strings_both_absent(self):
        """Test that strings without format placeholders pass."""
        assert translation_contains_same_variables("Hello world", "Bonjour monde")

    def test_format_strings_both_present(self):
        """Test that matching empty format placeholders pass."""
        assert translation_contains_same_variables("Hello {}", "Bonjour {}")

    def test_format_string_mismatch(self):
        """Test that mismatched format placeholders fail."""
        assert not translation_contains_same_variables("Hello {}", "Bonjour")


def test_check_translations_uses_path_namespace(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "temp_pkg"
"""
    )
    package_dir = tmp_path / "temp_pkg"
    package_dir.mkdir()
    locales_dir = package_dir / "locales"
    po_dir = locales_dir / "fr" / "LC_MESSAGES"
    po_dir.mkdir(parents=True)

    pot = polib.POFile()
    pot.append(polib.POEntry(msgid="Hello", msgstr=""))
    pot.save(locales_dir / "temp_pkg.pot")

    po = polib.POFile()
    po.append(polib.POEntry(msgid="Hello", msgstr="Bonjour"))
    po_path = po_dir / "temp_pkg.po"

    with working_directory(get_psynet_root()):
        with pytest.raises(RuntimeError, match="No translation found for fr"):
            check_translations_internal(
                path=tmp_path, locales=["fr"], recreate_pot=False
            )

    po.save(po_path)

    with working_directory(get_psynet_root()):
        check_translations_internal(path=tmp_path, locales=["fr"], recreate_pot=False)


def test_check_translations_missing_entry_raises(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "temp_pkg"
"""
    )
    package_dir = tmp_path / "temp_pkg"
    package_dir.mkdir()
    locales_dir = package_dir / "locales"
    po_dir = locales_dir / "fr" / "LC_MESSAGES"
    po_dir.mkdir(parents=True)

    pot = polib.POFile()
    pot.append(polib.POEntry(msgid="Hello", msgstr=""))
    pot.append(polib.POEntry(msgid="Goodbye", msgstr=""))
    pot.save(locales_dir / "temp_pkg.pot")

    po = polib.POFile()
    po.append(polib.POEntry(msgid="Hello", msgstr="Bonjour"))
    po.save(po_dir / "temp_pkg.po")

    with working_directory(get_psynet_root()):
        with pytest.raises(IndexError, match="Missing translations for fr"):
            check_translations_internal(
                path=tmp_path, locales=["fr"], recreate_pot=False
            )

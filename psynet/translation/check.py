import importlib
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from .. import log
from ..utils import (
    get_language_dict,
    get_locales_dir_from_path,
    get_package_name,
    get_package_source_directory,
    is_a_package,
    logger,
)
from .utils import compile_mo, create_pot, get_po_path, load_po, po_to_dict

JINJA_PATTERN = "%\\((.+?)\\)s"
F_STRING_PATTERN = "{(.+?)}"


def variable_name_check(variable_name):
    """Check if a variable name is uppercase and only contains underscores and capital letters."""
    assert all([letter.isupper() or letter == "_" for letter in variable_name]), (
        f'Variable name "{variable_name}" must be uppercase and may only contain of underscore and capital letters.'
    )


def get_translations(namespace, locales_dir, locales):
    translations = {}
    for locale in sorted(locales):
        if locale == "en":
            continue
        po_path = os.path.join(locales_dir, locale, "LC_MESSAGES", namespace + ".po")
        if not os.path.exists(po_path):
            raise RuntimeError(f"No translation found for {locale}")
        translations[locale] = load_po(po_path)
    return translations


def extract_variable_names(msgid):
    variable_names = []
    for pattern in [JINJA_PATTERN, F_STRING_PATTERN]:
        variable_names.extend(re.findall(pattern, msgid))
    return variable_names


def assert_variable_names_match(pot_entries, po_entries):
    translations_with_mismatching_variables = []
    for key, pot_entry in pot_entries.items():
        pot_variables = extract_variable_names(pot_entry.msgid)
        po_entry = po_entries[key]
        po_variables = extract_variable_names(po_entry.msgstr)
        if sorted(pot_variables) != sorted(po_variables):
            translations_with_mismatching_variables.append(
                (pot_variables, po_variables, po_entry)
            )
    if len(translations_with_mismatching_variables) > 0:
        lines = []
        for (
            pot_variables,
            po_variables,
            po_entry,
        ) in translations_with_mismatching_variables:
            lines.append(
                f"Problem {len(lines) + 1}:\n"
                f"- Input text: {po_entry.msgid}\n"
                f"- Translated text: {po_entry.msgstr}\n"
                f"- Expected variables: {pot_variables}\n"
                f"- Found variables: {po_variables}"
            )
        raise ValueError(
            "Found translations with mismatching variables:\n\n"
            + "\n\n".join(lines)
            + "\n\nPlease check these translations and ensure the variable names match exactly."
        )


def assert_no_missing_translations(po_entries, pot_entries, locale):
    """Check that all translations which are defined in the POT file are also present in the po file"""

    def parse_translation(msgid, msgctxt):
        return msgid if msgctxt is None else f"{msgctxt}: {msgid}"

    missing_translations = [key for key in pot_entries.keys() if key not in po_entries]
    missing_translations = [
        parse_translation(msgid, msgctxt) for msgid, msgctxt in missing_translations
    ]

    if len(missing_translations) > 0:
        [
            logger.error(missing_translation)
            for missing_translation in missing_translations
        ]
        raise IndexError(f"Missing translations for {locale} (see above)")

    assert all([key in po_entries for key in pot_entries.keys()]), (
        f"Keys in {locale} do not match keys in the template"
    )


def assert_no_empty_translations(po_entries, pot_entries, locale, language_name):
    """Check that all translations have non-empty msgstr values."""

    def parse_translation(msgid, msgctxt):
        return msgid if msgctxt is None else f"{msgctxt}: {msgid}"

    empty_translations = [
        key
        for key in pot_entries.keys()
        if key in po_entries and not po_entries[key].msgstr.strip()
    ]
    empty_translations = [
        parse_translation(msgid, msgctxt) for msgid, msgctxt in empty_translations
    ]

    if len(empty_translations) > 0:
        entries_str = ", ".join(empty_translations[:5])
        if len(empty_translations) > 5:
            entries_str += f", ... and {len(empty_translations) - 5} more"
        raise ValueError(
            f"Empty translations for locale '{locale}' ({language_name}): {entries_str}"
        )


def assert_no_duplicate_translations_in_same_context(po_entries, locale):
    """
    Check if the same translation does not occur multiple times in the same context.

    In machine translation it happens quite often that similar entries are translated identically, e.g. siminalar items
    in a list of languages then to be translated identically, e.g. Malay and Malayam. These cases are hard to eyeball,
    so we disallow an identical translation within the same context for a different input text.
    """
    import pandas as pd

    translation_dict_list = [
        {
            "msgid": key[0],
            "msgctxt": key[1],
            "msgstr": str(entry.msgstr),
        }
        for key, entry in po_entries.items()
    ]

    translation_df = pd.DataFrame(translation_dict_list)
    for context in translation_df["msgctxt"].unique():
        translation_counts = translation_df.query(
            f"msgctxt == '{context}'"
        ).msgstr.value_counts()
        duplicate_translations = list(translation_counts.index[translation_counts > 1])

        if not all(translation_counts == 1):
            duplicates_str = ", ".join([f"'{t}'" for t in duplicate_translations])
            msg = (
                f"Translation error: "
                f"Multiple different source texts in context '{context}' were translated to the same text: {duplicates_str}."
            )
            raise AssertionError(msg)


def translation_contains_same_variables(
    original, translation, assume_same_variable_order=False
):
    """
    Assess if the translation contains the same variables as the original.

    We check the following patterns: jinja variables, f-strings, format strings, and HTML tags. Machine translations
    tend to translate variable names, which will lead to runtime errors. Also, quite often HTML tags are not translated
    properly or are not correctly closed.

    To reduce ambiguity in the translation, we assume each variable name is capital letters and underscores only (see
    `variable_name_check`). We therefore do not allow empty variable placeholders (e.g. `{}`) in the original or
    translation.
    """
    variable_checks = [
        {
            "name": "Jinja string",
            "pattern": JINJA_PATTERN,
            "assertion": "equals",
            "additional_checks": [variable_name_check],
        },
        {
            "name": "f-string",
            "pattern": F_STRING_PATTERN,
            "assertion": "equals",
            "additional_checks": [variable_name_check],
        },
        {
            "name": "format string",
            "pattern": "{}",
            "assertion": "does_not_contain",
        },
        {
            "name": "HTML tag",
            "pattern": "<(.+?)>",
            "assertion": "equals",
        },
    ]
    checks = []
    for check in variable_checks:
        found_entries_original = re.findall(check["pattern"], original)
        found_entries_translation = re.findall(check["pattern"], translation)
        for additional_check in check.get("additional_checks", []):
            for entry in found_entries_original + found_entries_translation:
                additional_check(entry)
        if check["assertion"] == "equals":
            if assume_same_variable_order:
                checks.append(found_entries_original == found_entries_translation)
            else:
                checks.append(
                    set(found_entries_original) == set(found_entries_translation)
                )
        elif check["assertion"] == "does_not_contain":
            f_strings_in_original = set(re.findall(check["pattern"], original))
            f_strings_in_translation = set(re.findall(check["pattern"], translation))
            checks.append(f_strings_in_original == f_strings_in_translation)
        else:
            raise ValueError(f"Unknown assertion {check['assertion']}")
    return all(checks)


def assert_no_runtime_errors(
    gettext, pgettext, locale, msgid, msgstr, msgctxt, variable_placeholders
):
    """Make sure that the translation does not raise a runtime error when replacing the variable."""
    kwargs = {
        variable_name: variable_placeholders[variable_name]
        for variable_name in extract_variable_names(msgid)
    }
    try:
        if msgctxt == "":
            gettext(msgid).format(**kwargs)
        else:
            pgettext(msgctxt, msgid).format(**kwargs)
    except Exception as e:
        raise RuntimeError(
            f"Runtime error in {locale} for {msgid} with translation {msgstr}"
        ) from e


def _check_translations(pot_entries, translations, locales_dir, namespace):
    import gettext

    language_dict = get_language_dict("en")

    for locale, po in translations.items():
        language_name = language_dict[locale]
        logger.info(
            log.bold(f"Checking {locale} translation ({language_name}) for errors...")
        )
        po_entries = po_to_dict(po)

        assert_no_missing_translations(po_entries, pot_entries, locale)

        assert_variable_names_match(pot_entries, po_entries)

        assert_no_empty_translations(po_entries, pot_entries, locale, language_name)

        # Check for duplicates - warn but don't fail
        try:
            assert_no_duplicate_translations_in_same_context(po_entries, locale)
        except AssertionError as e:
            print(f"⚠️  Warning: {e}")

        po_path = get_po_path(locale, locales_dir, namespace)
        compile_mo(po_path)
        translator = gettext.translation(namespace, locales_dir, [locale])

        for key, po_entry in po_entries.items():
            msgid, msgctxt = key
            msgstr = str(po_entry.msgstr)

            variables = extract_variable_names(msgid)
            variable_placeholders = dict(zip(variables, len(variables) * [""]))
            assert_no_runtime_errors(
                translator.gettext,
                translator.pgettext,
                locale,
                msgid,
                msgstr,
                msgctxt,
                variable_placeholders,
            )
        os.remove(po_path.replace(".po", ".mo"))


def check_translations(
    path=".",
    locales: Optional[list[str]] = None,
    recreate_pot=True,
):
    """
    Check translations for errors.

    Parameters
    ----------
    path : str
        Path to package or experiment directory.
    locales : list[str], optional
        List of locales to check. If None, uses supported_locales.
    recreate_pot : bool
        Whether to recreate the POT file from source.
    """
    path = Path(path)
    locales_dir = get_locales_dir_from_path(path)

    if is_a_package(path):
        source_directory = get_package_source_directory(path)
        namespace = get_package_name(path)
        if locales is None:
            from .languages import psynet_supported_locales

            package = importlib.import_module(namespace)
            locales = getattr(package, "supported_locales", psynet_supported_locales)
    elif (path / "experiment.py").exists():
        from ..experiment import get_experiment

        source_directory = path
        namespace = "experiment"
        if locales is None:
            locales = get_experiment().supported_locales
    else:
        raise ValueError(
            f"{path} does not appear to be either a package or an experiment directory."
        )

    if recreate_pot:
        with tempfile.NamedTemporaryFile(suffix=".pot") as f:
            pot_path = f.name
            pot = create_pot(source_directory, pot_path)
    else:
        pot_path = os.path.join(locales_dir, namespace + ".pot")
        pot = load_po(pot_path)

    pot_entries = po_to_dict(pot)

    translations = get_translations(namespace, locales_dir, locales)

    _check_translations(
        pot_entries=pot_entries,
        translations=translations,
        locales_dir=locales_dir,
        namespace=namespace,
    )

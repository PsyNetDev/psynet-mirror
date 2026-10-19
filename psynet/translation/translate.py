import os
import time
from copy import copy
from functools import cached_property
from typing import Iterable, List, Optional

import polib
from yaspin import yaspin

from psynet.translation.translators import (
    DefaultTranslator,
    TranslationError,
    Translator,
)

from ..log import bold
from ..utils import (
    get_language_dict,
    get_package_name,
    get_package_source_directory,
    require_exp_directory,
)
from . import psynet_supported_locales
from .check import check_translations
from .utils import create_pot, remove_line_numbers, sort_po


@require_exp_directory
def translate_experiment(
    locales: List[str],
    force: bool = False,
    skip_pot: bool = False,
    continue_on_error: bool = True,
    translator: Optional[Translator] = None,
):
    namespace = "experiment"
    source_directory = os.getcwd()
    locales_directory = os.path.join(os.getcwd(), "locales")

    if len(locales) == 0:
        from psynet.experiment import get_experiment

        locales = get_experiment().supported_locales

    translate(
        namespace,
        source_directory,
        locales_directory,
        locales,
        force=force,
        skip_pot=skip_pot,
        continue_on_error=continue_on_error,
        translator=translator,
    )


def translate_package(
    locales: List[str],
    force: bool = False,
    skip_pot: bool = False,
    continue_on_error: bool = True,
    translator: Optional[Translator] = None,
):
    namespace = get_package_name()
    source_directory = get_package_source_directory()
    locales_directory = os.path.join(source_directory, "locales")

    if len(locales) == 0:
        locales = psynet_supported_locales

    translate(
        namespace,
        source_directory,
        locales_directory,
        locales,
        force=force,
        skip_pot=skip_pot,
        continue_on_error=continue_on_error,
        translator=translator,
    )


def translate(
    namespace,
    source_dir,
    locales_dir,
    locales,
    force: bool = False,
    skip_pot: bool = False,
    continue_on_error: bool = True,
    translator=None,
):
    locales = [locale for locale in locales if locale != "en"]

    check_locales(locales)

    pot_path = str(os.path.join(locales_dir, namespace + ".pot"))
    if skip_pot:
        pot = polib.pofile(pot_path)
    else:
        pot = create_pot(source_dir, pot_path)

    print(bold(f"Translating {pot_path} into {len(locales)} languages:"))

    n_valid_translations = 0
    for locale in locales:
        translation_valid = translate_pot(
            pot_path,
            target_language=locale,
            force=force,
            continue_on_error=continue_on_error,
            translator=translator,
        )
        n_valid_translations += int(translation_valid)

    n_failed_translations = len(locales) - n_valid_translations
    if n_failed_translations > 0:
        print(
            "\n"
            + bold("Some translations failed.")
            + " Please check the output above and fix the errors and run `psynet translate` again.\n"
            + "\nNote: Duplicate translations often happen with similar-looking words. "
            + "Please review these translations to ensure each has a distinct translation appropriate to its specific meaning.\n"
        )
    pot.save(pot_path)


def translate_pot(
    pot_path,
    target_language,
    source_language="en",
    force: bool = False,
    continue_on_error=True,
    translator=None,
):
    if not os.path.isabs(pot_path):
        pot_path = os.path.abspath(pot_path)
    assert os.path.exists(pot_path), "Input file does not exist."
    assert pot_path.endswith(".pot"), "Input file must be a POT file."

    po_filename = os.path.basename(pot_path).replace(".pot", ".po")
    dir_name = os.path.join(os.path.dirname(pot_path), target_language, "LC_MESSAGES")
    os.makedirs(dir_name, exist_ok=True)
    po_path = os.path.join(dir_name, po_filename)

    if force:
        try:
            os.remove(po_path)
        except FileNotFoundError:
            pass

    return translate_po(
        pot_path,
        po_path,
        source_language,
        target_language,
        continue_on_error,
        translator=translator,
    )


def check_locales(locales: Iterable[str]):
    from .languages import get_known_languages

    assert isinstance(locales, Iterable) and not isinstance(locales, str)

    known_languages = get_known_languages()
    language_codes = [language[0] for language in known_languages]

    for locale in locales:
        if locale not in language_codes:
            raise ValueError(f"Unknown locale: {locale}")

    return True


class TranslationUnit:
    def __init__(self, file: str):
        self.file = file
        self.entries = []

    def append(self, entry: polib.POEntry):
        self.entries.append(entry)

    def __len__(self):
        return len(self.entries)

    @cached_property
    def translator(self):
        return DefaultTranslator()

    def sort_by_line_number(self):
        # We can assume that each entry has only a single occurrence, by virtue of the logic in `from_po`.
        # We can also assume that each entry comes from the same file. So, we just need to look at the first
        # element in entry.occurrences, which is a tuple (file, line_number), and take the second element.
        # Note that this line number is by default a string, so we need to convert it to an integer.
        self.entries.sort(key=lambda entry: int(entry.occurrences[0][1]))

    @classmethod
    def from_po(
        cls, po: Optional[polib.POFile]
    ) -> dict[tuple[str, str], "TranslationUnit"]:
        units = {}

        if po is None:
            return units

        # For each text that we find the po file, we look at each occurrence separately.
        # Our aim is to create a TranslationUnit for each file, which contains one entry per occurrence.
        # This involves creating multiple copies of the same entry, with the same msgid, but different occurrences.
        for entry in po:
            occurrences = entry.occurrences  # list of tuples (file, line_number)
            files = [occurrence[0] for occurrence in occurrences]

            for file, occurrence in zip(files, occurrences):
                try:
                    unit = units[file]
                except KeyError:
                    units[file] = unit = TranslationUnit(file=file)

                _entry = copy(entry)
                _entry.occurrences = [occurrence]

                unit.append(_entry)

        return units

    @classmethod
    def inherit(
        cls,
        new: "dict[tuple[str, str], TranslationUnit]",
        old: "dict[tuple[str, str], TranslationUnit]",
    ):
        result = {}

        for key in new.keys():
            if (
                key in old
                and old[key].is_translated
                and set(old[key].text_to_translate) == set(new[key].text_to_translate)
            ):
                # The old translation is already translated, so we will inherit it directly.
                # and not retranslate it.
                # We will however update the `occurrences` property to match the new file.
                old_unit = copy(old[key])
                new_unit = copy(new[key])

                for new_entry, old_entry in zip(new_unit.entries, old_unit.entries):
                    old_entry.occurrences = new_entry.occurrences

                result[key] = old_unit
            else:
                result[key] = new[key]

        return result

    @property
    def is_translated(self):
        return all(entry.msgstr for entry in self.entries)

    @property
    def text_to_translate(self):
        return [entry.msgid for entry in self.entries]

    def translate(
        self, source_lang, target_lang, continue_on_error=False, translator=None
    ):
        if translator is None:
            translator = self.translator

        assert isinstance(translator, Translator)

        input_texts = self.text_to_translate

        try:
            translated_texts = translator.translate(
                texts=input_texts,
                source_lang=source_lang,
                target_lang=target_lang,
                file_path=self.file,
            )
        except TranslationError as e:
            if continue_on_error:
                translated_texts = [""] * len(input_texts)
                print(f"Translation failed: {e}, skipping.")
            else:
                raise e
        assert len(translated_texts) == len(input_texts)

        for entry, translated_text in zip(self.entries, translated_texts):
            entry.msgstr = translated_text
            entry.fuzzy = True  # Signals that the translation needs to be reviewed


def translate_po(
    pot_path, po_path, source_lang, target_lang, continue_on_error, translator=None
):
    # Add yaspin spinner here
    language_dict = get_language_dict("en")
    assert target_lang in language_dict, (
        f"Language {target_lang} not found in language_dict"
    )
    target_language = language_dict[target_lang]
    assert target_lang != "en", (
        "English is the source language, so doesn't need translation."
    )
    bold_language = bold(f"{target_language} ({target_lang})")
    with yaspin() as spinner:
        now = time.time()
        spinner.text = f"{bold_language}: Start translating..."

        old_po = polib.pofile(po_path) if os.path.exists(po_path) else None
        new_po = initialize_po(pot_path, po_path, target_lang)

        old_units = TranslationUnit.from_po(old_po)
        new_units = TranslationUnit.from_po(new_po)

        for unit in new_units.values():
            unit.sort_by_line_number()

        combined_units = TranslationUnit.inherit(new_units, old_units)

        units_to_translate = [
            unit for unit in combined_units.values() if not unit.is_translated
        ]

        n_to_translate = len(units_to_translate)
        n_to_skip = len(combined_units) - n_to_translate

        if n_to_skip > 0:
            spinner.text = f"{bold_language}: Skipping translations in {n_to_skip} file(s), because no new text was found to translate."

        total_entries = sum(len(unit) for unit in units_to_translate)
        remaining_entries = copy(total_entries)
        for i, translation_unit in enumerate(units_to_translate):
            if not translation_unit.is_translated:
                remaining_entries -= len(translation_unit)
                spinner.text = f"{bold_language}: Translating file {1 + i}/{n_to_translate} ({translation_unit.file}, {len(translation_unit)} entries, {remaining_entries} remaining)."
                translation_unit.translate(
                    source_lang, target_lang, continue_on_error, translator
                )

        # This function should try and preserve the ordering of the old_po file where possible
        # Strategy: po should be sorted by (a) file path and (b) line number
        # If the same _() call is used in multiple places, then we keep the first one.
        # We won't actually store the line numbers in the saved version, but we use them for sorting before we remove them
        # from the pot file.

        po = update_po(
            new_po,  # We are going to in-place modify the new_po object:
            combined_units,  # we will incorporate the new translations from combined_units;
            old_po,  # we will preserve any manual translations from old_po.
        )

        po = sort_po(po)
        po = remove_line_numbers(po)

        po.save(po_path)
        try:
            check_translations(locales=[target_lang], recreate_pot=False)
            # TODO TranslationCheckError

        except Exception as e:
            error_message = str(e)
            spinner.text = f"{bold_language}: {error_message}"
            spinner.fail("💥")
            return False

        if n_to_translate > 0:
            taken = round(time.time() - now)
            ms_per_entry = round(1000 * taken / total_entries)
            spinner.text = f"{bold_language}: Translation complete ({taken}s, {ms_per_entry}ms/entry)."
            spinner.ok("✅")
        else:
            spinner.text = f"{bold_language}: No new text found to translate."
            spinner.ok("⚠️")
        return True


def update_po(
    new_po: polib.POFile,
    combined_units: dict[tuple[str, str], TranslationUnit],
    old_po: Optional[polib.POFile],
):
    # Flatten the combined_units dictionary into a list of entries
    newly_translated_entries = [
        entry for unit in combined_units.values() for entry in unit.entries
    ]

    # Convert this into a dictionary, keyed by (msgctxt, msgid)
    newly_translated_entries = {
        (entry.msgctxt, entry.msgid): entry for entry in newly_translated_entries
    }

    # Convert old_po into an analogous dictionary, keyed by (msgctxt, msgid), only keeping manual translations
    # (i.e. entries that have the 'fuzzy' flag set)
    if old_po is None:
        old_manual_translations = {}
    else:
        old_manual_translations = {
            (entry.msgctxt, entry.msgid): entry for entry in old_po if not entry.fuzzy
        }

    # Iterate over the new_po file.
    # If the entry is in old_manual_translations, then use this old translation.
    # Otherwise, use the new translation from combined_units.
    # If neither works, throw an error.
    for i, entry in enumerate(new_po):
        occurrences = entry.occurrences

        key = (entry.msgctxt, entry.msgid)
        if key in old_manual_translations:
            new_po[i] = old_manual_translations[key]
        elif key in newly_translated_entries:
            new_po[i] = newly_translated_entries[key]
        else:
            raise ValueError(
                f"Entry {key} not found in old_manual_translations or newly_translated_entries"
            )

        new_po[i].occurrences = occurrences

    return new_po


def initialize_po(pot_path, po_path, output_lang):
    po = polib.pofile(pot_path)

    # Preserve the metadata from the old po file if it exists
    if os.path.exists(po_path):
        old_po = polib.pofile(po_path)
        po.metadata = old_po.metadata
    else:
        po.metadata["Language"] = output_lang
        po.metadata["MIME-Version"] = "1.0"
        po.metadata["Content-Type"] = "text/plain; charset=UTF-8"
        po.metadata["Content-Transfer-Encoding"] = "8bit"

    return po

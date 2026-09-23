import os
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional

import polib
from yaspin import yaspin

from psynet.translation.translators import (
    DefaultTranslator,
    TranslationContext,
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


MAX_BATCH_SIZE = 30
MAX_EXAMPLES = 20


def _line_number(entry: polib.POEntry) -> Optional[int]:
    try:
        return int(entry.occurrences[0][1])
    except (IndexError, ValueError):
        return None


def _file(entry: polib.POEntry) -> Optional[str]:
    return entry.occurrences[0][0] if entry.occurrences else None


def reuse_translations(po: polib.POFile, old_po: Optional[polib.POFile]) -> int:
    """
    Copy every existing translation from ``old_po`` into ``po``, message by message.

    A message keeps its translation, including its fuzzy flag, for as long as its
    text and context are unchanged. Returns the number of reused translations.
    """
    if old_po is None:
        return 0
    previous = {
        (entry.msgctxt, entry.msgid): entry
        for entry in old_po
        if entry.msgstr and not entry.obsolete
    }
    n_reused = 0
    for i, entry in enumerate(po):
        old_entry = previous.get((entry.msgctxt, entry.msgid))
        if old_entry is not None:
            old_entry.occurrences = entry.occurrences
            po[i] = old_entry
            n_reused += 1
    return n_reused


@dataclass
class TranslationBatch:
    """Untranslated messages from one source file, sent in one request."""

    file: Optional[str]
    entries: List[polib.POEntry]
    examples: List[tuple[str, str]]

    def translate(self, source_lang, target_lang, continue_on_error, translator):
        texts = [entry.msgid for entry in self.entries]
        context = TranslationContext(
            file_path=self.file,
            labels=[entry.msgctxt for entry in self.entries],
            line_numbers=[_line_number(entry) for entry in self.entries],
            examples=self.examples,
        )
        try:
            translated_texts = translator.translate(
                texts=texts,
                source_lang=source_lang,
                target_lang=target_lang,
                context=context,
            )
        except TranslationError as e:
            if not continue_on_error:
                raise e
            translated_texts = [""] * len(texts)
            print(f"Translation failed: {e}, skipping.")
        assert len(translated_texts) == len(texts)

        for entry, translated_text in zip(self.entries, translated_texts):
            entry.msgstr = translated_text
            entry.fuzzy = True  # Signals that the translation needs to be reviewed


def batch_untranslated(po: polib.POFile) -> List[TranslationBatch]:
    """
    Group untranslated messages by source file, in source order.

    Each file is split into batches of at most ``MAX_BATCH_SIZE`` messages.
    Translated messages from the same file are attached as examples, preferring
    those that share a gettext context with the batch, so new translations stay
    consistent with existing ones.
    """
    files = {}
    for entry in po:
        files.setdefault(_file(entry), []).append(entry)

    batches = []
    for file, entries in files.items():
        entries.sort(key=lambda entry: _line_number(entry) or 0)
        untranslated = [entry for entry in entries if not entry.msgstr]
        translated = [entry for entry in entries if entry.msgstr]
        for i in range(0, len(untranslated), MAX_BATCH_SIZE):
            batch_entries = untranslated[i : i + MAX_BATCH_SIZE]
            labels = {entry.msgctxt for entry in batch_entries}
            examples = sorted(translated, key=lambda entry: entry.msgctxt not in labels)
            batches.append(
                TranslationBatch(
                    file=file,
                    entries=batch_entries,
                    examples=[(e.msgid, e.msgstr) for e in examples[:MAX_EXAMPLES]],
                )
            )
    return batches


def translate_po(
    pot_path, po_path, source_lang, target_lang, continue_on_error, translator=None
):
    language_dict = get_language_dict("en")
    assert target_lang in language_dict, (
        f"Language {target_lang} not found in language_dict"
    )
    target_language = language_dict[target_lang]
    assert target_lang != "en", (
        "English is the source language, so doesn't need translation."
    )
    if translator is None:
        translator = DefaultTranslator()
    assert isinstance(translator, Translator)

    bold_language = bold(f"{target_language} ({target_lang})")
    with yaspin() as spinner:
        now = time.time()
        spinner.text = f"{bold_language}: Start translating..."

        old_po = polib.pofile(po_path) if os.path.exists(po_path) else None
        po = initialize_po(pot_path, po_path, target_lang)
        reuse_translations(po, old_po)
        batches = batch_untranslated(po)

        total_entries = sum(len(batch.entries) for batch in batches)
        for i, batch in enumerate(batches):
            spinner.text = f"{bold_language}: Translating batch {1 + i}/{len(batches)} ({batch.file}, {len(batch.entries)} of {total_entries} entries)."
            batch.translate(source_lang, target_lang, continue_on_error, translator)

        # Line numbers are only needed for sorting and prompts; they are not saved.
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

        if total_entries > 0:
            taken = round(time.time() - now)
            ms_per_entry = round(1000 * taken / total_entries)
            spinner.text = f"{bold_language}: Translated {total_entries} new entries ({taken}s, {ms_per_entry}ms/entry)."
            spinner.ok("✅")
        else:
            spinner.text = f"{bold_language}: No new text found to translate."
            spinner.ok("⚠️")
        return True


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

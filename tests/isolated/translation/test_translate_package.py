import json
import math

import polib

from psynet.translation.translate import MAX_BATCH_SIZE, translate_package
from psynet.utils import get_psynet_root, working_directory

mock_translate_counter = -1


def mock_translate_func(texts, source_lang, target_lang, context=None):
    global mock_translate_counter
    mock_translate_counter += 1
    return [
        json.dumps(
            {
                "languages": f"{source_lang} -> {target_lang}",
                "translation_file_context": context.file_path,
                "api_call_id": mock_translate_counter,
                "text": text,
            }
        )
        for text in range(len(texts))
    ]


def reset_mock_translate_counter():
    global mock_translate_counter
    mock_translate_counter = -1


def test_translate_psynet(mocker, tmp_path):
    """
    Tests the logic for translating the PsyNet package.

    The autotranslator function is mocked to produce outputs of the following form:
    "source_language: en, target_language: fr, source_text: Hello, target_text: Bonjour, call_id: 1"
    where call_id is a unique identifier for the call to the autotranslator.

    We write the generated catalogs into ``tmp_path`` so the test never mutates
    the shared ``psynet/locales`` directory (which would race with parallel
    tests that compile PsyNet's translations).
    """
    mock_translate = mocker.patch(
        "psynet.translation.translators.DefaultTranslator.translate"
    )
    mock_translate.side_effect = mock_translate_func

    reset_mock_translate_counter()

    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    with working_directory(get_psynet_root()):
        translate_package(["fr", "de"], locales_directory=str(locales_dir))

    po_fr = polib.pofile(str(locales_dir / "fr" / "LC_MESSAGES" / "psynet.po"))
    entry_gender = [
        entry for entry in po_fr if entry.msgid == "How do you identify yourself?"
    ][0]
    entry_gender_json = json.loads(entry_gender.msgstr)
    assert entry_gender_json["languages"] == "en -> fr"

    # Note that the po file is relative to the psynet root, so we need to check the end of the path
    assert entry_gender_json["translation_file_context"].endswith(
        "psynet/demography/general.py"
    )

    entries_demography = [
        entry
        for entry in po_fr
        if entry.occurrences[0][0] == "psynet/demography/general.py"
    ]

    # Translations are batched by file, in batches of at most MAX_BATCH_SIZE.
    api_call_ids = {
        json.loads(entry.msgstr)["api_call_id"] for entry in entries_demography
    }
    assert len(api_call_ids) == math.ceil(len(entries_demography) / MAX_BATCH_SIZE)

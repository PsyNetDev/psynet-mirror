import json
import math
import shutil
from pathlib import Path

import polib
import pytest

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


@pytest.fixture
def backup_locales():
    """Backup and restore psynet/locales directory during test."""
    locales_dir = Path(get_psynet_root()) / "psynet" / "locales"
    backup_dir = locales_dir.parent / "locales_backup"

    # Backup existing locales if they exist
    if locales_dir.exists():
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.move(locales_dir, backup_dir)

    # Create fresh locales dir
    locales_dir.mkdir(exist_ok=True)

    yield

    # Restore from backup
    if locales_dir.exists():
        shutil.rmtree(locales_dir)
    if backup_dir.exists():
        shutil.move(backup_dir, locales_dir)


def test_translate_psynet(mocker, backup_locales):
    """
    Tests the logic for translating the PsyNet package.

    The autotranslator function is mocked to produce outputs of the following form:
    "source_language: en, target_language: fr, source_text: Hello, target_text: Bonjour, call_id: 1"
    where call_id is a unique identifier for the call to the autotranslator.

    We run this test on the local PsyNet package. To avoid overwriting the pre-existing translations,
    we use a fixture to backup the original contents of "psynet/locales" while running this test.
    """
    mock_translate = mocker.patch(
        "psynet.translation.translators.DefaultTranslator.translate"
    )
    mock_translate.side_effect = mock_translate_func

    reset_mock_translate_counter()

    with working_directory(get_psynet_root()):
        translate_package(["fr", "de"])

    po_fr = polib.pofile("psynet/locales/fr/LC_MESSAGES/psynet.po")
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

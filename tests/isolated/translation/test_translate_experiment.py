import os

import polib
import pytest

from psynet.pytest_psynet import path_to_test_experiment
from psynet.translation.translate import translate_experiment

po_path = os.path.join("locales", "fr", "LC_MESSAGES", "experiment.po")


@pytest.fixture
def cleanup_po_file():
    yield
    if os.path.exists(po_path):
        os.remove(po_path)


@pytest.fixture
def backup_experiment_py(in_experiment_directory):
    """Save and restore experiment.py during test.

    Creates a backup of experiment.py before the test runs and restores it afterwards.
    """
    import shutil
    from pathlib import Path

    experiment_py = Path("experiment.py")
    backup_path = Path("experiment.py.bak")

    shutil.copy2(experiment_py, backup_path)

    yield

    if experiment_py.exists():
        experiment_py.unlink()
    shutil.move(backup_path, experiment_py)


@pytest.mark.usefixtures(
    "in_experiment_directory", "cleanup_po_file", "backup_experiment_py"
)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("translation")], indirect=True
)
def test_translate_experiment(mocker):
    mock_translate = mocker.patch(
        "psynet.translation.translators.DefaultTranslator.translate"
    )

    def expected_translation(source_lang, target_lang, i, text):
        return f"{source_lang} -> {target_lang} {i}: {text}"

    def mock_translate_func(texts, source_lang, target_lang, file_path=None):
        return [
            expected_translation(source_lang, target_lang, i, text)
            for i, text in enumerate(texts)
        ]

    mock_translate.side_effect = mock_translate_func

    translate_experiment(["fr"])

    # We expect all texts within experiment.py to be batched into a single call to the translator
    # (because the rule is that all texts within a single file are translated together)
    mock_translate.assert_called_once_with(
        texts=[
            "Hello, welcome to my experiment!",
            # The text is repeated in the source code file, so we repeat it in the translator too,
            # because in theory this repetition is relevant context for the translator.
            "What is your name?",
            "What is your name?",
            "Hello, {NAME}!",
            "What is your favorite pet?",
            "dog",
            "cat",
            "fish",
            "hamster",
            "bird",
            "snake",
            "Great, I like {PET} too!",
        ],
        source_lang="en",
        target_lang="fr",
        file_path="experiment.py",
    )

    # Expect the translation to be written to the PO file
    global po_path
    assert os.path.exists(po_path)
    po = polib.pofile(po_path)

    # Expected message IDs and their corresponding translations
    expected_entries = [
        (
            "Hello, welcome to my experiment!",
            "en -> fr 0: Hello, welcome to my experiment!",
        ),
        # Unlike the translator, the po file will only contain one entry for "What is your name?".
        # This is because all entries with the same msgid are merged into a single entry in the PO file.
        # Only the last translation is kept; en -> fr 1 is therefore omitted from the PO file.
        ("What is your name?", "en -> fr 2: What is your name?"),
        ("Hello, {NAME}!", "en -> fr 3: Hello, {NAME}!"),
        ("What is your favorite pet?", "en -> fr 4: What is your favorite pet?"),
        ("dog", "en -> fr 5: dog"),
        ("cat", "en -> fr 6: cat"),
        ("fish", "en -> fr 7: fish"),
        ("hamster", "en -> fr 8: hamster"),
        ("bird", "en -> fr 9: bird"),
        ("snake", "en -> fr 10: snake"),
        ("Great, I like {PET} too!", "en -> fr 11: Great, I like {PET} too!"),
    ]

    # Check each entry matches expected msgid and translation
    for i, (expected_msgid, expected_msgstr) in enumerate(expected_entries):
        assert po[i].msgid == expected_msgid
        assert po[i].msgstr == expected_msgstr
        assert po[i].fuzzy

        # occurrences is a list of tuples, where each tuple contains (filename, line_number)
        # line_number should be None since we clean the PO file to remove line numbers
        occurrences = po[i].occurrences
        assert len(occurrences) == 1

        occurrence = occurrences[0]
        filename, line_number = occurrence

        assert filename == "experiment.py"
        assert line_number == "" or line_number is None

    # Now let's imagine that we manually edit one of the translations in the PO file.
    # When doing so, we remove the fuzzy flag to indicate that the translation is complete.
    po[0].msgstr = "manual translation"
    po[0].fuzzy = False
    po.save()

    # Let's additonally append a new translatable string to experiment.py
    with open("experiment.py", "a") as f:
        f.write("\n_('Translate me please')")

    # Now let's run the translation again
    translate_experiment(["fr"])

    # The original manual translation should still be there
    po = polib.pofile(po_path)
    assert po[0].msgstr == "manual translation"
    assert not po[0].fuzzy

    # The new translatable string should be translated
    assert po[-1].msgid == "Translate me please"
    assert po[-1].msgstr == "en -> fr 12: Translate me please"

    # Now let's reinstate the fuzzy flag for the original manual translation
    po[0].fuzzy = True
    po.save()

    # And add one more translatable string to experiment.py, to invalidate the existing translations
    with open("experiment.py", "a") as f:
        f.write("\n_('Translate me next')")

    # Now let's run the translation again
    translate_experiment(["fr"])

    # The manual translation should now be overwritten by the machine translation
    po = polib.pofile(po_path)
    assert po[0].msgstr == "en -> fr 0: Hello, welcome to my experiment!"
    assert po[0].fuzzy


@pytest.mark.usefixtures(
    "in_experiment_directory", "cleanup_po_file", "backup_experiment_py"
)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("translation")], indirect=True
)
def test_null_translator(mocker):
    """Test that the NullTranslator just copies the original text without translating it."""
    from click.testing import CliRunner

    from psynet.command_line import translate

    runner = CliRunner()
    runner.invoke(translate, ["fr", "--translator", "null"])

    # Verify PO file was created with original text as translations
    assert os.path.exists(po_path)
    po = polib.pofile(po_path)

    # Expected message IDs (translations should be identical)
    expected_entries = [
        "Hello, welcome to my experiment!",
        "What is your name?",
        "Hello, {NAME}!",
        "What is your favorite pet?",
        "dog",
        "cat",
        "fish",
        "hamster",
        "bird",
        "snake",
        "Great, I like {PET} too!",
    ]

    # Check each entry has identical msgid and msgstr
    for i, expected_msgid in enumerate(expected_entries):
        assert po[i].msgid == expected_msgid
        assert po[i].msgstr == expected_msgid
        assert po[i].fuzzy

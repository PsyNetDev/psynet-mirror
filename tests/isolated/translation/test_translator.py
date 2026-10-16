"""
Translator tests for PsyNet.

To run these tests locally (requires API credentials):

    pytest tests/isolated/translation/test_translator.py -v

These tests require an OpenAI API key: set `openai_api_key` in .dallingerconfig.
"""

import os

import pytest

from psynet.experiment import import_local_experiment
from psynet.pytest_psynet import local_only, path_to_test_experiment
from psynet.translation.translators import (
    ChatGptTranslator,
    TranslationContext,
)

TEST_TRANSLATIONS = [
    (["Hello", "Goodbye"], ["Bonjour", "Au revoir"]),
    (
        ['<div class="alert alert-primary" role="alert">Hello</div>'],
        ['<div class="alert alert-primary" role="alert">Bonjour</div>'],
    ),
    (["Goodbye {NAME}!"], ["Au revoir {NAME}!"]),
    (["Thank you"], ["Merci"]),
]


@local_only  # We don't run this in the CI because it requires an OpenAI API key
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("english,expected_french", TEST_TRANSLATIONS)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("translation")], indirect=True
)
def test_translator(english, expected_french, experiment_directory):
    """
    Test that ChatGPT correctly handles basic English to French translations.

    Parameters
    ----------
    english : list
        Input English texts
    expected_french : list
        Expected French translation
    """
    import_local_experiment()
    translator = ChatGptTranslator()
    assert len(english) == len(expected_french)
    result = translator.translate(texts=english, source_lang="en", target_lang="fr")

    assert len(english) == len(result)
    for i, translation in enumerate(result):
        assert preprocess_translation(translation) == preprocess_translation(
            expected_french[i]
        )


@local_only
def test_translator_with_file_path():
    """Test that translators properly handle file paths."""
    translator = ChatGptTranslator()
    os.chdir(path_to_test_experiment("translation"))

    translations = translator.translate(
        texts=[
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
        ],
        source_lang="en",
        target_lang="fr",
        context=TranslationContext(file_path="experiment.py"),
    )

    # Sentences have several valid translations, so only the single words are
    # pinned; the sentences must keep their variables.
    assert len(translations) == 11
    assert [preprocess_translation(t) for t in translations[4:10]] == [
        "chien",
        "chat",
        "poisson",
        "hamster",
        "oiseau",
        "serpent",
    ]
    assert "{NAME}" in translations[2]
    assert "{PET}" in translations[10]


def preprocess_translation(text: str) -> str:
    """
    Normalize translation text for comparison.

    Parameters
    ----------
    text : str
        The text to normalize

    Returns
    -------
    str
        Normalized text with standardized spacing and punctuation
    """
    return (
        text.lower().strip().replace(" !", "!").replace(" ?", "?")
        # Add any future normalization rules here
    )


@local_only
def test_invalid_language():
    """Test that translators properly handle invalid language codes."""
    translator = ChatGptTranslator()

    # TODO - raise a more specific exception here
    with pytest.raises(Exception):
        translator.translate(
            texts=["Hello"], source_lang="en", target_lang="invalid_code"
        )

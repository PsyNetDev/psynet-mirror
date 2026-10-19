"""
Translator tests for PsyNet.

To run these tests locally (requires API credentials):

    pytest tests/isolated/translation/test_translator.py -v

These tests require either:
- OpenAI API key (for ChatGptTranslator) - set `openai_api_key` in .dallingerconfig
- Google Cloud Translate API key (for GoogleTranslator) - set `google_translate_json_path` in .dallingerconfig

If only OpenAI credentials are available, run ChatGPT tests only:

    pytest tests/isolated/translation/test_translator.py -k "ChatGpt" -v

"""

import os

import pytest

from psynet.experiment import import_local_experiment
from psynet.pytest_psynet import local_only, path_to_test_experiment
from psynet.translation.translators import ChatGptTranslator, GoogleTranslator

TEST_TRANSLATIONS = [
    (["Hello", "Goodbye"], ["Bonjour", "Au revoir"]),
    (
        ['<div class="alert alert-primary" role="alert">Hello</div>'],
        ['<div class="alert alert-primary" role="alert">Bonjour</div>'],
    ),
    (["Goodbye ■0■!"], ["Au revoir ■0■!"]),  # The variable {NAME} gets encoded as ■0■
    (["Thank you"], ["Merci"]),
]


@local_only  # We don't run this in the CI because it requires an API keys for the autotranslators
@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.parametrize("translator_class", [GoogleTranslator, ChatGptTranslator])
@pytest.mark.parametrize("english,expected_french", TEST_TRANSLATIONS)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("translation")], indirect=True
)
def test_translator(translator_class, english, expected_french, experiment_directory):
    """
    Test that translators correctly handle basic English to French translations.

    Parameters
    ----------
    translator_class : class
        The translator class to test
    english : list
        Input English texts
    expected_french : list
        Expected French translation
    """
    import_local_experiment()
    translator = translator_class()
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
            "Hello, {NAME}!",  # ChatGptTranslator uses use_codebook=False, so variables are not encoded
            "What is your favorite pet?",
            "dog",
            "cat",
            "fish",
            "hamster",
            "bird",
            "snake",
            "Great, I like {PET} too!",  # ChatGptTranslator uses use_codebook=False, so variables are not encoded
        ],
        source_lang="en",
        target_lang="fr",
        file_path="experiment.py",
    )

    expected_translations = [
        "Bonjour, bienvenue dans mon expérience !",
        "Quel est votre nom ?",
        "Bonjour, {NAME} !",
        "Quel est votre animal préféré?",
        "chien",
        "chat",
        "poisson",
        "hamster",
        "oiseau",
        "serpent",
        "Super, j'aime {PET} aussi!",
    ]

    for i, translation in enumerate(translations):
        expected_translation = expected_translations[i]
        assert preprocess_translation(translation) == preprocess_translation(
            expected_translation
        ), (
            f"Translation {i} does not match expected translation. Expected: {expected_translation}, Got: {translation}"
        )


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
    translator = GoogleTranslator()

    # TODO - raise a more specific exception here
    with pytest.raises(Exception):
        translator.translate(
            texts=["Hello"], source_lang="en", target_lang="invalid_code"
        )

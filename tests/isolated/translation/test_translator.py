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

import json
import os
from types import SimpleNamespace

import pytest

from psynet.experiment import import_local_experiment
from psynet.pytest_psynet import local_only, path_to_test_experiment
from psynet.translation.translators import (
    ChatGptTranslator,
    GoogleTranslator,
    TranslationContext,
)

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


@pytest.mark.parametrize(
    "temperature, expected", [(None, {}), ("0", {"temperature": 0.0})]
)
def test_chat_gpt_sends_temperature_only_when_configured(
    monkeypatch, temperature, expected
):
    """Models such as gpt-6-luna reject a temperature, so it is optional."""
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        message = SimpleNamespace(content=json.dumps({"1": "Bonjour"}), refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")]
        )

    config = {"openai_api_key": "key", "openai_default_model": "gpt-6-luna"}
    if temperature is not None:
        config["openai_default_temperature"] = temperature
    monkeypatch.setattr("psynet.translation.translators.get_config", lambda: config)
    monkeypatch.setattr(
        "openai.OpenAI",
        lambda api_key: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )

    result = ChatGptTranslator().translate(["Hello"], "en", "fr")

    assert result == ["Bonjour"]
    assert {k: v for k, v in requests[0].items() if k == "temperature"} == expected


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
    translator = GoogleTranslator()

    # TODO - raise a more specific exception here
    with pytest.raises(Exception):
        translator.translate(
            texts=["Hello"], source_lang="en", target_lang="invalid_code"
        )

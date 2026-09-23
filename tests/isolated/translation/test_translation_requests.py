"""Tests for how many translation requests are made, and how large they get."""

import pytest

from psynet.translation.translators import (
    MAX_SOURCE_CONTEXT_CHARS,
    ChatGptTranslator,
    InvalidTranslationError,
    Translator,
)


class CountingTranslator(Translator):
    """A translator that records its calls instead of contacting a provider."""

    use_codebook = False

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def _translate_texts(self, texts, source_lang, target_lang, file_path=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise InvalidTranslationError("provider error")
        return [f"{text}-{target_lang}" for text in texts]


def test_successful_translation_makes_one_request():
    translator = CountingTranslator()

    result = translator.translate(texts=["Hello"], source_lang="en", target_lang="fr")

    assert result == ["Hello-fr"]
    assert translator.calls == 1


def test_failed_translation_is_retried_then_succeeds():
    translator = CountingTranslator(failures=2)

    result = translator.translate(texts=["Hello"], source_lang="en", target_lang="fr")

    assert result == ["Hello-fr"]
    assert translator.calls == 3


def test_translation_gives_up_after_retries():
    translator = CountingTranslator(failures=3)

    with pytest.raises(InvalidTranslationError):
        translator.translate(texts=["Hello"], source_lang="en", target_lang="fr")

    assert translator.calls == 3


def test_system_prompt_quotes_a_small_source_file(tmp_path):
    source = tmp_path / "experiment.py"
    source.write_text('_("Hello")\n', encoding="utf-8")

    prompt = ChatGptTranslator().get_system_prompt(
        ["Hello"], "English", "French", file_path=str(source)
    )

    assert str(source) in prompt
    assert '_("Hello")' in prompt


def test_system_prompt_omits_an_oversized_source_file(tmp_path):
    source = tmp_path / "recruiters.py"
    body = "# padding\n" * MAX_SOURCE_CONTEXT_CHARS
    source.write_text(body, encoding="utf-8")

    prompt = ChatGptTranslator().get_system_prompt(
        ["Hello"], "English", "French", file_path=str(source)
    )

    assert str(source) in prompt
    assert "# padding" not in prompt
    assert len(prompt) < MAX_SOURCE_CONTEXT_CHARS

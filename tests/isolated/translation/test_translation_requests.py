"""Tests for what is sent to the translator, how often, and in which batches."""

import polib
import pytest

from psynet.translation.translate import (
    MAX_BATCH_SIZE,
    batch_untranslated,
    reuse_translations,
)
from psynet.translation.translators import (
    MAX_SOURCE_CONTEXT_CHARS,
    ChatGptTranslator,
    InvalidTranslationError,
    TranslationContext,
    Translator,
    _response_format,
)


class CountingTranslator(Translator):
    """A translator that records its calls instead of contacting a provider."""

    use_codebook = False

    def __init__(self, failures=0):
        self.failures = failures
        self.calls = 0

    def _translate_texts(self, texts, source_lang, target_lang, context=None):
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
        "English", "French", TranslationContext(file_path=str(source))
    )

    assert str(source) in prompt
    assert '_("Hello")' in prompt


def test_system_prompt_quotes_only_nearby_lines_of_a_large_file(tmp_path):
    source = tmp_path / "recruiters.py"
    padding = ["# padding"] * MAX_SOURCE_CONTEXT_CHARS
    padding[999] = '_p("lucid", "Save")'
    source.write_text("\n".join(padding), encoding="utf-8")

    prompt = ChatGptTranslator().get_system_prompt(
        "English",
        "French",
        TranslationContext(file_path=str(source), line_numbers=[1000]),
    )

    assert '_p("lucid", "Save")' in prompt
    assert "Lines 992-1008:" in prompt
    assert len(prompt) < 2_000


def test_system_prompt_includes_existing_translations():
    prompt = ChatGptTranslator().get_system_prompt(
        "English", "French", TranslationContext(examples=[("I agree", "J'accepte")])
    )

    assert "J'accepte" in prompt


def test_response_format_requires_exactly_one_translation_per_text():
    schema = _response_format(["1", "2"])["json_schema"]["schema"]

    assert schema["required"] == ["1", "2"]
    assert schema["additionalProperties"] is False


def _entry(msgid, file, line, msgctxt=None, msgstr=""):
    return polib.POEntry(
        msgid=msgid, msgctxt=msgctxt, msgstr=msgstr, occurrences=[(file, str(line))]
    )


class RecordingTranslator(Translator):
    def translate(self, texts, source_lang, target_lang, context=None):
        self.context = context
        return [f"{text}-{target_lang}" for text in texts]


def test_only_new_messages_are_sent_in_batches_per_file():
    old_po = polib.POFile()
    old_po.append(_entry("Back", "consent.html", "", "navigation", "Retour"))
    old_po.append(_entry("I agree", "consent.html", "", "consent", "J'accepte"))

    po = polib.POFile()
    po.append(_entry("Back", "consent.html", 1, "navigation"))
    po.append(_entry("I agree", "consent.html", 2, "consent"))
    po.append(_entry("I disagree", "consent.html", 3, "consent"))
    po.append(_entry("Save", "recruiters.py", 5, "lucid"))
    for i in range(MAX_BATCH_SIZE + 1):
        po.append(_entry(f"Country {i}", "countries.py", i + 1, "country_name"))

    assert reuse_translations(po, old_po) == 2
    consent, recruiters, *countries = batch_untranslated(po)

    assert [e.msgid for e in consent.entries] == ["I disagree"]
    assert consent.examples[0] == ("I agree", "J'accepte")
    assert recruiters.file == "recruiters.py"
    assert [len(b.entries) for b in countries] == [MAX_BATCH_SIZE, 1]

    translator = RecordingTranslator()
    consent.translate("en", "fr", False, translator)
    assert translator.context.labels == ["consent"]
    assert consent.entries[0].msgstr == "I disagree-fr"
    assert consent.entries[0].fuzzy

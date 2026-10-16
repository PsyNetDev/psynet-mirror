"""Tests for what is sent to the translator, how often, and in which batches."""

import json
import sys
from types import SimpleNamespace

import polib
import pytest

from psynet.translation import translators
from psynet.translation.translate import (
    MAX_BATCH_SIZE,
    batch_untranslated,
    reuse_translations,
    translate_po,
)
from psynet.translation.translators import (
    MAX_SOURCE_CONTEXT_CHARS,
    ChatGptTranslator,
    InvalidTranslationError,
    TranslationContext,
    TranslationError,
    Translator,
    _response_format,
    _script_name,
    _validate_translations,
    source_context_for_prompt,
)


class CountingTranslator(Translator):
    """A translator that records its calls instead of contacting a provider."""

    def __init__(self, failures=0, drop_variables=0):
        self.failures = failures
        self.drop_variables = drop_variables
        self.calls = 0
        self.attempts = []

    def _translate_texts(
        self, texts, source_lang, target_lang, context=None, attempt=0
    ):
        self.calls += 1
        self.attempts.append(attempt)
        if self.calls <= self.failures:
            raise InvalidTranslationError("provider error")
        if self.calls <= self.drop_variables:
            return [text.replace("{NAME}", "") for text in texts]
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


def test_translation_that_drops_a_variable_is_retried():
    translator = CountingTranslator(drop_variables=1)

    result = translator.translate(
        texts=["Hello {NAME}"], source_lang="en", target_lang="fr"
    )

    assert result == ["Hello {NAME}-fr"]
    assert translator.attempts == [0, 1]


@pytest.mark.parametrize(
    "text, translation, valid",
    [
        ("<i>audiovisual</i> recordings", "<i>audiovisuelle</i> Aufnahmen", True),
        ("<I>Agreement</I> of the <I>Data</I>", "<I>Datenvereinbarung</I>", True),
        ("<i>audiovisual</i> recordings", "audiovisuelle Aufnahmen", False),
        ("<i>audiovisual</i> recordings", "<em>audiovisuelle</em> Aufnahmen", False),
        ("Hello", " ", False),
    ],
)
def test_validation_rejects_lost_html_tags_and_empty_translations(
    text, translation, valid
):
    try:
        _validate_translations([text], [translation], "de")
    except InvalidTranslationError:
        assert not valid
    else:
        assert valid


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


def test_oversized_source_blocks_are_cut_not_dropped(tmp_path):
    source = tmp_path / "recruiters.py"
    lines = ["#" * 2_000] * 2_000
    lines[999] = '_p("lucid", "Save")'
    lines[1_499] = '_p("lucid", "Cancel")'
    source.write_text("\n".join(lines), encoding="utf-8")

    context = source_context_for_prompt(str(source), [1_000, 1_500])

    assert '_p("lucid", "Save")' in context
    assert '_p("lucid", "Cancel")' in context
    assert len(context) <= MAX_SOURCE_CONTEXT_CHARS + 2


def test_system_prompt_asks_to_translate_ui_labels():
    prompt = ChatGptTranslator().get_system_prompt("English", "Japanese")

    assert "Translate button and link labels too" in prompt


def test_system_prompt_includes_existing_translations():
    prompt = ChatGptTranslator().get_system_prompt(
        "English", "French", TranslationContext(examples=[("I agree", "J'accepte")])
    )

    assert "J'accepte" in prompt


def test_system_prompt_names_the_locale_script():
    assert _script_name("sat") == "Ol Chiki"
    assert _script_name("od") == "Odia"
    assert _script_name("sr") == "Latin"

    prompt = ChatGptTranslator().get_system_prompt(
        "English", "Santali", script=_script_name("sat")
    )

    assert "Ol Chiki script" in prompt


def test_temperature_is_dropped_for_models_that_reject_it(monkeypatch):
    class BadRequestError(Exception):
        def __init__(self, param):
            self.param = param

    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if "temperature" in kwargs:
            raise BadRequestError(param="temperature")
        message = SimpleNamespace(content=json.dumps({"1": "Bonjour"}), refusal=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=lambda api_key: client, BadRequestError=BadRequestError),
    )
    monkeypatch.setattr(translators, "_MODELS_WITHOUT_TEMPERATURE", set())
    config = {
        "openai_api_key": "key",
        "openai_default_model": "gpt-6-luna",
        "openai_default_temperature": "0",
    }
    monkeypatch.setattr(translators, "get_config", lambda: config)

    for _ in range(2):
        assert ChatGptTranslator().translate(["Hello"], "en", "fr") == ["Bonjour"]

    assert ["temperature" in request for request in requests] == [True, False, False]


def test_response_format_requires_exactly_one_translation_per_text():
    schema = _response_format(["1", "2"])["json_schema"]["schema"]

    assert schema["required"] == ["1", "2"]
    assert schema["additionalProperties"] is False


def _entry(msgid, file, line, msgctxt=None, msgstr="", fuzzy=False):
    return polib.POEntry(
        msgid=msgid,
        msgctxt=msgctxt,
        msgstr=msgstr,
        occurrences=[(file, str(line))],
        flags=["fuzzy"] if fuzzy else [],
    )


def test_finished_batches_are_saved_when_a_later_batch_fails(tmp_path):
    class FailingTranslator(Translator):
        def translate(self, texts, source_lang, target_lang, context=None):
            if context.file_path == "b.py":
                raise TranslationError("provider outage")
            return [f"{text}-{target_lang}" for text in texts]

    pot = polib.POFile()
    pot.append(_entry("Hello", "a.py", 1))
    pot.append(_entry("Goodbye", "b.py", 1))
    pot_path = tmp_path / "experiment.pot"
    pot.save(str(pot_path))
    po_path = tmp_path / "experiment.po"

    with pytest.raises(TranslationError):
        translate_po(
            str(pot_path), str(po_path), "en", "fr", False, FailingTranslator()
        )

    saved = {entry.msgid: entry.msgstr for entry in polib.pofile(str(po_path))}
    assert saved == {"Hello": "Hello-fr", "Goodbye": ""}


class RecordingTranslator(Translator):
    def translate(self, texts, source_lang, target_lang, context=None):
        self.context = context
        return [f"{text}-{target_lang}" for text in texts]


def test_only_new_messages_are_sent_in_batches_per_file():
    old_po = polib.POFile()
    old_po.append(_entry("Back", "consent.html", "", "navigation", "Retour"))
    old_po.append(_entry("I agree", "consent.html", "", "consent", "J'accepte"))
    old_po.append(_entry("Leave", "consent.html", "", "consent", "Leave"))
    old_po.append(_entry("Stay", "consent.html", "", "consent", "Stay", fuzzy=True))

    po = polib.POFile()
    po.append(_entry("Back", "consent.html", 1, "navigation"))
    po.append(_entry("I agree", "consent.html", 2, "consent"))
    po.append(_entry("Leave", "consent.html", 3, "consent"))
    po.append(_entry("Stay", "consent.html", 4, "consent"))
    po.append(_entry("I disagree", "consent.html", 5, "consent"))
    po.append(_entry("Save", "recruiters.py", 6, "lucid"))
    for i in range(MAX_BATCH_SIZE + 1):
        po.append(_entry(f"Country {i}", "countries.py", i + 1, "country_name"))

    # The reviewed English copy is kept; the fuzzy one is translated again.
    assert reuse_translations(po, old_po) == 3
    consent, recruiters, *countries = batch_untranslated(po)

    assert [e.msgid for e in consent.entries] == ["Stay", "I disagree"]
    assert consent.examples[0] == ("I agree", "J'accepte")
    assert ("Leave", "Leave") not in consent.examples
    assert recruiters.file == "recruiters.py"
    assert [len(b.entries) for b in countries] == [MAX_BATCH_SIZE, 1]

    translator = RecordingTranslator()
    consent.translate("en", "fr", False, translator)
    assert translator.context.labels == ["consent", "consent"]
    assert consent.entries[1].msgstr == "I disagree-fr"
    assert consent.entries[1].fuzzy

    assert countries[1].examples == []
    countries[0].translate("en", "fr", False, translator)
    assert ("Country 0", "Country 0-fr") in countries[1].examples

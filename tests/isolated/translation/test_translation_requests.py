"""Tests for what is sent to the translator, how often, and in which batches."""

import json
import sys
from types import SimpleNamespace

import polib
import pytest

from psynet.translation import translators
from psynet.translation.translate import (
    MAX_BATCH_SIZE,
    _save_po,
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
    get_translator_from_name,
    source_context_for_prompt,
)


class CountingTranslator(Translator):
    """A translator that records its calls instead of contacting a provider."""

    use_codebook = False

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


def test_custom_translators_keep_automatic_placeholder_protection():
    class CustomTranslator(Translator):
        def _translate_texts(
            self, texts, source_lang, target_lang, context=None, attempt=0
        ):
            self.received = texts
            return [text.replace("Hello", "Bonjour") for text in texts]

    translator = CustomTranslator()

    result = translator.translate(
        texts=['<a title="x > y">Hello {NAME}</a>'],
        source_lang="en",
        target_lang="fr",
    )

    assert translator.received == ["■0■Hello ■1■■2■"]
    assert result == ['<a title="x > y">Bonjour {NAME}</a>']


@pytest.mark.parametrize(
    "text, translation, valid",
    [
        ("<i>audiovisual</i> recordings", "<i>audiovisuelle</i> Aufnahmen", True),
        ("<I>Agreement</I> of the <I>Data</I>", "<I>Datenvereinbarung</I>", True),
        ("<i>audiovisual</i> recordings", "audiovisuelle Aufnahmen", False),
        ("<i>audiovisual</i> recordings", "<em>audiovisuelle</em> Aufnahmen", False),
        (
            '<a href="/consent">Consent</a>',
            '<a href="/withdraw">Einwilligung</a>',
            False,
        ),
        (
            '<a title="x > y" href="/consent">Consent</a>',
            '<a title="x > y" href="/withdraw">Einwilligung</a>',
            False,
        ),
        ("<i><b>Important</b></i>", "<i><b>Wichtig</i></b>", False),
        ("<i>One</i>", "<i>Eins</i><i>Zwei</i>", False),
        ("1 < x > 0", "1 < x > 0", True),
        ("Save <filename>", "Enregistrer <filename>", True),
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


def test_nearby_source_lines_are_not_lost_when_their_context_windows_overlap(
    tmp_path,
):
    source = tmp_path / "recruiters.py"
    lines = ["#" * 2_000] * 2_000
    lines[999] = '_p("lucid", "Save")'
    lines[1_015] = '_p("lucid", "Cancel")'
    source.write_text("\n".join(lines), encoding="utf-8")

    context = source_context_for_prompt(str(source), [1_000, 1_016])

    assert '_p("lucid", "Save")' in context
    assert '_p("lucid", "Cancel")' in context
    assert len(context) <= MAX_SOURCE_CONTEXT_CHARS
    assert source_context_for_prompt(str(source), [-1, 0, 2_001]) == ""


def test_source_context_crops_around_text_on_an_oversized_target_line(tmp_path):
    source = tmp_path / "recruiters.py"
    lines = ["# padding"] * 2_000
    lines[998] = 'unrelated = "Save"'
    lines[999] = "#" * 30_000 + 'TARGET = _p("lucid", "Save")'
    source.write_text("\n".join(lines), encoding="utf-8")

    context = source_context_for_prompt(str(source), [1_000], ["Save"])

    assert 'TARGET = _p("lucid", "Save")' in context
    assert len(context) <= MAX_SOURCE_CONTEXT_CHARS


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


def _fake_chat_gpt(monkeypatch, temperature, reject_temperature=False, replies=()):
    """Route ChatGptTranslator to a fake ``openai`` module and return its requests.

    The fake answers with ``replies`` in turn, then with "Bonjour".
    """

    class BadRequestError(Exception):
        def __init__(self, param):
            self.param = param

    requests = []
    replies = list(replies)

    def create(**kwargs):
        requests.append(kwargs)
        if reject_temperature and "temperature" in kwargs:
            raise BadRequestError(param="temperature")
        reply = replies.pop(0) if replies else "Bonjour"
        message = SimpleNamespace(content=json.dumps({"1": reply}), refusal=None)
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
    config = {"openai_api_key": "key", "openai_default_model": "gpt-6-luna"}
    if temperature is not None:
        config["openai_default_temperature"] = temperature
    monkeypatch.setattr(translators, "get_config", lambda: config)
    return requests


@pytest.mark.parametrize(
    "temperature, expected", [(None, ["absent", "absent"]), ("0", [0.0, 0.7])]
)
def test_temperature_is_sent_only_when_configured(monkeypatch, temperature, expected):
    """The first reply is empty, so the request is retried."""
    requests = _fake_chat_gpt(monkeypatch, temperature, replies=[""])

    assert ChatGptTranslator().translate(["Hello"], "en", "fr") == ["Bonjour"]

    assert [request.get("temperature", "absent") for request in requests] == expected


def test_temperature_is_dropped_for_models_that_reject_it(monkeypatch, capsys):
    requests = _fake_chat_gpt(monkeypatch, "0", reject_temperature=True)

    for _ in range(2):
        assert ChatGptTranslator().translate(["Hello"], "en", "fr") == ["Bonjour"]

    assert ["temperature" in request for request in requests] == [True, False, False]
    assert "openai_default_temperature is ignored" in capsys.readouterr().out


@pytest.mark.parametrize("temperature", ["-0.1", "2.1", "nan", "inf", "not-a-number"])
def test_invalid_temperature_is_rejected(monkeypatch, capsys, temperature):
    requests = _fake_chat_gpt(monkeypatch, temperature)

    with pytest.raises(
        ValueError, match="openai_default_temperature must be a number from 0 to 2"
    ):
        ChatGptTranslator().translate(["Hello"], "en", "fr")

    assert requests == []
    assert "Retrying" not in capsys.readouterr().out


@pytest.mark.parametrize("model", ["gpt-4o", "chatgpt-4o-latest", "ft:gpt-4o-custom"])
def test_gpt_4o_request_stays_within_its_completion_token_limit(monkeypatch, model):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
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
        SimpleNamespace(
            OpenAI=lambda api_key: client,
            BadRequestError=type("BadRequestError", (Exception,), {}),
        ),
    )
    monkeypatch.setattr(
        translators,
        "get_config",
        lambda: {
            "openai_api_key": "key",
            "openai_default_model": model,
            "openai_default_temperature": "0",
        },
    )

    ChatGptTranslator().translate(["a" * 5_000], "en", "fr")

    assert requests[0]["max_completion_tokens"] <= 16_000


def test_removed_google_translator_has_a_clear_error():
    with pytest.raises(ValueError, match="no longer supports Google Translate"):
        get_translator_from_name("google_translate")


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


def test_saving_a_catalog_is_atomic(tmp_path, monkeypatch):
    po_path = tmp_path / "experiment.po"
    po_path.write_text("original catalog", encoding="utf-8")
    po = polib.POFile()
    po.append(_entry("Hello", "a.py", 1, msgstr="Bonjour"))

    def fail_during_save(self, path):
        with open(path, "w", encoding="utf-8") as file:
            file.write("partial catalog")
        raise OSError("disk full")

    monkeypatch.setattr(polib.POFile, "save", fail_during_save)

    with pytest.raises(OSError, match="disk full"):
        _save_po(po, str(po_path))

    assert po_path.read_text(encoding="utf-8") == "original catalog"


def test_saving_a_catalog_preserves_symlinks(tmp_path):
    target_path = tmp_path / "catalog-target.po"
    target_path.write_text("original catalog", encoding="utf-8")
    po_path = tmp_path / "experiment.po"
    po_path.symlink_to(target_path)
    po = polib.POFile()
    po.append(_entry("Hello", "a.py", 1, msgstr="Bonjour"))

    _save_po(po, str(po_path))

    assert po_path.is_symlink()
    assert polib.pofile(str(target_path))[0].msgstr == "Bonjour"


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

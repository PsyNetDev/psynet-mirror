import json
import os.path
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional, Sequence

from psynet.utils import get_config, get_descendent_class_by_name, get_language_dict

from .check import extract_variable_names

# Source files are quoted into the translation prompt for context. Large modules
# (``psynet/recruiters.py`` is ~150 kB) would otherwise dominate every request
# for that file, so beyond this size only the lines around each text are quoted.
MAX_SOURCE_CONTEXT_CHARS = 20_000
SOURCE_SNIPPET_RADIUS_LINES = 8
DEFAULT_MAX_COMPLETION_TOKENS = 32_000
GPT_4O_MAX_COMPLETION_TOKENS = 16_000

_PROTECTED_TEXT_PATTERN = re.compile(
    r"""\{\{[^}]+\}\}|\{[^}]+\}|<(?:"[^"]*"|'[^']*'|[^'">])*>"""
)
_VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HTML_TAGS = _VOID_HTML_TAGS | set(
    """
    a abbr address article aside audio b bdi bdo blockquote body button canvas
    caption cite code colgroup data datalist dd del details dfn dialog div dl dt
    em fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header
    hgroup html i iframe ins kbd label legend li main map mark math menu meter
    nav noscript object ol optgroup option output p picture pre progress q rp rt
    ruby s samp script search section select slot small span strong style sub
    summary sup svg table tbody td template textarea tfoot th thead time title tr
    u ul var video
    """.split()
)

# PsyNet's catalogs for these locales are written in a different script than
# CLDR's default (Latin for Kurdish, Cyrillic for Serbian).
SCRIPT_OVERRIDES = {"ku": "Arabic", "sr": "Latin"}

# PsyNet locale codes that are not ISO 639 codes, which CLDR needs.
ISO_LOCALE_CODES = {"od": "or"}

# At temperature 0 a retry repeats the same reply, e.g. a model stuck repeating
# one word in a low-resource script, so retries sample more freely. Without a
# configured temperature the model's default (1 for OpenAI) already varies
# replies between retries.
RETRY_TEMPERATURE = 0.7

# Models such as gpt-6-luna reject any temperature but their own default. A
# model is added here when the API rejects its temperature, so later requests
# leave the temperature out.
_MODELS_WITHOUT_TEMPERATURE: set[str] = set()


def _encode_protected_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Replace variables and HTML tags with stable translator placeholders."""
    codebook = []

    def replace(match):
        placeholder = f"■{len(codebook)}■"
        codebook.append((match.group(0), placeholder))
        return placeholder

    return _PROTECTED_TEXT_PATTERN.sub(replace, text), codebook


def _decode_protected_text(text: str, codebook: Sequence[tuple[str, str]]) -> str:
    """Restore variables and HTML tags replaced by translator placeholders."""
    for original, placeholder in codebook:
        text = text.replace(placeholder, original)
    return text


@dataclass
class TranslationContext:
    """Where a batch of texts comes from, for translators that can use it."""

    file_path: Optional[str] = None
    labels: Sequence[Optional[str]] = ()
    """The gettext context (``msgctxt``) of each text, in the same order as the texts."""
    line_numbers: Sequence[Optional[int]] = ()
    """The source line of each text, in the same order as the texts."""
    examples: Sequence[tuple[str, str]] = ()
    """Already translated ``(source, translation)`` pairs from the same place."""
    source_texts: Sequence[str] = ()
    """The source texts, used to keep their occurrences when source code is cropped."""


class Translator:
    nickname = None
    # Kept for compatibility with custom translators. ChatGPT receives the raw
    # markup because its prompt and response validation handle it directly.
    use_codebook = True

    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
        n_retries: int = 3,
    ):
        """Translate a list of texts from source language to target language.

        Parameters
        ----------
        texts : List[str]
            The texts to translate
        source_lang : str
            The source language code
        target_lang : str
            The target language code
        context : TranslationContext, optional
            Where the texts come from, by default None
        n_retries : int, optional
            The number of times to retry the translation request, by default 3

        Returns
        -------
        List[str]
            The translated texts
        """
        if self.use_codebook:
            encoded = [_encode_protected_text(text) for text in texts]
            request_texts = [text for text, _ in encoded]
            codebooks = [codebook for _, codebook in encoded]
        else:
            request_texts = texts
            codebooks = None

        for i in range(n_retries):
            try:
                translated_texts = self._translate_texts(
                    request_texts, source_lang, target_lang, context, attempt=i
                )
                if len(translated_texts) != len(texts):
                    _validate_translations(texts, translated_texts, target_lang)
                if codebooks is not None:
                    translated_texts = [
                        _decode_protected_text(text, codebook)
                        for text, codebook in zip(translated_texts, codebooks)
                    ]
                _validate_translations(texts, translated_texts, target_lang)
                break
            except Exception as e:
                if i == n_retries - 1:
                    raise e
                else:
                    print(f"Retrying translation ({i + 1}/{n_retries})... {e}")

        return [self.fix_translation(text) for text in translated_texts]

    def _translate_texts(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
        attempt: int = 0,
    ) -> List[str]:
        """Internal method to perform the actual translation.

        This method should be implemented by subclasses.

        Parameters
        ----------
        texts : List[str]
            The texts to translate
        source_lang : str
            The source language code
        target_lang : str
            The target language code
        context : TranslationContext, optional
            Where the texts come from, by default None
        attempt : int, optional
            0 for the first request; retries count up, so translators can vary them

        Returns
        -------
        List[str]
            The translated texts
        """
        raise NotImplementedError

    @classmethod
    def fix_translation(cls, translation: str) -> str:
        """Fix any issues in the translated text.

        Parameters
        ----------
        translation : str
            The translated text to fix

        Returns
        -------
        str
            The fixed translation
        """
        return translation


HtmlTag = tuple[str, str, tuple[tuple[str, Optional[str]], ...]]


class _HtmlTagParser(HTMLParser):
    """Collect normalized HTML tags while ignoring ordinary angle brackets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[HtmlTag] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _HTML_TAGS:
            return
        kind = "self" if tag in _VOID_HTML_TAGS else "open"
        self.tags.append((kind, tag, tuple(attrs)))

    def handle_startendtag(self, tag, attrs):
        if tag not in _HTML_TAGS:
            return
        self.tags.append(("self", tag, tuple(attrs)))

    def handle_endtag(self, tag):
        if tag not in _HTML_TAGS:
            return
        self.tags.append(("close", tag, ()))


def _html_tags(text: str) -> list[HtmlTag]:
    """Return normalized ``(kind, name, attributes)`` tuples for HTML tags."""
    parser = _HtmlTagParser()
    parser.feed(text)
    parser.close()
    return parser.tags


def _html_tags_are_balanced(tags: Sequence[HtmlTag]) -> bool:
    """Return whether opening and closing tags are properly nested."""
    stack = []
    for kind, name, _ in tags:
        if kind == "open":
            stack.append(name)
        elif kind == "close":
            if not stack or stack.pop() != name:
                return False
    return not stack


def _validate_translations(texts, translated_texts, target_lang):
    """
    Reject replies that a retry might fix: wrong length, empty translations,
    altered variables, or HTML tags that were dropped or changed.

    A translation may use a tag fewer times than its source, e.g. when two
    italicized words become one compound word.
    """
    if len(translated_texts) != len(texts):
        raise InvalidTranslationError(
            f"Number of translated texts for '{target_lang}' does not match number of input texts: {len(translated_texts)} != {len(texts)}."
        )
    for text, translation in zip(texts, translated_texts):
        if text.strip() and not translation.strip():
            raise InvalidTranslationError(
                f"The '{target_lang}' translation of {text!r} is empty."
            )
        if sorted(extract_variable_names(text)) != sorted(
            extract_variable_names(translation)
        ):
            raise InvalidTranslationError(
                f"The '{target_lang}' translation of {text!r} does not keep its variables: {translation!r}"
            )
        source_tags = Counter(_html_tags(text))
        translation_tag_list = _html_tags(translation)
        translation_tags = Counter(translation_tag_list)
        same_tag_kinds = source_tags.keys() == translation_tags.keys()
        no_extra_tags = all(
            count <= source_tags[tag] for tag, count in translation_tags.items()
        )
        if (
            not same_tag_kinds
            or not no_extra_tags
            or not _html_tags_are_balanced(translation_tag_list)
        ):
            raise InvalidTranslationError(
                f"The '{target_lang}' translation of {text!r} does not keep its HTML tags: {translation!r}"
            )


class TranslationError(Exception):
    pass


class CredentialsError(TranslationError):
    pass


class InvalidTranslationError(TranslationError):
    pass


def source_context_for_prompt(
    file_path: str,
    line_numbers: Sequence[Optional[int]] = (),
    target_texts: Sequence[str] = (),
) -> str:
    """
    Return the source code to show a translator alongside texts from ``file_path``.

    Small files are returned whole, because they usually are the page the
    texts appear on. For larger files, only the lines around each text are
    returned, within the same character budget. Each block of lines gets an
    equal share of what is left of the budget, so every text gets some context;
    a block longer than its share keeps its middle, where the text is.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()
    if len(source) <= MAX_SOURCE_CONTEXT_CHARS:
        return source

    lines = source.splitlines()
    windows = []
    targets = []
    for index, line in enumerate(line_numbers):
        if line is None or not 1 <= line <= len(lines):
            continue
        target_text = target_texts[index] if index < len(target_texts) else None
        target = (line, target_text)
        if target not in targets:
            targets.append(target)
    for line, target_text in sorted(targets, key=lambda target: target[0]):
        start = max(1, line - SOURCE_SNIPPET_RADIUS_LINES)
        end = min(len(lines), line + SOURCE_SNIPPET_RADIUS_LINES)
        windows.append((line, start, end, target_text))

    blocks = []
    budget = MAX_SOURCE_CONTEXT_CHARS
    for i, (line, start, end, target_text) in enumerate(windows):
        separator_size = 2 if blocks else 0
        share = (budget - separator_size) // (len(windows) - i)
        header = f"Lines {start}-{end}:\n"
        body = "\n".join(lines[start - 1 : end])
        body_budget = max(0, share - len(header))
        if len(body) > body_budget:
            target_line_start = sum(
                len(value) + 1 for value in lines[start - 1 : line - 1]
            )
            position_in_line = lines[line - 1].find(target_text) if target_text else -1
            if position_in_line >= 0:
                target_start = target_line_start + position_in_line
                target_end = target_start + len(target_text)
            else:
                target_start = target_line_start
                target_end = target_start + len(lines[line - 1])
            if target_end - target_start >= body_budget:
                middle = (target_start + target_end) // 2
                crop_start = max(0, middle - body_budget // 2)
            else:
                crop_start = max(
                    0,
                    target_start - (body_budget - (target_end - target_start)) // 2,
                )
            crop_start = min(crop_start, len(body) - body_budget)
            body = body[crop_start : crop_start + body_budget]
        blocks.append(header + body)
        budget -= separator_size + len(blocks[-1])
    return "\n\n".join(blocks)


def _max_completion_tokens(model: str) -> int:
    """Return a safe completion-token cap for an OpenAI model."""
    if "gpt-4o" in model.lower():
        return GPT_4O_MAX_COMPLETION_TOKENS
    return DEFAULT_MAX_COMPLETION_TOKENS


def _script_name(locale: str) -> Optional[str]:
    """
    The English name of the script to translate ``locale`` into, e.g. Ol Chiki for Santali.

    Some languages are written in several scripts; without this, the model may
    switch scripts between requests. The script is CLDR's default for the locale,
    unless ``SCRIPT_OVERRIDES`` names another.
    """
    from babel import Locale
    from babel.core import get_global

    if locale in SCRIPT_OVERRIDES:
        return SCRIPT_OVERRIDES[locale]
    locale = ISO_LOCALE_CODES.get(locale, locale)
    parts = get_global("likely_subtags").get(locale, "").split("_")
    if len(parts) < 3:
        return None
    return Locale("en").scripts.get(parts[1])


def _response_format(ids: List[str]) -> dict:
    """JSON schema that makes the model return exactly one translation per id."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "translations",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {id_: {"type": "string"} for id_ in ids},
                "required": ids,
                "additionalProperties": False,
            },
        },
    }


class ChatGptTranslator(Translator):
    nickname = "chat_gpt"
    use_codebook = False

    def get_system_prompt(
        self,
        source_language: str,
        target_language: str,
        context: Optional[TranslationContext] = None,
        script: Optional[str] = None,
    ):
        prompt = (
            f"You translate user-interface text from {source_language} to {target_language}. "
            "If you see any HTML tags in the text, you should not translate them. "
            "If you see any variables in the text, you should not translate them. "
            """Variables are written in capital letters and are either surrounded by curly brackets (e.g., {VARIABLE}) or start with "%(" and end with ")s" (e.g., "%(VARIABLE)s"). """
            "You do not have to keep the original word order. "
            "Translate button and link labels too, and when a text refers to another label, "
            "use the same translation as for that label. Only leave names such as Prolific untranslated. "
            "The input is a JSON object that maps ids to items. "
            "Each item has a text to translate and may have a label naming the part of the interface the text belongs to. "
            "Return a JSON object that maps the same ids to the translations of the texts."
        )
        if script:
            prompt += f" Write the translations in the {script} script."
        if context is None:
            return prompt

        if context.examples:
            examples = [
                {"text": text, "translation": translation}
                for text, translation in context.examples
            ]
            prompt += (
                "\n\nThese texts from the same place are already translated. "
                "Keep terminology and tone consistent with them:\n"
                + json.dumps(examples, ensure_ascii=False)
            )

        if context.file_path is not None and os.path.exists(context.file_path):
            prompt += f"\n\nThe texts are taken from {context.file_path}."
            source = source_context_for_prompt(
                context.file_path, context.line_numbers, context.source_texts
            )
            if source:
                prompt += f"\n\n{source}"

        return prompt

    def _translate_texts(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
        attempt: int = 0,
    ):
        from openai import BadRequestError, OpenAI

        language_dict = get_language_dict("en")
        assert source_lang in language_dict, (
            f"Source language {source_lang} not found in known languages"
        )
        source_language = language_dict[source_lang]
        assert target_lang in language_dict, (
            f"Target language {target_lang} not found in known languages"
        )
        target_language = language_dict[target_lang]

        config = get_config()
        openai_api_key = config.get("openai_api_key", None)
        if openai_api_key is None:
            raise CredentialsError(
                "Please provide an OpenAI API key in your .dallingerconfig file under `openai_api_key`"
            )
        # Models such as gpt-6-luna reject any temperature but their own, so a
        # temperature is only sent when one is configured.
        temperature = config.get("openai_default_temperature", None)
        openai_default_model = config.get("openai_default_model")

        ids = [str(i) for i in range(1, len(texts) + 1)]
        labels = context.labels if context and context.labels else [None] * len(texts)
        items = {
            id_: {"text": text, "label": label} if label else {"text": text}
            for id_, text, label in zip(ids, texts, labels)
        }
        request = dict(
            model=openai_default_model,
            messages=[
                {
                    "role": "system",
                    "content": self.get_system_prompt(
                        source_language,
                        target_language,
                        context,
                        script=_script_name(target_lang),
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(items, ensure_ascii=False),
                },
            ],
            response_format=_response_format(ids),
            # Generous even for scripts that need several tokens per character,
            # plus room for reasoning models' hidden reasoning, which counts
            # toward the limit; still stops a repetition loop well before the
            # model's own limit.
            max_completion_tokens=min(
                _max_completion_tokens(openai_default_model),
                8_000 + 5 * sum(len(text) for text in texts),
            ),
        )
        if (
            temperature is not None
            and openai_default_model not in _MODELS_WITHOUT_TEMPERATURE
        ):
            temperature = float(temperature)
            if attempt > 0:
                temperature = max(temperature, RETRY_TEMPERATURE)
            request["temperature"] = temperature
        client = OpenAI(api_key=openai_api_key)
        try:
            response = client.chat.completions.create(**request)
        except BadRequestError as e:
            if "temperature" not in request or e.param != "temperature":
                raise
            _MODELS_WITHOUT_TEMPERATURE.add(openai_default_model)
            print(
                f"{openai_default_model} rejects temperature {request['temperature']}, "
                "so openai_default_temperature is ignored for it."
            )
            del request["temperature"]
            response = client.chat.completions.create(**request)
        choice = response.choices[0]
        if choice.message.refusal:
            raise InvalidTranslationError(
                f"ChatGPT refused to translate: {choice.message.refusal}"
            )
        if choice.finish_reason == "length":
            raise InvalidTranslationError("ChatGPT's response was cut off.")
        try:
            translations = json.loads(choice.message.content)
            return [translations[id_] for id_ in ids]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise InvalidTranslationError(
                f"ChatGPT did not return one translation per text: {choice.message.content}"
            ) from e


class DefaultTranslator(Translator):
    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
    ):
        config = get_config()
        translator_class = _translator_class(config.get("default_translator"))
        return translator_class().translate(texts, source_lang, target_lang, context)


class NullTranslator(Translator):
    nickname = "null"

    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
    ):
        return texts


def _translator_class(name: str) -> type[Translator]:
    """The translator class with this class name or nickname."""
    if name == "google_translate":
        raise ValueError(
            "PsyNet no longer supports Google Translate. Remove "
            "`default_translator = google_translate` from your config to use "
            "ChatGPT (`chat_gpt`), the default."
        )
    return get_descendent_class_by_name(Translator, name)


def get_translator_from_name(name: Optional[str] = None) -> Translator:
    if name is None:
        return DefaultTranslator()
    return _translator_class(name)()

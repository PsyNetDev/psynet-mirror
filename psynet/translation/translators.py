import json
import os.path
from dataclasses import dataclass
from typing import List, Optional, Sequence

from psynet.utils import get_config, get_descendent_class_by_name, get_language_dict

# Source files are quoted into the translation prompt for context. Large modules
# (``psynet/recruiters.py`` is ~150 kB) would otherwise dominate every request
# for that file, so beyond this size only the lines around each text are quoted.
MAX_SOURCE_CONTEXT_CHARS = 20_000
SOURCE_SNIPPET_RADIUS_LINES = 8


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


class Translator:
    nickname = None
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
            codebooks = [self._get_codebook(text) for text in texts]
            encoded_texts = [
                self._encode(text, codebook) for text, codebook in zip(texts, codebooks)
            ]
            translated_encoded_texts = self._translate_texts(
                encoded_texts, source_lang, target_lang, context
            )
            translated_texts = [
                self._decode(text, codebook)
                for text, codebook in zip(translated_encoded_texts, codebooks)
            ]
        else:
            for i in range(n_retries):
                try:
                    translated_texts = self._translate_texts(
                        texts, source_lang, target_lang, context
                    )
                    if len(translated_texts) != len(texts):
                        raise InvalidTranslationError(
                            f"Number of translated texts for '{target_lang}' does not match number of input texts: {len(translated_texts)} != {len(texts)}."
                        )
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

        Returns
        -------
        List[str]
            The translated texts
        """
        raise NotImplementedError

    @classmethod
    def _get_codebook(cls, text: str) -> List[tuple[str, str]]:
        """Get codebook mapping text patterns to encoded placeholders.

        Parameters
        ----------
        text : str
            Input text to analyze for patterns that need encoding

        Returns
        -------
        list of tuple
            List of (original_text, encoded_placeholder) pairs
        """
        import re

        def process_pattern(
            pattern: str, text: str, codebook: list, counter: int
        ) -> tuple[str, int]:
            """Process a regex pattern and update codebook.

            Returns
            -------
            tuple[str, int]
                Updated text and counter
            """
            matches = list(re.finditer(pattern, text))
            for match in matches:
                original = match.group(0)
                encoded = f"■{counter}■"
                codebook.append((original, encoded))
                text = text.replace(original, encoded)
                counter += 1
            return text, counter

        patterns = [
            r"\{\{[^}]+\}\}",  # Jinja variables
            r"\{[^}]+\}",  # Simple variables
            r"<[^/>][^>]*>",  # Opening HTML tags with optional attributes
            r"</[^>]+>",  # Closing HTML tags
        ]

        codebook = []
        counter = 0
        working_text = text

        for pattern in patterns:
            working_text, counter = process_pattern(
                pattern, working_text, codebook, counter
            )

        return codebook

    @classmethod
    def _encode(cls, text: str, codebook: List[tuple[str, str]]) -> str:
        """Encode text by replacing patterns with placeholders.

        Parameters
        ----------
        text : str
            Text to encode
        codebook : list of tuple
            List of (original_text, encoded_placeholder) pairs

        Returns
        -------
        str
            Encoded text with patterns replaced by placeholders
        """
        result = text
        for original, encoded in codebook:
            result = result.replace(original, encoded)
        return result

    @classmethod
    def _decode(cls, text: str, codebook: List[tuple[str, str]]) -> str:
        """Decode text by replacing placeholders with original patterns.

        Parameters
        ----------
        text : str
            Text to decode
        codebook : list of tuple
            List of (original_text, encoded_placeholder) pairs

        Returns
        -------
        str
            Decoded text with placeholders replaced by original patterns
        """
        result = text
        for original, encoded in codebook:
            result = result.replace(encoded, original)
        return result

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


class TranslationError(Exception):
    pass


class CredentialsError(TranslationError):
    pass


class UnsupportedLanguageError(TranslationError):
    pass


class InvalidTranslationError(TranslationError):
    pass


class GoogleTranslator(Translator):
    nickname = "google_translate"

    def _translate_texts(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
    ):
        from google.cloud import translate_v3

        config = get_config()
        google_translate_json_path = config.get("google_translate_json_path", None)
        if google_translate_json_path is None:
            raise CredentialsError(
                "Please provide a Google Cloud Translate API key in your .dallingerconfig file under `google_translate_json_path`"
            )

        google_translate_json_path = os.path.expanduser(google_translate_json_path)

        with open(google_translate_json_path, "r") as f:
            auth_dict = json.load(f)

        client = translate_v3.TranslationServiceClient.from_service_account_json(
            google_translate_json_path
        )
        parent = f"projects/{auth_dict['project_id']}/locations/global"
        try:
            response = client.translate_text(
                contents=texts,
                target_language_code=target_lang,
                parent=parent,
                mime_type="text/html",
                source_language_code=source_lang,
            )
        except Exception as e:
            if e.args[0] == "Target language is invalid.":
                raise UnsupportedLanguageError(f"Invalid language code: {target_lang}")
            else:
                raise e

        # Display the translation for each input text provided
        return [translation.translated_text for translation in response.translations]


def source_context_for_prompt(
    file_path: str, line_numbers: Sequence[Optional[int]] = ()
) -> str:
    """
    Return the source code to show a translator alongside texts from ``file_path``.

    Small files are returned whole, because they usually are the page the
    texts appear on. For larger files, only the lines around each text are
    returned, within the same character budget.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()
    if len(source) <= MAX_SOURCE_CONTEXT_CHARS:
        return source

    lines = source.splitlines()
    windows = []
    for line in sorted({n for n in line_numbers if n}):
        start = max(1, line - SOURCE_SNIPPET_RADIUS_LINES)
        end = min(len(lines), line + SOURCE_SNIPPET_RADIUS_LINES)
        if windows and start <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))

    blocks = []
    budget = MAX_SOURCE_CONTEXT_CHARS
    for start, end in windows:
        block = f"Lines {start}-{end}:\n" + "\n".join(lines[start - 1 : end])
        if len(block) > budget:
            break
        blocks.append(block)
        budget -= len(block)
    return "\n\n".join(blocks)


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
    ):
        prompt = (
            f"You translate user-interface text from {source_language} to {target_language}. "
            "If you see any HTML tags in the text, you should not translate them. "
            "If you see any variables in the text, you should not translate them. "
            """Variables are written in capital letters and are either surrounded by curly brackets (e.g., {VARIABLE}) or start with "%(" and end with ")s" (e.g., "%(VARIABLE)s"). """
            "You do not have to keep the original word order. "
            "The input is a JSON object that maps ids to items. "
            "Each item has a text to translate and may have a label naming the part of the interface the text belongs to. "
            "Return a JSON object that maps the same ids to the translations of the texts."
        )
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
            source = source_context_for_prompt(context.file_path, context.line_numbers)
            if source:
                prompt += f"\n\n{source}"

        return prompt

    def _translate_texts(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
    ):
        from openai import OpenAI

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
        temperature = float(config.get("openai_default_temperature"))
        openai_default_model = config.get("openai_default_model")

        ids = [str(i) for i in range(1, len(texts) + 1)]
        labels = context.labels if context and context.labels else [None] * len(texts)
        items = {
            id_: {"text": text, "label": label} if label else {"text": text}
            for id_, text, label in zip(ids, texts, labels)
        }
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=openai_default_model,
            messages=[
                {
                    "role": "system",
                    "content": self.get_system_prompt(
                        source_language, target_language, context
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(items, ensure_ascii=False),
                },
            ],
            temperature=temperature,
            response_format=_response_format(ids),
        )
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
        default_translator = config.get("default_translator")
        translator_class = get_descendent_class_by_name(Translator, default_translator)
        return translator_class().translate(texts, source_lang, target_lang, context)


class NullTranslator(Translator):
    nickname = "null"
    use_codebook = False

    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        context: Optional[TranslationContext] = None,
    ):
        return texts


def get_translator_from_name(name: Optional[str] = None) -> Translator:
    if name is None:
        return DefaultTranslator()
    translator_class = get_descendent_class_by_name(Translator, name)
    return translator_class()

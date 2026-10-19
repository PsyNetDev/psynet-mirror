import json
import os.path
from typing import List, Optional

import tenacity

from psynet.utils import get_config, get_descendent_class_by_name, get_language_dict


class Translator:
    nickname = None
    use_codebook = True

    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        file_path: str = None,
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
        file_path : str, optional
            The path to the file being translated, by default None
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
                encoded_texts, source_lang, target_lang, file_path
            )
            translated_texts = [
                self._decode(text, codebook)
                for text, codebook in zip(translated_encoded_texts, codebooks)
            ]
        else:
            for i in range(n_retries):
                try:
                    translated_texts = self._translate_texts(
                        texts, source_lang, target_lang, file_path
                    )
                    if len(translated_texts) != len(texts):
                        raise InvalidTranslationError(
                            f"Number of translated texts for '{target_lang}' does not match number of input texts: {len(translated_texts)} != {len(texts)}."
                        )
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
        file_path: str = None,
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
        file_path : str, optional
            The path to the file being translated, by default None

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
        file_path: str = None,
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


class ChatGptTranslator(Translator):
    nickname = "chat_gpt"
    use_codebook = False

    def get_system_prompt(
        self,
        texts: List[str],
        source_language: str,
        target_language: str,
        file_path: str = None,
    ):
        prompt = f"You are a helpful assistant that translates {source_language} to {target_language}."
        prompt += (
            "If you see any HTML tags in the text, you should not translate them. "
            "If you see any variables in the text, you should not translate them. "
            """Variables are written in capital letters and are either surrounded by curly brackets (e.g., {VARIABLE}) or start with "%(" and end with ")s" (e.g., "%(VARIABLE)s"). """
            "You do not have to keep the original word order. "
            "The translation is specified as a list using JSON format. "
            """For example, ["Hello, {NAME}!", "My name is {NAME}"] would be converted to ["Bonjour, {NAME}!", "Je m'appelle {NAME}"] when translating to French. """
            "Your output should be pure JSON with no comments, formatting directives, or other modifiers"
        )

        if file_path is not None and os.path.exists(file_path):
            with open(file_path, "r") as f:
                prompt += (
                    f"\n\nThe translations are taken from {file_path}:\n\n{f.read()}"
                )

        return prompt

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        reraise=True,
    )
    def _translate_texts(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        file_path: str = None,
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

        client = OpenAI(api_key=openai_api_key)
        messages = [
            {
                "role": "system",
                "content": self.get_system_prompt(
                    texts, source_language, target_language, file_path
                ),
            },
            {"role": "user", "content": json.dumps(texts)},
        ]
        response = client.chat.completions.create(
            model=openai_default_model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            split_content = content.split("\n")
            if split_content[0] == "```json" and split_content[-1] == "```":
                content = "\n".join(split_content[1:-1])
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    pass
            msg = f"ChatGPT did not return a proper JSON string: {content}"
            if temperature == 0:
                msg += (
                    " This may be due to the low temperature setting. "
                    "Please try again with a higher temperature leading to less-deterministic results. "
                    "You can set it by setting `openai_default_temperature` in your .dallingerconfig file. "
                    "The default temperature of GPT4 is 0.7."
                )
            raise InvalidTranslationError(msg) from e


class DefaultTranslator(Translator):
    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        file_path: str = None,
    ):
        config = get_config()
        default_translator = config.get("default_translator")
        translator_class = get_descendent_class_by_name(Translator, default_translator)
        return translator_class().translate(texts, source_lang, target_lang, file_path)


class NullTranslator(Translator):
    nickname = "null"
    use_codebook = False

    def translate(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        file_path: str = None,
    ):
        return texts


def get_translator_from_name(name: Optional[str] = None) -> Translator:
    if name is None:
        return DefaultTranslator()
    translator_class = get_descendent_class_by_name(Translator, name)
    return translator_class()

"""Vocabulary tests (WikiVocab, BibleVocab) for screening participants by language.

A test shows real and made-up words one at a time; the participant says which are real.
Each word shown is its own :class:`VocabTrial`, so exports give one row per word, with
its answer, response time, ``position`` and ``node_id`` (repeats share a node).

Words come in forms: ``n_items`` words, half real and half fake, then
``n_repeat_items`` of them again. :meth:`VocabTest.word_order` plans every form on
block entry, so a trial's form follows from its ``position``. Screening checks each
form once its last word is answered (:meth:`VocabTest.should_check_performance_after`)
and again at the end, and every form begun so far must pass.

Every word uses the same :class:`~psynet.page.JSPage`, with only its ``contents``
changing, so with trials prepared in advance the page stays on screen and
``psynet/resources/scripts/vocabtest.js`` shows the next word without asking the
server. Keep anything that changes between words in ``contents``; changing the
page's HTML or ``page_config`` per word makes each word wait for the server.
"""

import csv
import os
import random
import re
import tempfile
import warnings
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Optional, Type

import arabic_reshaper
import requests
from dominate import tags
from markupsafe import Markup
from yaspin import yaspin

from psynet.asset import OnDemandAsset
from psynet.page import InfoPage, JSPage
from psynet.timeline import join
from psynet.translation.keyboards import KeyboardPage
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import (
    get_fitting_font_size,
    get_language_dict,
    get_locale,
    get_translator,
    text_to_image,
)

# Supported locales for the WikiVocab test
wikivocab_locales = [
    "af",
    "ar",
    "be",
    "bg",
    "ca",
    "cs",
    "cy",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fo",
    "fr",
    "ga",
    "gd",
    "gl",
    "he",
    "hi",
    "hr",
    "hu",
    "hy",
    "hyw",
    "id",
    "is",
    "it",
    "ja",
    "ko",
    "lt",
    "lv",
    "mr",
    "mt",
    "nl",
    "nn",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sa",
    "se",
    "sk",
    "sl",
    "sr",
    "sv",
    "ta",
    "te",
    "tr",
    "ug",
    "uk",
    "ur",
    "vi",
    "wo",
    "zh",
]

# Mapping from ISO2 locale to Bible tag (usually ISO3)
locale2bible_tag = {
    "am": "amh",  # Amharic
    "ar": "arb",  # Arabic
    "as": "asm",  # Assamese
    "av": "ava",  # Avaric
    "az": "azj",  # Azerbaijani
    "ba": "bak",  # Bashkir
    "be": "bel",  # Belarusian
    "bn": "ben",  # Bengali
    "bi": "bis",  # Bislama
    "bo": "bod",  # Tibetan
    "bg": "bul",  # Bulgarian
    "ca": "cat",  # Catalan
    "cs": "ces",  # Czech
    "ce": "che",  # Chechen
    "cv": "chv",  # Chuvash
    "doi": "dgo",  # Dogri
    "ku_IQ": "ckb",  # Kurdish (Central Kurdish)
    "kw": "cor",  # Cornish
    "co": "cos",  # Corsican
    "cy": "cym",  # Welsh
    "da": "dan",  # Danish
    "de": "deu",  # German
    "dv": "div",  # Divehi
    "el": "ell",  # Greek
    "en": "eng",  # English
    "eo": "epo",  # Esperanto
    "eu": "eus",  # Basque
    "fo": "fao",  # Faroese
    "fj": "fij",  # Fijian
    "fi": "fin",  # Finnish
    "fr": "fra",  # French
    "gd": "gla",  # Scottish Gaelic
    "ga": "gle",  # Irish
    "gl": "glg",  # Galician
    "gv": "glv",  # Manx
    "gu": "guj",  # Gujarati
    "ht": "hat",  # Haitian Creole
    "ha": "hau",  # Hausa
    "he": "heb",  # Hebrew
    "hi": "hin",  # Hindi
    "ho": "hmo",  # Hiri Motu
    "hr": "hrv",  # Croatian
    "hu": "hun",  # Hungarian
    "hw": "hwc",  # Hawaiian
    "hy": "hye",  # Armenian
    "id": "ind",  # Indonesian
    "is": "isl",  # Icelandic
    "it": "ita",  # Italian
    "jv": "jav",  # Javanese
    "ja": "jpn",  # Japanese
    "kn": "kan",  # Kannada
    "ka": "kat",  # Georgian
    "mn": "khk",  # Khakas
    "kk": "kaz",  # Kazakh
    "kok": "gom",  # Konkani (Goan Konkani)
    "km": "khm",  # Khmer
    "ki": "kik",  # Kikuyu
    "mai": "mai",  # Maithili
    "mni": "mni",  # Manipuri
    "rw": "kin",  # Kinyarwanda
    "ky": "kir",  # Kyrgyz
    "ku": "kmr",  # Kurdish (Kurmanji)
    "ko": "kor",  # Korean
    "kj": "kua",  # Kuanyama
    "lo": "lao",  # Lao
    "la": "lat",  # Latin
    "ln": "lin",  # Lingala
    "lt": "lit",  # Lithuanian
    "lg": "lug",  # Ganda
    "lv": "lvs",  # Latvian
    "ml": "mal",  # Malayalam
    "mr": "mar",  # Marathi
    "mk": "mkd",  # Macedonian
    "mt": "mlt",  # Maltese
    "mi": "mri",  # Maori
    "ms": "msa",  # Malay
    "my": "mya",  # Burmese
    "nv": "nav",  # Navajo
    "nr": "nbl",  # Southern Ndebele
    "nd": "nde",  # Northern Ndebele
    "ng": "ndo",  # Ndonga
    "nl": "nld",  # Dutch
    "nn": "nno",  # Norwegian Nynorsk
    "no": "nob",  # Norwegian Bokmål
    "ne": "npi",  # Nepali
    "ny": "nya",  # Chichewa
    "od": "ory",  # Odia
    "os": "oss",  # Ossetian
    "pa": "pan",  # Punjabi
    "fa": "pes",  # Persian
    "mg": "plt",  # Malagasy
    "pl": "pol",  # Polish
    "pt": "por",  # Portuguese
    "ru": "rus",  # Russian
    "sg": "sag",  # Sango
    "sa": "san",  # Sanskrit
    "sat": "sat",  # Santali
    "si": "sin",  # Sinhala
    "sk": "slk",  # Slovak
    "sl": "slv",  # Slovenian
    "sn": "sna",  # Shona
    "sd": "snd",  # Sindhi
    "so": "som",  # Somali
    "st": "sot",  # Southern Sotho
    "es": "spa",  # Spanish
    "sq": "sqi",  # Albanian
    "ss": "ssw",  # Swati
    "su": "sun",  # Sundanese
    "sv": "swe",  # Swedish
    "sw": "swh",  # Swahili
    "ta": "tam",  # Tamil
    "tt": "tat",  # Tatar
    "te": "tel",  # Telugu
    "tg": "tgk",  # Tajik
    "tl": "tgl",  # Tagalog
    "th": "tha",  # Thai
    "tn": "tsn",  # Tswana
    "ts": "tso",  # Tsonga
    "tk": "tuk",  # Turkmen
    "tr": "tur",  # Turkish
    "tw": "twi",  # Twi
    "ug": "uig",  # Uighur
    "uk": "ukr",  # Ukrainian
    "ur": "urd",  # Urdu
    "uz": "uzn",  # Uzbek
    "ve": "ven",  # Venda
    "vo": "vol",  # Volapük
    "xh": "xho",  # Xhosa
    "zh_CN": "zho",  # Chinese
    "zh_TW": "zho_tw",  # Chinese (Taiwan)
    "zo": "zom",  # Zomi
    "zu": "zul",  # Zulu
}

biblevocab_locales = list(locale2bible_tag.values())


_ = get_translator()


class VocabTrial(StaticTrial):
    """One presentation of a vocabulary item, including a repeated presentation."""

    time_estimate = 1.8
    # The feedback after a form's last word adds to that trial's time.
    check_time_credit_received = False

    @staticmethod
    def score_answer(answer, definition):
        return int(
            answer == ("real" if definition["correct_answer"] == "correct" else "fake")
        )

    def show_trial(self, experiment, participant):
        return self.trial_maker.word_page(self)

    def gives_feedback(self, experiment, participant):
        return self.trial_maker.show_feedback and self.trial_maker.ends_form(self)

    def show_feedback(self, experiment, participant):
        maker = self.trial_maker
        score = maker.score_form(
            maker.get_participant_trials(participant), self.position + 1
        )
        return InfoPage(
            _("Your score was")
            + f" {score:.0%}. "
            + _("Press the button to continue."),
            time_estimate=5,
        )


default_test_config = {
    "image_width": 500,
    "image_height": 350,
}


class VocabTest(StaticTrialMaker):
    """
    A test to check the participant's vocabulary knowledge. The test consists of a series of trials, each showing a
    string of characters. The participant has to decide whether the string is an existing word in the given language or
    not. Each string is shown for a short time and then disappears. The participant can either respond by pressing the
    corresponding key on the keyboard or by clicking the corresponding button on the screen. The test is made to work
    with the vocabulary tests created with the VocabTest package by Pol van Rijn
    (https://github.com/polvanrijn/VocabTest).

    VocabTest does not support synchronized groups. Each participant must
    receive independently chosen items.

    Attributes
    ----------

    locale : str
        The locale of the test. The locale is a two-letter ISO 639-1 code.
    label : str
        The label of the test.
    csv_path : str
        The path to the CSV file containing the test items.
    performance_threshold_per_trial : float
        Minimal percentage of correct responses. Each form is checked once its last word is answered, and a
        participant whose score for it is below this threshold is disqualified. A word left unanswered until
        the response timeout scores its form 0, as does a form left unfinished. If set to None, the performance
        will not be checked.
    performance_check_type : str
        The type of performance check. The performance can be checked based on accuracy or consistency. If set to
        "accuracy", the performance is checked based on the percentage of correct responses. If set to "consistency",
        the performance is checked based on the percentage of consistent responses between the first and second
        presentation of the same item.
    n_trials : int
        The number of scored forms per participant (default 1). Each word presentation is one saved trial.
    n_items : int
        The number of items per form. The number of items must be even. The items are randomly selected from the
        list of real and fake words, such that there are an equal number of real and fake words. By default, the number
        of items is set to 30.
    n_repeat_items : int
        The number of repeated items per form. The repeated items are randomly selected from the list of selected
        items. By default, the number of repeated items is set to 0. Consistency compares the two responses to each repeated word. Accuracy scores only first presentations.
    show_instructions : bool
        Whether to show the instructions at the beginning of the test. By default, the instructions are shown.
    show_feedback : bool
        Whether to show the feedback after each form. By default, the feedback is shown.
    hide_after : int
        The time in milliseconds after which the item disappears. By default, the item disappears after 1000 ms.
    lag_between_items : int
        The time in milliseconds between the presentation of items. By default, the time between the items is set to
        200 ms. This is useful to prevent the participant from responding too quickly.
    use_keyboard : bool
        Whether to use the keyboard to respond. By default, the keyboard is used.
    use_buttons : bool
        Whether to use the buttons to respond. By default, the buttons are not used. `use_keyboard` and `use_buttons`
        are not mutually exclusive. If both are set to True, the participant can respond using both the keyboard and
        the buttons. However, `use_buttons` is recommended to be set to False because of the response speed, however
        it might be necessary for mobile devices.
    true_key_button : str
        The key code for the correct answer. By default, the key code is "KeyA". Must be a valid key code, see
        https://developer.mozilla.org/en-US/docs/Web/API/UI_Events/Keyboard_event_code_values for a list of key codes.
    true_key_label : str
        The label for the correct answer. By default, the label is "A" (corresponding to the key code "KeyA").
    false_key_button : str
        The key code for the incorrect answer. By default, the key code is "KeyL". Must be a valid key code, see
        https://developer.mozilla.org/en-US/docs/Web/API/UI_Events/Keyboard_event_code_values for a list of key codes.
    false_key_label : str
        The label for the incorrect answer. By default, the label is "L" (corresponding to the key code "KeyL").
    trial_class : Type[VocabTrial]
        The class of the trial. By default, the trial class is VocabTrial.
    present_as_image: bool
        Whether to present the items as images or as text. If set to True, the items are presented as images. If set
        to False, the items are presented as text. By default, the items are presented as images.
    font_url: Optional[str]
        The URL to the font to use for rendering the items as images. If set to None, the default font is used.

    """

    def __init__(
        self,
        locale: str,
        label: str,
        csv_path: str,
        performance_threshold_per_trial: float,
        performance_check_type: str = "accuracy",
        n_trials: int = 1,
        n_items: int = 30,
        n_repeat_items: int = 0,
        show_instructions: bool = True,
        show_feedback: bool = True,
        hide_after: int = 1000,
        lag_between_items: int = 200,
        use_keyboard: bool = True,
        use_buttons: bool = False,
        true_key_button: str = "KeyA",
        true_key_label: str = "A",
        false_key_button: str = "KeyL",
        false_key_label: str = "L",
        trial_class: Type[VocabTrial] = VocabTrial,
        present_as_image: bool = True,
        # Its file name is also listed in the stock .gitignore and in
        # psynet.deployment_info.DOWNLOADED_RESOURCE_PATHS.
        font_url: Optional[
            str
        ] = "https://psynet.s3.amazonaws.com/resources/fonts/GoNotoKurrent-Bold.ttf",
        **kwargs,
    ):
        if kwargs.get("sync_group_type") is not None:
            raise ValueError(
                "VocabTest does not support synchronized groups. "
                "Each participant must receive independently chosen items."
            )
        self.locale = locale
        self.label = label

        if performance_threshold_per_trial is not None and not (
            0 <= performance_threshold_per_trial <= 1
        ):
            raise ValueError("performance_threshold_per_trial must be between 0 and 1.")
        self.performance_threshold_per_trial = performance_threshold_per_trial

        if performance_check_type not in ("accuracy", "consistency"):
            raise ValueError(
                "performance_check_type must be 'accuracy' or 'consistency'."
            )
        self.performance_check_type = performance_check_type
        if performance_check_type == "consistency":
            if n_repeat_items <= 0:
                raise ValueError(
                    "A consistency check needs at least one repeated item."
                )
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != ["stimulus", "correct_answer"]:
                raise ValueError("Expected the columns stimulus,correct_answer.")
            test_items = list(reader)
        if not test_items or any(
            not item["stimulus"]
            or item["correct_answer"] not in ("correct", "incorrect")
            for item in test_items
        ):
            raise ValueError(
                "Each vocabulary item needs a word and a correct or incorrect answer label."
            )
        if n_items <= 0 or n_trials < 1 or n_repeat_items < 0:
            raise ValueError(
                "A vocabulary test needs at least one form with a positive item count."
            )
        if n_items % 2 != 0:
            raise ValueError("The number of items must be even.")
        if n_repeat_items > n_items:
            raise ValueError(
                "The number of repeated items must be less than or equal to the number of items."
            )
        if not use_buttons and not use_keyboard:
            raise ValueError(
                "Enable buttons or keyboard input for the vocabulary test."
            )
        if any(
            sum(item["correct_answer"] == answer for item in test_items) < n_items // 2
            for answer in ("correct", "incorrect")
        ):
            raise ValueError(
                "The bank needs enough distinct real and fake items for one form."
            )

        self.present_as_image = present_as_image
        if self.present_as_image:
            (
                self.use_arabic_script,
                self.image_width,
                self.image_height,
                self.font_size,
            ) = self.image_setup(test_items, font_url, **kwargs)
        else:
            warnings.warn(
                "The test is not presented as images. This will make it easier for LLMs to pass the test."
            )

        self.n_trials = n_trials
        self.n_items = n_items
        self.n_repeat_items = n_repeat_items
        self.show_instructions = show_instructions
        self.show_feedback = show_feedback
        self.hide_after = hide_after
        self.lag_between_items = lag_between_items
        self.use_keyboard = use_keyboard
        self.use_buttons = use_buttons
        self.true_key_button = true_key_button
        self.true_key_label = true_key_label
        self.false_key_button = false_key_button
        self.false_key_label = false_key_label

        count = n_trials * self.form_size
        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=[self.word_node(item) for item in test_items],
            expected_trials_per_participant=count,
            max_trials_per_participant=count,
            node_order=self.word_order,
            allow_repeated_nodes=True,
            check_performance_every_trial=True,
            # Catches forms whose last words failed, which the check after
            # each form never reaches.
            check_performance_at_end=True,
            prepare_trials_in_advance=True,
        )

    @property
    def form_size(self):
        return self.n_items + self.n_repeat_items

    def word_order(self, nodes, participant):
        """Balance real and fake words and prefer less familiar nodes across forms."""
        visits = Counter()
        pools = [
            [node for node in nodes if node.definition["correct_answer"] == label]
            for label in ("correct", "incorrect")
        ]
        order = []
        for _ in range(self.n_trials):
            originals = []
            for pool in pools:
                # Randomize ties between words with equal exposure.
                random.shuffle(pool)
                originals.extend(
                    sorted(pool, key=lambda node: visits[node.id])[: self.n_items // 2]
                )
            random.shuffle(originals)
            form = originals + random.sample(originals, self.n_repeat_items)
            order.extend(form)
            visits.update(node.id for node in form)
        return order

    def word_node(self, item):
        if not self.present_as_image:
            return StaticNode(definition=item)
        text = item["stimulus"]
        if self.use_arabic_script:
            reshaper = arabic_reshaper.ArabicReshaper()
            if self.locale in ("ur", "fa"):
                reshaper.language = {"ur": "Urdu", "fa": "Farsi"}[self.locale]
            text = reshaper.reshape(text)
        image = OnDemandAsset(
            function=text_to_image,
            extension=".png",
            arguments=dict(
                text=text,
                width=self.image_width,
                height=self.image_height,
                font_path=self.font_path,
                font_size=self.font_size,
            ),
        )
        return StaticNode(definition=item, assets={"image": image})

    def word_page(self, trial):
        """Return the page for one word; every word's page has the same HTML."""

        def choice(value, label, key):
            caption = f"{label} ({key})" if self.use_keyboard else label
            if self.use_buttons:
                return tags.button(
                    caption,
                    type="button",
                    disabled=True,
                    data_choice=value,
                    cls="btn btn-outline-secondary mx-1",
                )
            return tags.span(caption, cls="mx-2")

        height = self.image_height if self.present_as_image else 260
        if self.present_as_image:
            contents = {"image": trial.node.assets["image"].url}
        else:
            contents = {"stimulus": trial.definition["stimulus"]}
        return JSPage(
            "vocabtest",
            tags.div(
                tags.div(
                    id="test-stimulus",
                    role="status",
                    style=(
                        f"min-height:min({height}px,55vh);display:grid;place-items:center;"
                        "font-size:clamp(2rem,7vw,5rem);font-weight:bold;"
                        "overflow-wrap:anywhere"
                    ),
                ),
                choice("real", _("Real"), self.true_key_label),
                choice("fake", _("Fake"), self.false_key_label),
                cls="text-center",
            ),
            contents=contents,
            module="/static/scripts/vocabtest.js",
            page_config={
                "vocab": {
                    "trueKey": self.true_key_button,
                    "falseKey": self.false_key_button,
                    "keyboard": self.use_keyboard,
                    "buttons": self.use_buttons,
                    "hideAfter": self.hide_after,
                    "lag": self.lag_between_items,
                    "width": getattr(self, "image_width", None),
                }
            },
            bot_response=lambda: random.choice(["real", "fake"]),
            time_estimate=self.trial_class.time_estimate,
        )

    @staticmethod
    def get_font_path(font_url):
        """Return a local copy of the font used to draw the word images, downloading it if needed.

        The font is saved in the experiment's ``static/fonts/`` folder so that
        deployments include it; the stock ``.gitignore`` ignores the default font.
        """
        font_dir = os.path.join("static", "fonts")
        font_path = os.path.join(font_dir, os.path.basename(font_url))
        if not os.path.exists(font_path):
            with yaspin(text="Downloading font...", color="yellow") as spinner:
                response = requests.get(font_url, timeout=60)
                response.raise_for_status()
                spinner.ok("✔")
            os.makedirs(font_dir, exist_ok=True)
            # Write then rename so that a parallel process never reads a partial file.
            fd, temp_path = tempfile.mkstemp(dir=font_dir)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(response.content)
                # mkstemp creates the file readable only by its owner.
                os.chmod(temp_path, 0o644)
                os.replace(temp_path, font_path)
            except BaseException:
                Path(temp_path).unlink(missing_ok=True)
                raise
        return os.path.abspath(font_path)

    def image_setup(self, test_items, font_url, **kwargs):
        concatenated_chars = "".join(item["stimulus"] for item in test_items)
        arabic_regex = r"[^0-9\u0600-\u06ff\u0750-\u077f\ufb50-\ufbc1\ufbd3-\ufd3f\ufd50-\ufd8f\ufd50-\ufd8f\ufe70-\ufefc\uFDF0-\uFDFD]+"
        arabic_chars = re.sub(arabic_regex, "", concatenated_chars)
        arabic_percentage = len(arabic_chars) / len(concatenated_chars)
        use_arabic_script = arabic_percentage > 0.9
        # Image settings
        image_width = kwargs.get("image_width", default_test_config["image_width"])
        image_height = kwargs.get("image_height", default_test_config["image_height"])

        self.font_path = os.path.relpath(self.get_font_path(font_url))

        font_size = get_fitting_font_size(
            text=test_items[-1]["stimulus"],
            font_path=self.font_path,
            max_width=int(image_width * 0.8),
            max_height=int(image_height * 0.8),
            min_font_size=10,
            max_font_size=100,
        )
        return use_arabic_script, image_width, image_height, font_size

    def score_form(self, trials, stop):
        """Score the form that ends just before position ``stop``.

        Override this to change how a form is scored.

        Parameters
        ----------
        trials : list of VocabTrial
            The participant's trials in this test.
        stop : int
            The position after the form's last word, a multiple of
            :attr:`form_size`.

        Returns
        -------
        float
            The share of real-or-fake answers that are correct, or for
            ``performance_check_type="consistency"`` the share of repeats
            answered as the first time. A form with a word that wasn't
            answered scores 0.
        """
        form = sorted(
            (t for t in trials if stop - self.form_size <= t.position < stop),
            key=lambda t: t.position,
        )
        if len(form) != self.form_size or any(
            not t.complete or t.failed or t.answer not in ("real", "fake") for t in form
        ):
            return 0
        originals = form[: self.n_items]
        if self.performance_check_type == "consistency":
            first_answers = {t.node_id: t.answer for t in originals}
            repeats = form[self.n_items :]
            return sum(t.answer == first_answers.get(t.node_id) for t in repeats) / len(
                repeats
            )
        return sum(t.score for t in originals) / len(originals)

    def _passes(self, score):
        threshold = self.performance_threshold_per_trial
        return threshold is None or score >= threshold

    def ends_form(self, trial):
        """Return whether ``trial`` is the last presentation of its form."""
        return (trial.position + 1) % self.form_size == 0

    def should_check_performance_after(self, trial):
        """Check each form once its last word is answered, so the words in between don't wait for the server."""
        return self.ends_form(trial)

    def performance_check(self, experiment, participant, participant_trials):
        """Score every form begun so far, giving the latest form's score; each must pass."""
        n_begun = 1 + max((t.position for t in participant_trials), default=-1)
        n_forms = -(-n_begun // self.form_size)
        scores = [
            self.score_form(participant_trials, (form + 1) * self.form_size)
            for form in range(n_forms)
        ]
        return {
            "score": scores[-1] if scores else None,
            "passed": all(self._passes(score) for score in scores),
        }

    @classmethod
    def get_language_name(self, test_locale):
        exp_locale = get_locale()
        language_dict = get_language_dict(exp_locale)
        return language_dict[test_locale]

    @classmethod
    def get_instructions_intro(cls, test_locale):
        return InfoPage(
            Markup(
                "<p>"
                + " ".join(
                    [
                        _("We will perform a test to check your language abilities."),
                        _("In each trial, you will see a string of characters."),
                        _("The string will automatically disappear."),
                        _(
                            "Your task is to decide whether this is an existing word in {LANGUAGE_NAME} or not."
                        ).format(LANGUAGE_NAME=cls.get_language_name(test_locale)),
                    ]
                )
                + "</p>"
            ),
            time_estimate=5,
        )

    @classmethod
    def get_instructions_spelling(cls, test_locale):
        language_name = cls.get_language_name(test_locale)
        return InfoPage(
            Markup(
                " ".join(
                    [
                        _(
                            "If you don’t know the exact meaning of the word, but you are certain that it exists in {LANGUAGE_NAME}, you should mark the it as a real word."
                        ).format(LANGUAGE_NAME=language_name),
                        _(
                            "If you are not sure whether the word exists in {LANGUAGE_NAME}, you should mark it as a fake word."
                        ).format(LANGUAGE_NAME=language_name),
                        '<br><br><div class="alert alert-warning">'
                        + _(
                            "In this experiment, you might find a mix between spelling variants."
                        ),
                        _(
                            "You should not pay attention to subtle spelling differences."
                        ),
                        _(
                            "The words are presented in either only uppercase or lowercase letters."
                        ),
                        _("You can ignore the case of the word."),
                        "</div>",
                    ]
                )
            ),
            time_estimate=5,
        )

    @classmethod
    def get_instructions_keyboard(cls, true_key=("KeyA", "A"), false_key=("KeyL", "L")):
        if true_key[1] == "A" and false_key[1] == "L":
            real = _(
                "Press <kbd>A</kbd> if the presented word is <strong>real</strong>"
            )
            fake = _(
                "Press <kbd>L</kbd> if the presented word is <strong>fake</strong>"
            )
        else:
            key_hint = Markup("{} (<kbd>{}</kbd>)")
            real = str(key_hint.format(_("Real"), true_key[1]))
            fake = str(key_hint.format(_("Fake"), false_key[1]))
        prompt = Markup(
            _("To do the task quickly, you should use the keys on your keyboard.")
            + " "
            + _("You can use the following keys:")
            + "<ul>"
            + "<li>"
            + real
            + "</li><li>"
            + fake
            + "</li>"
            + "</ul>"
            + "<br>"
            + _("Familiarize yourself with the two keys on your keyboard.")
            + " "
            + _("If you press them, they will light up in the keyboard on the right.")
            + " "
            + "<strong>"
            + "<font size='4.5', color='#ff4633'>"
            + _(
                "You need to press both keys at least once to progress to the next page."
            )
            + "</font>"
            + "</strong>"
            + " "
            + _("In case you forget the keys, they will be printed on every page.")
        )
        return KeyboardPage(
            prompt=prompt,
            highlight_keys=[true_key[0], false_key[0]],
            press_keys=[true_key[0], false_key[0]],
            time_estimate=5,
        )

    @classmethod
    def get_instructions_start(cls):
        return InfoPage(_("The test will start on the next page."), time_estimate=1)

    @classmethod
    def get_instructions(cls, test_locale, use_keyboard, **keyboard):
        pages = [
            cls.get_instructions_intro(test_locale),
            cls.get_instructions_spelling(test_locale),
        ]

        if use_keyboard:
            pages.append(cls.get_instructions_keyboard(**keyboard))
        pages.append(cls.get_instructions_start())
        return join(*pages)

    @property
    def introduction(self):
        if self.show_instructions:
            return self.get_instructions(
                self.locale,
                self.use_keyboard,
                true_key=(self.true_key_button, self.true_key_label),
                false_key=(self.false_key_button, self.false_key_label),
            )
        else:
            return None


def get_test_csv_and_label(locale, test_type):
    error_msg = f"""
    Vocabulary test not found for locale "{locale}" and test type "{test_type}".
    You can can download missing tests here: https://github.com/polvanrijn/VocabTest/tree/main/vocabtest/
    Place the missing csv file in your experiment folder and create a vocabulary test by running:
     `VocabTest(csv_path='path/to/your.csv', …)`
    """
    if test_type in "wikivocab":
        if locale not in wikivocab_locales:
            raise ValueError(error_msg)
    elif test_type in "biblevocab":
        if locale not in biblevocab_locales:
            raise ValueError(error_msg)
    else:
        raise ValueError(f"Unknown test type: {test_type}")
    test_csv = str(
        resources.files("psynet") / f"resources/vocabtest/{test_type}/{locale}.csv"
    )
    return test_csv, f"{test_type}_{locale}"


class WikiVocab(VocabTest):
    """
    WikiVocab language test for 60 languages.

    The WikiVocab test is a vocabulary test that checks the participant's knowledge of words in a given language.
    Make sure you set the `performance_threshold_per_trial` according to your requirements.

    See :class:`~psynet.prescreen.vocabtest.VocabTest` for the other arguments.
    """

    def __init__(
        self, locale: str, performance_threshold_per_trial: float = 0.5, **kwargs
    ):
        if kwargs is None:
            kwargs = {}
        assert len(locale) == 2
        csv_path, label = get_test_csv_and_label(locale, "wikivocab")

        super().__init__(
            locale=locale,
            csv_path=csv_path,
            label=label,
            performance_threshold_per_trial=performance_threshold_per_trial,
            **kwargs,
        )


class BibleVocab(VocabTest):
    """
    BibleVocab language test created from the Bible.

    The BibleVocab test is a vocabulary test that checks the participant's knowledge of words in a given language.
    Make sure you set the `performance_threshold_per_trial` according to your requirements.

    Since the quality of the vocabulary test items is less controlled than the WikiVocab test, one can use the
    "consistency" `performance_check_type` instead.

    See :class:`~psynet.prescreen.vocabtest.VocabTest` for the other arguments.
    """

    def __init__(
        self, locale: str, performance_threshold_per_trial: float = 0.5, **kwargs
    ):
        if kwargs is None:
            kwargs = {}
        locale = locale2bible_tag.get(locale, locale)
        csv_path, label = get_test_csv_and_label(locale, "biblevocab")
        super().__init__(
            locale=locale,
            csv_path=csv_path,
            label=label,
            performance_threshold_per_trial=performance_threshold_per_trial,
            **kwargs,
        )

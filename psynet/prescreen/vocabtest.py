import os
import random
import re
import tempfile
import warnings
from datetime import time
from hashlib import sha256
from importlib import resources
from typing import Optional, Type

import arabic_reshaper
import requests
from markupsafe import Markup
from yaspin import yaspin

from psynet.asset import ExperimentAsset
from psynet.page import InfoPage
from psynet.timeline import MediaSpec, Page, get_template, join
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


class VocabPage(Page):
    """
    A page for the vocabulary test. The page shows a series of items, each consisting of a string of characters. The
    participant has to decide whether the string is an existing word in the given language or not. Each string is shown
    for a short time and then disappears. The participant can either respond by pressing the corresponding key on the
    keyboard or by clicking the corresponding button on the screen.

    Attributes
    ----------

    time_estimate : int
        The time estimate for the page in seconds.
    items : list[dict]
        The list of items to show. This includes n_items + n_repeat_items item. The order is randomized on the backend.
        The order on the frontend is fixed.
    test_config : dict
        A dictionary containing the test configuration which is passed on to the frontend.
    media : MediaSpec
        The media specification for the vocabulary items (by default all assets associated with the trial).
    """

    def __init__(
        self,
        time_estimate,
        items: list[dict],
        test_config: dict,
        media: Optional[MediaSpec] = None,
    ):
        self.items = items
        super().__init__(
            label="vocabtest",
            time_estimate=time_estimate,
            template_str=get_template("vocabtest.html"),
            framework_owned_template=True,
            js_vars={
                "items": items,
                "testConfig": test_config,
            },
            media=media,
        )

    def get_bot_response(self, experiment, bot):
        from psynet.bot import BotResponse

        answer = [
            {"hash": item["hash"], "answer": random.choice(["real", "fake"])}
            for item in self.items
        ]
        return BotResponse(
            raw_answer=answer,
            metadata=self.metadata(),
        )


class VocabTrial(StaticTrial):
    """
    A trial for the vocabulary test. The trial shows a series of items, each consisting of a string of characters. The
    participant has to decide whether the string is an existing word in the given language or not. Each string is shown
    for a short time and then disappears. The participant can either respond by pressing the corresponding key on the
    keyboard or by clicking the corresponding button on the screen.
    """

    @property
    def trial_maker(self) -> "VocabTest":
        return self.node.trial_maker

    def get_base_test_config(self):
        return {
            "trueKeyButton": self.trial_maker.true_key_button,
            "trueKeyLabel": self.trial_maker.true_key_label,
            "falseKeyButton": self.trial_maker.false_key_button,
            "falseKeyLabel": self.trial_maker.false_key_label,
            "hideAfter": self.trial_maker.hide_after,
            "lagBetweenItems": self.trial_maker.lag_between_items,
            "useKeyboard": self.trial_maker.use_keyboard,
            "showButtons": self.trial_maker.use_buttons,
            "presentAsImage": self.trial_maker.present_as_image,
        }

    def finalize_definition(self, definition, experiment, participant):
        previous_trials = [
            previous
            for previous in VocabTrial.query.filter_by(
                trial_maker_id=self.trial_maker_id,
                participant_id=participant.id,
            ).all()
            if previous is not self
        ]
        selected_hashes = self.trial_maker.choose_hashes(
            self.node.seed, previous_trials
        )
        assets = self.trial_maker.get_assets(self.node.seed, selected_hashes)
        self.assets = {**self.assets, **assets}
        return {**definition, "hashes": selected_hashes}

    @property
    def items(self) -> list[dict]:
        return [{"hash": _hash} for _hash in self.definition["hashes"]]

    def show_image_trial(self):
        test_config = self.get_base_test_config()
        test_config["imageWidth"] = self.trial_maker.image_width
        test_config["imageHeight"] = self.trial_maker.image_height
        return VocabPage(
            items=self.items,
            test_config=test_config,
            media=(MediaSpec(image={**self.assets})),
            time_estimate=self.trial_maker.time_estimate_per_trial,
        )

    def show_text_trial(self):
        hash2stimulus = {item["hash"]: item["stimulus"] for item in self.node.seed}
        items = [
            {**item, "stimulus": hash2stimulus[item["hash"]]} for item in self.items
        ]
        return VocabPage(
            items=items,
            test_config=self.get_base_test_config(),
            media=None,
            time_estimate=self.trial_maker.time_estimate_per_trial,
        )

    def show_trial(self, experiment, participant):
        if self.trial_maker.present_as_image:
            return self.show_image_trial()
        else:
            return self.show_text_trial()

    def show_feedback(self, experiment, participant):
        if not self.trial_maker.show_feedback or self.score is None:
            return None
        prompt = _("Your score was") + f" {self.score:.0%}. "
        prompt += _("Press the button to continue.")

        return InfoPage(
            prompt,
            time_estimate=5,
        )

    def score_answer(self, answer, definition):
        return self.trial_maker.score_trial(self)


def date_hash(x):
    now = time()
    return sha256((str(now) + x).encode()).hexdigest()


_ = get_translator()

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
    receive independently chosen items; a follower copy would run
    ``finalize_definition`` again and pick a different set.

    Attributes
    ----------

    locale : str
        The locale of the test. The locale is a two-letter ISO 639-1 code.
    label : str
        The label of the test.
    csv_path : str
        The path to the CSV file containing the test items.
    performance_threshold_per_trial : float
        Minimal percentage of correct responses. If the participant's performance is below this threshold, the
        participant will be disqualified. If set to None, the performance will not be checked.
    performance_check_type : str
        The type of performance check. The performance can be checked based on accuracy or consistency. If set to
        "accuracy", the performance is checked based on the percentage of correct responses. If set to "consistency",
        the performance is checked based on the percentage of consistent responses between the first and second
        presentation of the same item.
    n_trials : int
        The number of trials per participant. Each trial shows a sequence of items. By default, the participant will
        perform one trial.
    n_items : int
        The number of items per trial. The number of items must be even. The items are randomly selected from the
        list of real and fake words, such that there are an equal number of real and fake words. By default, the number
        of items is set to 30.
    n_repeat_items : int
        The number of repeated items per trial. The repeated items are randomly selected from the list of selected
        items. By default, the number of repeated items is set to 0. This parameter is only used when the performance
        check type is set to "consistency".
    show_instructions : bool
        Whether to show the instructions at the beginning of the test. By default, the instructions are shown.
    show_feedback : bool
        Whether to show the feedback after each trial. By default, the feedback is shown.
    hide_after : int
        The time in milliseconds after which the item disappears. By default, the item disappears after 2000 ms.
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
    trial_class : ChainTrial
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
        hide_after: int = 2000,
        lag_between_items: int = 200,
        use_keyboard: bool = True,
        use_buttons: bool = False,
        true_key_button: str = "KeyA",
        true_key_label: str = "A",
        false_key_button: str = "KeyL",
        false_key_label: str = "L",
        trial_class: Type[VocabTrial] = VocabTrial,
        present_as_image: bool = True,
        font_url: Optional[
            str
        ] = "https://psynet.s3.amazonaws.com/resources/fonts/GoNotoKurrent-Bold.ttf",
        **kwargs,
    ):
        if kwargs.get("sync_group_type") is not None:
            raise ValueError(
                "VocabTest does not support synchronized groups. "
                "Each participant must receive independently chosen items; "
                "a follower copy would pick a different item set."
            )
        self.locale = locale
        self.label = label

        assert (
            performance_threshold_per_trial is None
            or 0 <= performance_threshold_per_trial <= 1
        )
        self.performance_threshold_per_trial = performance_threshold_per_trial

        assert performance_check_type in ["accuracy", "consistency"]
        self.performance_check_type = performance_check_type
        if performance_check_type == "consistency":
            assert n_repeat_items > 0, (
                "The number of repeated items must be greater than 0."
            )
        concatenated_chars = ""
        test_items = []
        with open(csv_path) as f:
            lines = [line.strip() for line in f.readlines()]
            headers = lines[0].split(",")
            assert headers == ["stimulus", "correct_answer"]
            lines = lines[1:]
            for line in lines:
                stimulus, correct_answer = line.split(",")
                concatenated_chars += stimulus.strip()
                test_items.append(
                    {
                        "stimulus": stimulus,
                        "correct_answer": correct_answer,
                        # We give each stimulus a unique, hard to guess hash to easily identify which stimuli have been
                        # visited already and for easily accessing assets from the psynet JS front-end
                        # Fixme: In the near future, we want to simplify this behaviour
                        "hash": date_hash(stimulus),
                    }
                )

        self.present_as_image = present_as_image
        if self.present_as_image:
            (
                self.use_arabic_script,
                self.image_width,
                self.image_height,
                self.font_size,
            ) = self.image_setup(concatenated_chars, test_items, font_url, **kwargs)
        else:
            warnings.warn(
                "The test is not presented as images. This will make it easier for LLMs to pass the test."
            )

        self.n_trials = n_trials
        self.n_items = n_items
        self.n_repeat_items = n_repeat_items
        assert self.n_items % 2 == 0, "The number of items must be even."
        assert self.n_repeat_items <= self.n_items, (
            "The number of repeated items must be less than or equal to the number of items."
        )
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

        self.time_estimate_per_trial = self.n_items * 1.8  # based on extensive testing

        super().__init__(
            id_=label,
            trial_class=trial_class,
            nodes=[StaticNode(seed=test_items)],
            expected_trials_per_participant=self.n_trials,
            max_trials_per_participant=self.n_trials,
            check_performance_every_trial=True,
            allow_repeated_nodes=True,
            recruit_mode=None,
            target_trials_per_node=None,
            target_n_participants=None,
            sync_group_type=None,
        )

    def get_font_path(self, font_url):
        font_name = os.path.basename(font_url)
        font_path = f"static/fonts/{font_name}"
        if not os.path.exists(font_path):
            with yaspin(text="Downloading font...", color="yellow") as spinner:
                response = requests.get(font_url)
                spinner.ok("✔")
            os.makedirs(os.path.dirname(font_path), exist_ok=True)
            with open(font_path, "wb") as f:
                f.write(response.content)
        return os.path.abspath(font_path)

    def image_setup(self, concatenated_chars, test_items, font_url, **kwargs):
        arabic_regex = r"[^0-9\u0600-\u06ff\u0750-\u077f\ufb50-\ufbc1\ufbd3-\ufd3f\ufd50-\ufd8f\ufd50-\ufd8f\ufe70-\ufefc\uFDF0-\uFDFD]+"
        arabic_chars = re.sub(arabic_regex, "", concatenated_chars)
        arabic_percentage = len(arabic_chars) / len(concatenated_chars)
        use_arabic_script = arabic_percentage > 0.9
        # Image settings
        image_width = kwargs.get("image_width", default_test_config["image_width"])
        image_height = kwargs.get("image_height", default_test_config["image_height"])

        default_test_config["font_path"] = self.get_font_path(font_url)

        font_size = get_fitting_font_size(
            text=test_items[-1]["stimulus"],
            font_path=default_test_config["font_path"],
            max_width=int(image_width * 0.8),
            max_height=int(image_height * 0.8),
            min_font_size=10,
            max_font_size=100,
        )
        return use_arabic_script, image_width, image_height, font_size

    def select_hashes(self, stimuli, n):
        assert len({item["hash"] for item in stimuli}) == len(stimuli), (
            "Duplicate hashes found in input to select_hashes."
        )
        selected_hashes = []
        enough_stimuli = False
        n_visited = sorted({item["n_visited"] for item in stimuli})
        while not enough_stimuli:
            for i in n_visited:
                subset = [item for item in stimuli if item["n_visited"] == i]
                n_missing_hashes = n - len(selected_hashes)
                available_hashes = [item["hash"] for item in subset]
                if len(subset) >= n_missing_hashes:
                    selected_hashes.extend(
                        random.sample(available_hashes, n_missing_hashes)
                    )
                    enough_stimuli = True
                else:
                    selected_hashes.extend(available_hashes)
        assert len(set(selected_hashes)) == len(selected_hashes), (
            "Duplicates found in output of select_hashes."
        )
        return selected_hashes

    def choose_hashes(self, stimuli, previous_trials):
        assert len({item["hash"] for item in stimuli}) == len(stimuli), (
            "Duplicate hashes found in input to choose_hashes."
        )
        visited_hashes = []
        for _trial in previous_trials:
            visited_hashes.extend(_trial.definition["hashes"])

        hash_hist = {}
        for hash_ in visited_hashes:
            hash_hist[hash_] = hash_hist.get(hash_, 0) + 1

        for item in stimuli:
            item["n_visited"] = hash_hist.get(item["hash"], 0)

        stimuli = list(sorted(stimuli, key=lambda x: x["n_visited"]))
        correct_stimuli = [
            item for item in stimuli if item["correct_answer"] == "correct"
        ]
        incorrect_stimuli = [
            item for item in stimuli if item["correct_answer"] == "incorrect"
        ]

        n = self.n_items // 2
        selected_hashes = (
            # balance the number of correct and incorrect answers
            self.select_hashes(correct_stimuli, n)
            + self.select_hashes(incorrect_stimuli, n)
        )
        selected_hashes = random.sample(selected_hashes, n * 2)
        assert len(set(selected_hashes)) == len(selected_hashes), (
            "choose_hashes returned duplicate hashes."
        )
        if self.n_repeat_items > 0:
            selected_hashes = selected_hashes + random.sample(
                selected_hashes, self.n_repeat_items
            )
        return selected_hashes

    def get_assets(self, stimuli, selected_hashes):
        if not self.present_as_image:
            return {}
        assets = {
            asset.local_key: asset
            for asset in ExperimentAsset.query.filter(
                ExperimentAsset.local_key.in_(selected_hashes)
            ).all()
        }

        # Generate images
        with tempfile.TemporaryDirectory() as temp_dir:
            for i, hash_ in enumerate(selected_hashes):
                if hash_ in assets:
                    continue
                item = next(item for item in stimuli if item["hash"] == hash_)
                padded_i = str(i).zfill(4)
                text = item["stimulus"]
                if self.use_arabic_script:
                    reshaper = arabic_reshaper.ArabicReshaper()
                    if self.locale == "ur":
                        reshaper.language = "Urdu"
                    elif self.locale == "fa":
                        reshaper.language = "Farsi"
                    text = reshaper.reshape(text)
                path = os.path.join(temp_dir, f"{padded_i}.png")
                text_to_image(
                    text=text,
                    path=path,
                    width=self.image_width,
                    height=self.image_height,
                    font_size=self.font_size,
                    font_path=default_test_config["font_path"],
                )
                asset = ExperimentAsset(
                    local_key=hash_,
                    input_path=path,
                    extension=".png",
                    description=f"{hash_}-{item['stimulus']}-{item['correct_answer']}",
                )
                asset.deposit()
                assets[hash_] = asset
        return assets

    @staticmethod
    def score_consistency(items, repeat_items):
        item_dict = {item["hash"]: item for item in items}
        repeat_item_dict = {item["hash"]: item for item in repeat_items}
        common_hashes = set(item_dict.keys()) & set(repeat_item_dict.keys())
        n_consistent = 0
        for hash_ in common_hashes:
            if item_dict[hash_]["answer"] == repeat_item_dict[hash_]["answer"]:
                n_consistent += 1
        return n_consistent / len(common_hashes) if common_hashes else 0

    @staticmethod
    def score_accuracy(items, definition):
        n_correct = 0
        for item in items:
            correct_answer = definition[item["hash"]]["correct_answer"]
            if (
                item["answer"] == "real"
                and correct_answer == "correct"
                or item["answer"] == "fake"
                and correct_answer == "incorrect"
            ):
                n_correct += 1
        return n_correct / len(items)

    def score_trial(self, trial):
        definition = {
            item["hash"]: item
            for item in trial.node.seed
            if item["hash"] in trial.definition["hashes"]
        }

        items = trial.answer
        repeat_items = []
        if self.n_repeat_items > 0:
            repeat_items = items[-self.n_repeat_items :]
            items = items[: -self.n_repeat_items]

        if self.performance_check_type == "accuracy":
            return self.score_accuracy(items, definition)
        elif self.performance_check_type == "consistency":
            return self.score_consistency(items, repeat_items)
        else:
            raise ValueError(
                f"Unknown performance check type: {self.performance_check_type}"
            )

    def performance_check(self, experiment, participant, participant_trials):
        score = self.score_trial(participant_trials[0])
        passed = (
            True
            if self.performance_threshold_per_trial is None
            else score >= self.performance_threshold_per_trial
        )
        return {"score": score, "passed": passed}

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
    def get_instructions_keyboard(cls):
        prompt = (
            _("To do the task quickly, you should use the keys on your keyboard.")
            + " "
            + _("You can use the following keys:")
            + "<ul>"
            + "<li>"
            + _("Press <kbd>A</kbd> if the presented word is <strong>real</strong>")
            + "</li>"
            + "<li>"
            + _("Press <kbd>L</kbd> if the presented word is <strong>fake</strong>")
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
            highlight_keys=["KeyA", "KeyL"],
            press_keys=["KeyA", "KeyL"],
            time_estimate=5,
        )

    @classmethod
    def get_instructions_start(cls):
        return InfoPage(_("The test will start on the next page."), time_estimate=1)

    @classmethod
    def get_instructions(cls, test_locale, use_keyboard):
        pages = [
            cls.get_instructions_intro(test_locale),
            cls.get_instructions_spelling(test_locale),
        ]

        if use_keyboard:
            pages.append(cls.get_instructions_keyboard())
        pages.append(cls.get_instructions_start())
        return join(*pages)

    @property
    def introduction(self):
        if self.show_instructions:
            return self.get_instructions(self.locale, self.use_keyboard)
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

    See `VocabTest` for more information.
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

    Make sure you set the `performance_threshold_per_trial` according to your requirements.
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

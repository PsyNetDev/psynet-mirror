import json
from typing import List

from markupsafe import Markup

from psynet.log import bold, red
from psynet.lucid import get_lucid_service
from psynet.modular_page import Control, ModularPage
from psynet.recruiters import get_lucid_country_language_id
from psynet.timeline import join
from psynet.utils import get_logger


def create_lucid_recruitment_config(
    language_tag,
    country_tag,
    question_answer_dict,
    config_path=None,
    allow_mobile_devices: bool = None,
    force_google_chrome: bool = None,
    unique_ip: bool = True,
    unique_pid: bool = True,
    industry_id: int = 30,
    study_type_id: int = 1,
    debug: bool = True,
    qualifications_dict=None,
    config=None,
    service=None,
):
    """
    Build the Lucid (Cint) recruitment config for one language-country pair.

    Looks up each qualification and its translated answer options through the Lucid API,
    so it needs the Lucid API credentials. It also adds ``TIMEOUT v1`` (answer ``Agree``),
    mobile and tablet exclusions unless ``allow_mobile_devices`` is true, and a Chrome
    requirement when ``force_google_chrome`` is true.

    Parameters
    ----------
    language_tag : str
        Three-letter Lucid language code (not an ISO tag); the API lists valid codes on error.
    country_tag : str
        Two-letter Lucid country code (not an ISO code); the API lists valid codes on error.
    question_answer_dict : dict
        Maps qualification names on your Lucid account to lists of allowed English answers.
        Modified in place to add ``TIMEOUT v1``.
    config_path : str, optional
        If given, write the config to this JSON file and return ``None``.
    allow_mobile_devices : bool, optional
        Defaults to the ``allow_mobile_devices`` config value.
    force_google_chrome : bool, optional
        Defaults to the ``force_google_chrome`` config value.
    unique_ip : bool
        Require a unique IP address per participant.
    unique_pid : bool
        Require a unique panelist ID per participant.
    industry_id : int
        Lucid industry ID; default 30 (Other). Options: 1 Automotive, 2 Beauty/Cosmetics,
        3 Beverages - Alcoholic, 4 Beverages - Non Alcoholic, 5 Education,
        6 Electronics/Computer/Software, 7 Entertainment (Movies, Music, TV, etc),
        8 Fashion/Clothing, 9 Financial Services/Insurance, 10 Food/Snacks,
        11 Gambling/Lottery, 12 Healthcare/Pharmaceuticals, 13 Home (Utilities, Appliances, ...),
        14 Home Entertainment (DVD, VHS), 15 Home Improvement/Real Estate/Construction,
        16 IT (Servers, Databases, etc), 17 Personal Care/Toiletries, 18 Pets, 19 Politics,
        20 Publishing (Newspaper, Magazines, Books), 21 Restaurants, 22 Sports,
        23 Telecommunications (phone, cell phone, cable), 24 Tobacco (Smokers), 25 Toys,
        26 Transportation/Shipping, 27 Travel, 28 Video Games, 29 Websites/Internet/E-Commerce,
        30 Other, 31 Sensitive Content, 32 Explicit Content.
    study_type_id : int
        Lucid study type ID; default 1 (Adhoc). Options: 1 Adhoc, 2 Diary, 5 IHUT,
        8 Community Build, 9 Face to Face, 11 Recruit - Panel, 13 Tracking - Monthly,
        14 Tracking - Quarterly, 15 Tracking - Weekly, 16 Wave Study, 17 Qualitative Screening,
        18 Internal Use, 21 Incidence Check, 22 Recontact, 23 Ad Effectiveness Research,
        24 Proof Exposed, 25 Proof Control.
    debug : bool
        Print the English and translated text of each qualification.
    qualifications_dict : dict, optional
        Maps qualification names to Lucid question IDs. Fetched from the API if omitted;
        pass it to save time when building several configs.
    config : dallinger.config.Configuration, optional
        Experiment config; loaded if omitted.
    service : LucidService, optional
        Lucid service; created with :func:`psynet.lucid.get_lucid_service` if omitted.

    Returns
    -------
    dict or None
        The config (with ``survey``, ``qualifications``, ``country`` and ``language`` keys),
        or ``None`` if ``config_path`` is given.
    """

    logger = get_logger()
    if config is None:
        from psynet.utils import get_config

        config = get_config()
    if service is None:
        service = get_lucid_service(config=config)

    if qualifications_dict is None:
        qualifications_dict = service.get_qualifications_dict()

    country_language_id = get_lucid_country_language_id(
        country_tag, language_tag, service=service
    )

    qualifications = []

    if allow_mobile_devices is None:
        allow_mobile_devices = config.get("allow_mobile_devices")

    if not allow_mobile_devices:
        qualifications.append(
            {
                "Name": "MS_is_mobile",
                "QuestionID": 8214,
                "LogicalOperator": "NOT",
                "NumberOfRequiredConditions": 0,
                "IsActive": True,
                "Order": 1,
                "PreCodes": ["true"],
            }
        )
        qualifications.append(
            {
                "Name": "MS_is_tablet",
                "QuestionID": 8213,
                "LogicalOperator": "NOT",
                "NumberOfRequiredConditions": 0,
                "IsActive": True,
                "Order": 1,
                "PreCodes": ["true"],
            }
        )

    if force_google_chrome is None:
        force_google_chrome = config.get("force_google_chrome")

    if force_google_chrome:
        qualifications.append(
            {
                "Name": "MS_browser_type_Non_Wurfl",
                "QuestionID": 1035,
                "LogicalOperator": "OR",
                "NumberOfRequiredConditions": 0,
                "IsActive": True,
                "Order": 2,
                "PreCodes": ["Chrome"],
            }
        )

    question_answer_dict["TIMEOUT v1"] = ["Agree"]

    for question_name, options in question_answer_dict.items():
        if question_name not in qualifications_dict:
            raise ValueError(f"Unknown question {question_name}.")
        question_id = qualifications_dict[question_name]
        english_option_df = service.get_answer_options(question_id)
        option_df = english_option_df.query("text in @options")
        assert len(option_df) > 0, (
            f"Question {question_name} does not have specified options: {options}. Make sure to pick from: {english_option_df.text.tolist()}."
        )
        precodes = option_df.precode.tolist()

        foreign_locale = f"{language_tag}_{country_tag}"
        try:
            foreign_option_df = service.get_answer_options(question_id, foreign_locale)
        except AssertionError:
            raise AssertionError(
                bold(
                    red(f"Could not find question {question_name} in {foreign_locale}.")
                )
                + " "
                + "Make sure it exists: https://www.samplicio.us/fulcrum/Questions.aspx"
            )

        foreign_selected_option_df = foreign_option_df.query("precode in @precodes")
        english_selected_option_df = english_option_df.query("precode in @precodes")
        assert len(foreign_selected_option_df) == len(english_selected_option_df), (
            f"Foreign options for question {question_name} do not match English options. English: {english_selected_option_df.text.tolist()} -> Foreign: {foreign_selected_option_df.text.tolist()}"
        )
        foreign_question = service.get_question_name(question_id, foreign_locale)

        english_question = service.get_question_name(question_id)

        qualifications.append(
            {
                "Name": question_name,
                "QuestionID": question_id,
                "LogicalOperator": "OR",
                "NumberOfRequiredConditions": len(options),
                "IsActive": True,
                "PreCodes": precodes,
                "QuestionText": english_question,
                "OptionsTextDict": dict(
                    zip(english_option_df.precode, english_option_df.text)
                ),
                "QuestionTranslation": foreign_question,
                "OptionsTranslationDict": dict(
                    zip(foreign_option_df.precode, foreign_option_df.text)
                ),
            }
        )
        if debug:
            logger.info(
                bold(
                    f"Question {question_name} ({question_id}): {service.default_locale.upper()} -> {foreign_locale.upper()}"
                )
            )
            print(
                bold("English")
                + f": '{english_question}' => {english_selected_option_df.text.tolist()}"
            )
            print(
                bold("Foreign")
                + f": '{foreign_question}' => {foreign_selected_option_df.text.tolist()}"
            )
    lucid_recruitment_config = {
        "survey": {
            "CountryLanguageID": country_language_id,
            # Following API documentation: To ensure Suppliers have access to the Survey when it is set live,
            # set the following parameters:
            # FulcrumExchangeAllocation: 0
            # FulcrumExchangeHedgeAccess: true
            "FulcrumExchangeAllocation": 0,
            "FulcrumExchangeHedgeAccess": True,
            "IndustryID": industry_id,
            "StudyTypeID": study_type_id,
            "UniqueIPAddress": unique_ip,
            "UniquePID": unique_pid,
        },
        "qualifications": qualifications,
        "country": country_tag,
        "language": language_tag,
    }
    if config_path is not None:
        with open(config_path, "w") as f:
            json.dump(lucid_recruitment_config, f, indent=4)
    else:
        return lucid_recruitment_config


class LucidTerminateControl(Control):
    """
    This control presents a list of buttons. If the participant clicks a not allowed button, the experiment is
    terminated. This can be used for screening within the experiment.

    """

    macro = "terminate_control"

    def __init__(
        self,
        choices: List[str],
        labels: List[str],
        allowed: List[str],
        page_label: str,
        css_class_per_option: List[str],
        arrange_vertically: bool = True,
    ):
        super().__init__()
        assert all([choice in choices for choice in allowed])
        assert all(
            [
                all([char.islower() or char == "-" for char in choice])
                for choice in choices
            ]
        ), (
            "All choices must be lowercase letters. Special characters are not allowed except '-'."
        )
        self.items = [
            {
                "label": labels[i],
                "allowed": choice in allowed,
                "id": choice,
                "class": css_class_per_option[i],
            }
            for i, choice in enumerate(choices)
        ]
        self.label = page_label
        self.arrange_vertically = arrange_vertically

    @property
    def metadata(self):
        return self.__dict__


class LucidScreeningQuestion(ModularPage):
    def __init__(
        self,
        label,
        question,
        choices,
        labels,
        allowed,
        time_estimate,
        arrange_vertically=False,
        base_css_class="btn btn-primary btn-lg mx-2",
        css_class_per_option=None,
        aggressive_termination_on_no_focus=True,
    ):
        assert len(choices) == len(labels)
        if css_class_per_option is None:
            css_class_per_option = [base_css_class] * len(choices)
        assert len(css_class_per_option) == len(choices)
        css_class_per_option = [
            base_css_class + " " + style for style in css_class_per_option
        ]
        super().__init__(
            label=label,
            prompt=Markup(question),
            control=LucidTerminateControl(
                choices=choices,
                labels=labels,
                allowed=allowed,
                page_label=label,
                arrange_vertically=arrange_vertically,
                css_class_per_option=css_class_per_option,
            ),
            time_estimate=time_estimate,
            show_next_button=False,
            show_early_exit_button=False,
            aggressive_termination_on_no_focus=aggressive_termination_on_no_focus,
        )


class LucidTwoForcedChoiceQualification(LucidScreeningQuestion):
    def __init__(
        self,
        label,
        question,
        labels,
        choices=None,
        allowed=None,
        time_estimate=2,
        css_class_per_option=None,
    ):
        if choices is None:
            choices = ["yes", "no"]
            css_class_per_option = ["btn-success", "btn-danger"]

        assert css_class_per_option is not None, (
            "If you provide custom choices, you must also provide custom css classes"
        )

        if allowed is None:
            allowed = ["yes"]
        assert all([choice in choices for choice in allowed]), (
            f"Allowed choices must be in {choices}"
        )
        super().__init__(
            label=label,
            question=question,
            choices=choices,
            labels=labels,
            allowed=allowed,
            time_estimate=time_estimate,
            css_class_per_option=css_class_per_option,
        )


def verify_lucid_qualifications(config_path: str, question_names: List[str] = None):
    """
    Re-ask Lucid qualification questions in the experiment, ending it for disallowed answers.

    Each question is shown in the participant's language with two buttons; choosing an
    answer not allowed by the qualification terminates the experiment.

    Parameters
    ----------
    config_path : str
        JSON file written by :func:`create_lucid_recruitment_config`.
    question_names : list of str, optional
        Qualifications to ask. Defaults to all except the built-in ``MS_`` ones.
        Each must have exactly two answer options.

    Returns
    -------
    list
        Timeline elements, one page per question.
    """
    with open(config_path, "r") as f:
        config = json.load(f)

    name2question = {q["Name"]: q for q in config["qualifications"]}

    if question_names is None:
        question_names = [
            name for name in name2question.keys() if not name.startswith("MS_")
        ]

    unknown_questions = [q for q in question_names if q not in name2question]
    assert len(unknown_questions) == 0, f"Unknown question names: {unknown_questions}"
    pages = []

    for question_name in question_names:
        qualification = name2question[question_name]
        question = qualification["QuestionTranslation"]
        option_dict = qualification["OptionsTranslationDict"]
        assert len(option_dict) == 2, (
            f"Question {question_name} must have exactly 2 options."
        )

        choices = ["yes", "no"]
        allowed_choices = [
            choices[int(precode) - 1] for precode in qualification["PreCodes"]
        ]
        all_options = list(option_dict.values())

        pages.append(
            LucidTwoForcedChoiceQualification(
                label=question_name,
                question=question,
                labels=all_options,
                choices=choices,
                css_class_per_option=["btn-success", "btn-danger"],
                allowed=allowed_choices,
                time_estimate=5,
            )
        )
    return join(*pages)

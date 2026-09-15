from typing import Optional

from psynet.modular_page import (
    Control,
    DropdownControl,
    ModularPage,
    NumberControl,
    PushButtonControl,
    RadioButtonControl,
    TextControl,
)
from psynet.timeline import FailedValidation, Module, conditional, join
from psynet.utils import (
    get_country_dict,
    get_language_dict,
    get_locale,
    get_logger,
    get_translator,
)

logger = get_logger()


class BasicDemography(Module):
    def __init__(
        self,
        label="basic_demography",
    ):
        self.label = label
        self.elts = join(
            Gender(),
            Age(),
            CountryOfBirth(),
            CountryOfResidence(),
            FormalEducation(),
        )
        super().__init__(self.label, self.elts)


class Language(Module):
    def __init__(
        self,
        label="language",
    ):
        self.label = label
        self.elts = join(
            MotherTongue(),
            MoreThanOneLanguage(),
            conditional(
                "more_than_one_language",
                lambda experiment, participant: participant.answer == "yes",
                LanguagesInOrderOfProficiency(),
            ),
        )
        super().__init__(self.label, self.elts)


class BasicMusic(Module):
    def __init__(
        self,
        label="basic_music",
    ):
        self.label = label
        self.elts = join(
            YearsOfFormalTraining(),
            HoursOfDailyMusicListening(),
            MoneyFromPlayingMusic(),
        )
        super().__init__(self.label, self.elts)


class Dance(Module):
    def __init__(
        self,
        label="dance",
    ):
        self.label = label
        self.elts = join(
            DanceSociallyOrProfessionally(),
            conditional(
                "dance_socially_or_professionally",
                lambda experiment, participant: (
                    participant.answer in ["socially", "professionally"]
                ),
                LastTimeDanced(),
            ),
        )
        super().__init__(self.label, self.elts)


class SpeechDisorders(Module):
    def __init__(
        self,
        label="speech_disorders",
    ):
        self.label = label
        self.elts = join(
            SpeechLanguageTherapy(),
            DiagnosedWithDyslexia(),
        )
        super().__init__(self.label, self.elts)


class Income(Module):
    def __init__(
        self,
        label="income",
    ):
        self.label = label
        self.elts = join(
            HouseholdIncomePerYear(),
        )
        super().__init__(self.label, self.elts)


class ExperimentFeedback(Module):
    def __init__(
        self,
        label="feedback",
    ):
        self.label = label
        self.elts = join(
            LikedExperiment(),
            FoundExperimentDifficult(),
            EncounteredTechnicalProblems(),
        )
        super().__init__(self.label, self.elts)


# Basic demography #
class Gender(ModularPage):
    def __init__(
        self,
        label="gender",
    ):
        _p = get_translator(context=True)
        prompt = _p("gender", "How do you identify yourself?")
        self.label = label
        self.prompt = prompt
        self.time_estimate = 5

        control = RadioButtonControl(
            ["female", "male", "non_binary", "not_specified", "prefer_not_to_say"],
            [
                _p("gender", "Female"),
                _p("gender", "Male"),
                _p("gender", "Non-binary"),
                _p("gender", "Not specified"),
                _p("gender", "I prefer not to answer"),
            ],
            name="gender",
            show_free_text_option=True,
            placeholder_text_free_text=_p("gender", "Specify yourself"),
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class Age(ModularPage):
    def __init__(
        self,
        label="age",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p("age", "What is your age?")
        self.time_estimate = 5
        super().__init__(
            self.label,
            self.prompt,
            control=NumberControl(),
            time_estimate=self.time_estimate,
            save_answer=label,
        )

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        answer = response.answer
        error_msg = (
            _p("age", "You need to provide your age as an integer between 0 and 120!")
            + " "
            + _p("age", "Your answer was: '{AGE}'").format(AGE=answer)
        )
        try:
            age = int(answer)
            if not (0 < age < 120):
                return FailedValidation(error_msg)
            else:
                return None
        except ValueError:
            return FailedValidation(error_msg)


class CountryDropdown(ModularPage):
    def __init__(self, label):
        self.label = label
        _p = get_translator(context=True)
        self.time_estimate = 5
        locale = get_locale()
        country_dict = get_country_dict(locale)
        control = DropdownControl(
            choices=list(country_dict.keys()) + ["OTHER"],
            labels=list(country_dict.values())
            + [_p("country-select", "Other country")],
            default_text=_p("country-select", "Select a country"),
            name=self.label,
        )
        super().__init__(
            self.label,
            self.get_prompt(),
            control=control,
            time_estimate=self.time_estimate,
            save_answer="country",
        )

    def get_prompt(self):
        raise NotImplementedError()

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        if self.control.force_selection and response.answer == "":
            return FailedValidation(
                _p("country-select", "You need to select a country!")
            )
        return None


class CountryOfBirth(CountryDropdown):
    def __init__(
        self,
        label="country_of_birth",
    ):
        super().__init__(label)

    def get_prompt(self):
        _p = get_translator(context=True)
        return _p("country-select", "What country are you from?")


class CountryOfResidence(CountryDropdown):
    def __init__(
        self,
        label="country_of_residence",
    ):
        super().__init__(label)

    def get_prompt(self):
        _p = get_translator(context=True)
        return _p("country-select", "What is your current country of residence?")


class FormalEducation(ModularPage):
    def __init__(
        self,
        label="formal_education",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "formal-education", "What is your highest level of formal education?"
        )
        self.time_estimate = 5

        control = RadioButtonControl(
            [
                "none",
                "high_school",
                "college",
                "graduate_school",
                "postgraduate_degree_or_higher",
            ],
            [
                _p("formal-education", "None"),
                _p("formal-education", "High school"),
                _p("formal-education", "College"),
                _p("formal-education", "Graduate School"),
                _p("formal-education", "Postgraduate degree or higher"),
            ],
            name="formal_education",
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


# Language #
class MotherTongue(ModularPage):
    def __init__(
        self,
        label="mother_tongue",
        # TODO Change back to plural (add "(s)") once multi-select is implemented.
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "language-select",
            "What is your mother tongue - i.e., the language which you have grown up speaking from early childhood?",
        )
        self.time_estimate = 5
        locale = get_locale()
        language_dict = get_language_dict(locale)

        control = DropdownControl(
            choices=list(language_dict.keys()) + ["other"],
            labels=list(language_dict.values()) + ["Other language"],
            default_text=_p("language-select", "Select a language"),
            name=self.label,
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        if self.control.force_selection and response.answer == "":
            return FailedValidation(
                _p("language-select", "You need to select a language!")
            )
        return None


class MoreThanOneLanguage(ModularPage):
    def __init__(
        self,
        label="more_than_one_language",
    ):
        _ = get_translator()
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p("language-select", "Do you speak more than one language?")
        self.time_estimate = 5

        control = PushButtonControl(
            choices=["yes", "no"],
            labels=[_("Yes"), _("No")],
            arrange_vertically=False,
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class LanguageList(ModularPage):
    """
    This is a superclass containing core functionality for free-text participant language input pages.

    Parameters
    ----------
    label : str, optional
        The label for the page. The label is specified with default values in subclasses.
    prompt : str or callable, optional
        Prompt to show the participant. The prompt is specified with default values in subclasses.
    control : Control, optional
        The type of control to show to the participant. The control is specified with default values in subclasses.
    time_estimate : float, optional
        The time estimate for the page.
    save_answer : str, optional
        The name under which to store participant answers. Defaults to label.

    Attributes
    ----------
    default_label : str
        A default label to use is none is specified. Defined in each subclass.
    default_prompt : str or callable
        A default prompt to use if none is specified. Defined in each subclass.
    default_control : Control
        A default control to use if none is specified. Defined in each subclass.

    Methods
    -------
    validate(response, **kwargs)
        Ensures the participant has given a non-empty response, and raises a message to them if not.
    """

    def __init__(
        self,
        label: Optional[str] = None,
        prompt: Optional[str] = None,
        control: Optional[Control] = None,
        time_estimate: float = 5,
        save_answer: Optional[str] = None,
    ):
        if label is None:
            label = self.default_label
        if prompt is None:
            prompt = self.default_prompt
        if control is None:
            control = self.default_control
        if save_answer is None:
            save_answer = label
        super().__init__(
            label,
            prompt,
            control=control,
            time_estimate=time_estimate,
            save_answer=save_answer,
        )

    @property
    def default_label(self):
        raise NotImplementedError("Subclasses must define default_label")

    @property
    def default_prompt(self):
        raise NotImplementedError("Subclasses must define default_prompt")

    @property
    def default_control(self):
        return TextControl()

    def validate(self, response, **kwargs):
        _p = get_translator(context=True)
        if response.answer.strip() == "":
            return FailedValidation(
                _p("language-select", "Please list at least one language!")
            )
        return None


class LanguagesInOrderOfProficiency(LanguageList):
    """
    A free-text response page for participants to input multiple language in order of proficiency.

    Inherits from
    -------------
    LanguageList

    Attributes
    ----------
    default_label : str
        The default label for this page.
        May be overwritten with a label parameter when called.
    default_prompt : str or callable
        The default prompt instructing participants to list languages in order of proficiency.
        May be overwritten with a prompt parameter when called.
    default_control : Control
        The default control used for user input (free-text).
        May be overwritten with a Control parameter when called (unlikely to be needed).
    """

    default_label = "languages_in_order_of_proficiency"

    @property
    def default_prompt(self):
        _p = get_translator(context=True)
        return _p(
            "language-select",
            "Please list the languages you speak in order of proficiency (first language first, second language second, ...)",
        )


class MotherTongues(LanguageList):
    """
    A free-text response page for participants to input multiple languages they speak as mother tongues.

    Inherits from
    -------------
    LanguageList

    Attributes
    ----------
    default_label : str
        The default label for this page.
        May be overwritten with a label parameter when called.
    default_prompt : str or callable
        The default prompt instructing participants to list all languages they speak as mother tongues.
        May be overwritten with a prompt parameter when called.
    default_control : Control
        The default control used for user input (free-text).
        May be overwritten with a Control parameter when called (unlikely to be needed).
    """

    default_label = "mother_tongues"

    @property
    def default_prompt(self):
        _p = get_translator(context=True)
        return _p(
            "language-select",
            "Please list all languages you speak as mother tongues (i.e., which you grew up speaking since childhood).",
        )


# Basic music #
class YearsOfFormalTraining(ModularPage):
    def __init__(
        self,
        label="years_of_formal_training",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "music",
            "How many years of formal training on a musical instrument (including voice) have you had during your lifetime?",
        )
        self.time_estimate = 5
        super().__init__(
            self.label,
            self.prompt,
            control=NumberControl(),
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class HoursOfDailyMusicListening(ModularPage):
    def __init__(
        self,
        label="hours_of_daily_music_listening",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "music", "On average, how many hours do you listen to music daily?"
        )
        self.time_estimate = 5
        super().__init__(
            self.label,
            self.prompt,
            control=NumberControl(),
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class MoneyFromPlayingMusic(ModularPage):
    def __init__(
        self,
        label="money_from_playing_music",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p("music", "Do you make money from playing music?")
        self.time_estimate = 5

        control = RadioButtonControl(
            ["frequently", "sometimes", "never"],
            [_p("music", "Frequently"), _p("music", "Sometimes"), _p("music", "Never")],
            name="money_from_playing_music",
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


# Hearing loss #
class HearingLoss(ModularPage):
    def __init__(
        self,
        label="hearing_loss",
    ):
        _ = get_translator()
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "music", "Do you have hearing loss or any other hearing issues?"
        )
        self.time_estimate = 5

        control = PushButtonControl(
            choices=["yes", "no"],
            labels=[_("Yes"), _("No")],
            arrange_vertically=False,
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


# Dance #
class DanceSociallyOrProfessionally(ModularPage):
    def __init__(
        self,
        label="dance_socially_or_professionally",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p("dance", "Do you dance socially or professionally?")
        self.time_estimate = 5

        control = RadioButtonControl(
            ["socially", "professionally", "never_dance"],
            [
                _p("dance", "Socially"),
                _p("dance", "Professionally"),
                _p("dance", "I never dance"),
            ],
            name="dance_socially_or_professionally",
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class LastTimeDanced(ModularPage):
    def __init__(
        self,
        label="last_time_danced",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "dance",
            "When was the last time you danced? (choose the most accurate answer):",
        )
        self.time_estimate = 5

        control = RadioButtonControl(
            [
                "this_week",
                "this_month",
                "this_year",
                "some_years_ago",
                "many_years_ago",
                "never_danced",
            ],
            [
                _p("dance", "This week"),
                _p("dance", "This month"),
                _p("dance", "This year"),
                _p("dance", "Some years ago"),
                _p("dance", "Many years ago"),
                _p("dance", "I never danced"),
            ],
            name="last_time_danced",
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


# Speech disorders #
class SpeechLanguageTherapy(ModularPage):
    def __init__(
        self,
        label="speech_language_therapy",
    ):
        _ = get_translator()
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "speech-disorder", "Did you get speech-language therapy as a child?"
        )
        self.time_estimate = 5

        control = PushButtonControl(
            choices=["yes", "no", "dont_know"],
            labels=[_("Yes"), _("No"), _("I don’t know")],
            arrange_vertically=False,
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class DiagnosedWithDyslexia(ModularPage):
    def __init__(
        self,
        label="diagnosed_with_dyslexia",
    ):
        _ = get_translator()
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "speech-disorder", "Have you ever been diagnosed with dyslexia?"
        )
        self.time_estimate = 5

        control = PushButtonControl(
            choices=["yes", "no", "dont_know"],
            labels=[_("Yes"), _("No"), _("I don’t know")],
            arrange_vertically=False,
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
        )


# Income #
class HouseholdIncomePerYear(ModularPage):
    def __init__(
        self,
        label="household_income_per_year",
        currency="USD",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p("income", "What is your total household income per year?")
        self.time_estimate = 5

        control = RadioButtonControl(
            [
                "less_than_10000",
                "10000_to_19999",
                "20000_to_29999",
                "30000_to_39999",
                "40000_to_49999",
                "50000_to_59999",
                "60000_to_69999",
                "70000_to_79999",
                "80000_to_89999",
                "90000_to_99999",
                "100000_to_149999",
                "150000_or_more",
            ],
            [
                _p("income", "Less than 10,000 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "10,000 to 19,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "20,000 to 29,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "30,000 to 39,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "40,000 to 49,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "50,000 to 59,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "60,000 to 69,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "70,000 to 79,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "80,000 to 89,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "90,000 to 99,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "100,000 to 149,999 {CURRENCY}").format(CURRENCY=currency),
                _p("income", "150,000 {CURRENCY} or more").format(CURRENCY=currency),
            ],
            name="household_income_per_year",
        )
        super().__init__(
            self.label,
            self.prompt,
            control=control,
            time_estimate=self.time_estimate,
            save_answer=label,
            # Twelve income brackets cannot fit a laptop window.
            expect_scrolling=True,
        )


# ExperimentFeedback #
class LikedExperiment(ModularPage):
    def __init__(
        self,
        label="liked_experiment",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p("experiment-feedback", "Did you like the experiment?")
        self.time_estimate = 5
        super().__init__(
            self.label,
            self.prompt,
            control=TextControl(
                bot_response=lambda: "I'm a bot so I don't really have feelings..."
            ),
            time_estimate=self.time_estimate,
            save_answer=label,
        )


class FoundExperimentDifficult(ModularPage):
    def __init__(
        self,
        label="find_experiment_difficult",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = _p(
            "experiment-feedback", "Did you find the experiment difficult?"
        )
        self.time_estimate = 5
        super().__init__(
            self.label,
            self.prompt,
            control=TextControl(),
            time_estimate=self.time_estimate,
            bot_response=lambda: "I'm a bot so I found it pretty easy...",
            save_answer=label,
        )


class EncounteredTechnicalProblems(ModularPage):
    def __init__(
        self,
        label="encountered_technical_problems",
    ):
        _p = get_translator(context=True)
        self.label = label
        self.prompt = (
            _p(
                "experiment-feedback",
                "Did you encounter any technical problems during the experiment?",
            )
            + " "
            + _p(
                "experiment-feedback",
                "If so, please provide a few words describing the problem.",
            )
        )
        self.time_estimate = 5
        super().__init__(
            self.label,
            self.prompt,
            control=TextControl(),
            time_estimate=self.time_estimate,
            bot_response=lambda: "No technical problems.",
            save_answer=label,
        )

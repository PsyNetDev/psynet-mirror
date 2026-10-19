import psynet.experiment
from psynet.bot import Bot
from psynet.consent import NoConsent
from psynet.modular_page import PushButtonControl, TextControl
from psynet.page import InfoPage, ModularPage, SuccessfulEndPage
from psynet.timeline import CodeBlock, PageMaker, Timeline
from psynet.utils import get_translator

_ = get_translator()


class Exp(psynet.experiment.Experiment):
    label = "Translation test"
    config = {
        "locale": "nl",
        "supported_locales": ["en", "nl"],
    }
    variable_placeholders = {"PET": "dog", "NAME": "John"}

    timeline = Timeline(
        NoConsent(),
        InfoPage(
            _("Hello, welcome to my experiment!"),
            time_estimate=1,
        ),
        ModularPage(
            "name",
            prompt=_("What is your name?"),
            control=TextControl(),
            time_estimate=1,
        ),
        # Repeat the same page to test whether the translation deals with duplicate texts correctly
        ModularPage(
            "name",
            prompt=_("What is your name?"),
            control=TextControl(),
            time_estimate=1,
        ),
        CodeBlock(lambda participant: participant.var.set("name", participant.answer)),
        PageMaker(
            lambda participant: InfoPage(
                _("Hello, {NAME}!").format(NAME=participant.var.get("name")),
            ),
            time_estimate=1,
        ),
        ModularPage(
            "pet",
            prompt=_("What is your favorite pet?"),
            control=PushButtonControl(
                choices=["dog", "cat", "fish", "hamster", "bird", "snake"],
                labels=[
                    _("dog"),
                    _("cat"),
                    _("fish"),
                    _("hamster"),
                    _("bird"),
                    _("snake"),
                ],
            ),
            time_estimate=1,
        ),
        CodeBlock(
            lambda participant: participant.var.set("pet", _(participant.answer))
        ),
        PageMaker(
            lambda participant: InfoPage(
                _("Great, I like {PET} too!").format(PET=participant.var.get("pet")),
            ),
            time_estimate=1,
        ),
        SuccessfulEndPage(),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert True

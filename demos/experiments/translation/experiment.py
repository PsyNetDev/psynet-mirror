from dominate import tags

import psynet.experiment
from psynet.consent import NoConsent
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.utils import get_logger, get_translator

logger = get_logger()

_ = get_translator()
_p = get_translator(context=True)


class Exp(psynet.experiment.Experiment):
    label = "Translation demo"

    # You could also set these in the config.txt file
    config = {
        "locale": "de",
        "supported_locales": ["en", "de", "nl"],
        # Asserted by the end-to-end tests; generic recruitment now hides
        # rewards unless the experiment opts in.
        "show_reward": True,
    }
    timeline = Timeline(
        NoConsent(),
        InfoPage(
            _p("welcome-page", "Welcome to the translation demo!"), time_estimate=2
        ),
        InfoPage(
            tags.span(
                tags.h2(
                    f"You have chosen to translate this experiment to {config.get('locale')}."
                ),
                tags.p(
                    "Below you will see this text translated!",
                    tags.br(),
                    _("Below you will see this text translated!"),
                ),
            ),
            time_estimate=5,
        ),
        InfoPage(
            tags.span(
                tags.p("Here is an example of inline variable usage:"),
                tags.p(
                    _(
                        "My name is {NAME}. My favorite food is {FAVFOOD}. My least favorite food is {HATEFOOD}."
                    ).format(NAME="Alice", FAVFOOD="pizza", HATEFOOD="broccoli")
                ),
            ),
            time_estimate=5,
        ),
        ModularPage(
            "modular_translation",
            prompt=_(
                "You can also translate text in push buttons or any kind of page!"
            ),
            control=PushButtonControl(
                [
                    _p("button", "Chocolate"),
                    _p("button", "Vanilla"),
                    _p("button", "Strawberry"),
                ],
                arrange_vertically=False,
            ),
            time_estimate=4,
        ),
    )

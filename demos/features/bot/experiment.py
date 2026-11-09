import random

import psynet.experiment
from psynet.modular_page import ModularPage, TextControl
from psynet.page import UnsuccessfulEndPage
from psynet.timeline import CodeBlock, Timeline, conditional
from psynet.utils import get_logger

logger = get_logger()


class CustomTextControl(TextControl):
    def get_bot_response(self, experiment, bot, page, prompt):
        """
        This function is used when a bot simulates a participant responding to a given page.
        In the simplest form, the function just returns the value of the
        answer that the bot returns.
        For more sophisticated treatment, the function can return a
        ``BotResponse`` object which contains other parameters
        such as ``blobs`` and ``metadata``.
        """
        return "This response came from the CustomTextControl method."


# This demo doesn't actually run any bots; this is currently left to the associated test script.
class Exp(psynet.experiment.Experiment):
    label = "Bots demo"

    timeline = Timeline(
        CodeBlock(
            lambda participant: participant.var.set(
                "is_good_participant", bool(participant.id % 2)
            )
        ),
        ModularPage(
            "message_1",
            "This page has its bot function defined in-line using a fixed bot_response argument.",
            control=TextControl(),
            time_estimate=5,
            bot_response="Fixed response",
        ),
        ModularPage(
            "message_2",
            "This page instead uses a stochastic bot_response argument.",
            control=TextControl(),
            time_estimate=5,
            bot_response=lambda: random.sample(
                ["Stochastic response 1", "Stochastic response 2"], 1
            )[0],
        ),
        ModularPage(
            "message_3",
            "This page uses a custom control that has a customized built-in bot_response method.",
            control=CustomTextControl(),
            time_estimate=5,
        ),
        conditional(
            lambda participant: not participant.var.is_good_participant,
            UnsuccessfulEndPage(),
        ),
    )

from dominate import tags

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import CodeBlock, Timeline, join, switch, while_loop
from psynet.utils import get_logger

logger = get_logger()


def content_page(label, content, links):
    return join(
        ModularPage(
            label,
            tags.span(
                tags.p(content),
                tags.p(tags.em("Click below to visit another page.")),
            ),
            PushButtonControl(
                choices=links,
                labels=[choice.capitalize() for choice in links],
                arrange_vertically=False,
            ),
            # We have set the time_estimate to 0.0 to disable time-related payments.
            # An alternative would be to set wage_per_hour = 0.0 in the experiment config.
            time_estimate=0.0,
            save_answer="current_page",
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Simple website demo"

    config = {
        "show_reward": False,
        "show_progress_bar": False,
    }

    links = ["welcome", "fish", "dogs", "birds"]

    timeline = Timeline(
        join(
            CodeBlock(
                lambda participant: participant.var.set("current_page", "welcome")
            ),
            while_loop(
                condition=lambda: True,
                logic=join(
                    switch(
                        lambda participant: participant.var.get("current_page"),
                        {
                            "welcome": content_page(
                                "welcome", "Welcome to my website!", links
                            ),
                            "fish": content_page(
                                "fish", "My favorite fish is the goldfish.", links
                            ),
                            "dogs": content_page(
                                "dogs",
                                "My favorite dog is the golden retriever.",
                                links,
                            ),
                            "birds": content_page(
                                "birds", "My favorite bird is the robin.", links
                            ),
                        },
                    )
                ),
                expected_repetitions=0,
            ),
        ),
    )

    @classmethod
    def run_bot(cls, bot, **kwargs):
        assert bot.current_page_label == "welcome"

        bot.take_page(response="birds")
        assert bot.current_page_label == "birds"

        bot.take_page(response="fish")
        assert bot.current_page_label == "fish"

        bot.take_page(response="dogs")
        assert bot.current_page_label == "dogs"

        bot.take_page(response="welcome")
        assert bot.current_page_label == "welcome"

from dominate import tags

import psynet.experiment
from psynet.modular_page import ModularPage, TextControl
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Generic recruiter demo"

    timeline = Timeline(
        InfoPage("Welcome to the experiment!", time_estimate=5),
        ModularPage(
            "name",
            "What's your name?",
            TextControl(),
            time_estimate=5,
            save_answer="name",
        ),
    )

    def render_exit_message(self, participant):
        return tags.div(
            tags.h2("End of experiment"),
            tags.p(
                f"Thank you for participating, {participant.var.name}! ",
                "Now you're finished, you can go and watch some videos on ",
                tags.a("YouTube.", href="https://www.youtube.com"),
            ),
        )

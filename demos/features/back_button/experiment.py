import psynet.experiment
from psynet.modular_page import ModularPage, TextControl
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Back button demo"

    timeline = Timeline(
        InfoPage(
            "Welcome! This first page has no Back button, as there is nothing to go back to.",
            time_estimate=5,
        ),
        InfoPage(
            "Instructions, page 1 of 3. From here on, Back returns to the previous page.",
            time_estimate=5,
        ),
        InfoPage(
            "Instructions, page 2 of 3. Back and Next both change the page at once, "
            "without waiting for the server.",
            time_estimate=5,
        ),
        InfoPage(
            "Instructions, page 3 of 3. Next comes a question. "
            "Its page can go back here, in case you want to reread the instructions.",
            time_estimate=5,
        ),
        ModularPage(
            "colour",
            "Which colour do you like best?",
            TextControl(),
            time_estimate=5,
        ),
        InfoPage(
            "Thanks! This page has no Back button, because going back would "
            "mean answering the question again.",
            time_estimate=5,
        ),
        InfoPage(
            "This page could go back, but hides its Back button with "
            "show_back_button=False.",
            time_estimate=5,
            show_back_button=False,
        ),
    )

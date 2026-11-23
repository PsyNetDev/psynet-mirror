import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import PageMaker, Timeline


def question(label, prompt, choices):
    return ModularPage(
        label,
        prompt,
        PushButtonControl(choices, arrange_vertically=False),
        time_estimate=5,
        save_answer=label,
    )


def summary(participant):
    return InfoPage(
        f"You chose {participant.var.colour} and {participant.var.animal}. "
        "This page has no Back button, because a page maker builds it.",
        time_estimate=5,
    )


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
            "Instructions, page 3 of 3. Next come two questions. "
            "Go back from the second to change your first answer.",
            time_estimate=5,
        ),
        question("colour", "Pick a colour.", ["red", "green", "blue"]),
        question("animal", "Pick an animal.", ["cat", "dog", "owl"]),
        InfoPage(
            "Your answers are now final, so this page hides its Back button "
            "with show_back_button=False.",
            time_estimate=5,
            show_back_button=False,
        ),
        PageMaker(summary, time_estimate=5),
    )

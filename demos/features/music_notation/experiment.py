import psynet.experiment
from psynet.modular_page import ModularPage, MusicNotationPrompt
from psynet.timeline import Timeline
from psynet.utils import get_logger

logger = get_logger("experiment")


class Exp(psynet.experiment.Experiment):
    label = "Music notation demo"

    timeline = Timeline(
        ModularPage(
            "example_1",
            MusicNotationPrompt(
                content="[E2B2]",
                text="Here's some music notation:",
            ),
            time_estimate=5,
        ),
    )

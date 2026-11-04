import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Entry check test"

    timeline = Timeline(
        InfoPage("Experiment complete.", time_estimate=1),
    )

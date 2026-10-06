import psynet.experiment
from psynet.prescreen import AttentionTest
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Prolific demo"

    timeline = Timeline(
        AttentionTest(),
    )

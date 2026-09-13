"""Minimal experiment that imports a module sitting beside experiment.py."""

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline

from . import local_helper


class Exp(psynet.experiment.Experiment):
    label = "Local module import"
    helper_value = local_helper.VALUE

    timeline = Timeline(
        InfoPage("Hello", time_estimate=5),
    )

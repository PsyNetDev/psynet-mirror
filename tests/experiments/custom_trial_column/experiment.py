"""Minimal experiment that adds a custom column to a trial class."""

from sqlalchemy import Column, Integer, String

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.trial.static import StaticTrial


class CustomColumnTrial(StaticTrial):
    time_estimate = 5
    item_id = Column(String)
    attempts = Column(Integer, default=lambda: 0)

    def show_trial(self, experiment, participant):
        return InfoPage("Trial", time_estimate=5)


class Exp(psynet.experiment.Experiment):
    label = "Custom trial column"

    timeline = Timeline(
        InfoPage("Hello", time_estimate=5),
    )

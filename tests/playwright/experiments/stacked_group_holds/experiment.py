"""Stacked grouper and barrier holds for multi-member Playwright coverage."""

import os

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline

WAIT = "Waiting for your group"
GROUP_SIZE = int(os.environ.get("PSYNET_STACKED_GROUP_SIZE", "3"))


class Exp(psynet.experiment.Experiment):
    label = "Stacked group holds"

    timeline = Timeline(
        SimpleGrouper(
            group_type="stack",
            initial_group_size=GROUP_SIZE,
            content=WAIT,
        ),
        GroupBarrier(id_="stack_init", group_type="stack", content=WAIT),
        GroupBarrier(id_="stack_prepare", group_type="stack", content=WAIT),
        ModularPage(
            "choose_action",
            "Choose your action",
            PushButtonControl(choices=["go"]),
            time_estimate=1,
        ),
        GroupBarrier(id_="stack_after_choice", group_type="stack", content=WAIT),
        ModularPage("results", "Everyone is ready", time_estimate=1),
    )

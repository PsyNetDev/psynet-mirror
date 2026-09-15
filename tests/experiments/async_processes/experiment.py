import time

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import AsyncCodeBlock, Timeline


def async_work(participant):
    """Run a small, successful worker task for queue-delay benchmarking."""
    time.sleep(0.05)
    participant.var.async_work_completed = True


class Exp(psynet.experiment.Experiment):
    label = "Async process performance test"
    test_n_bots = 2

    timeline = Timeline(
        ModularPage(
            "start",
            "Ready to run async work?",
            PushButtonControl(["Continue"], bot_response="Continue"),
            time_estimate=1,
        ),
        AsyncCodeBlock(
            async_work,
            wait=True,
            expected_wait=0.1,
            check_interval=0.05,
        ),
        ModularPage(
            "finish",
            "Async work completed.",
            PushButtonControl(["Finish"], bot_response="Finish"),
            time_estimate=1,
        ),
    )

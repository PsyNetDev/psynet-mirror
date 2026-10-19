import datetime

import psynet.experiment
from psynet.page import wait_while
from psynet.timeline import CodeBlock, Timeline
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Demo for wait_while"

    timeline = Timeline(
        CodeBlock(
            lambda participant: participant.var.set(
                "start_time", datetime.datetime.now()
            )
        ),
        wait_while(
            lambda participant: (
                (datetime.datetime.now() - participant.var.start_time).total_seconds()
                <= 4
            ),
            expected_wait=3,
            check_interval=0.5,
        ),
        CodeBlock(
            lambda participant: participant.var.set("end_time", datetime.datetime.now())
        ),
    )

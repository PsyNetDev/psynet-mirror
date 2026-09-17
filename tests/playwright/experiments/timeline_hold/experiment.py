import time

from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import AsyncCodeBlock, CodeBlock, PageMaker, Timeline


def finish_background_work(participant):
    time.sleep(3)
    participant.var.background_work_finished = True


class Exp(psynet.experiment.Experiment):
    label = "Timeline hold lifecycle"

    timeline = Timeline(
        InfoPage(
            "Submit this page to start background feedback processing.",
            time_estimate=1,
        ),
        CodeBlock(
            lambda participant: participant.var.set(
                "credit_before_hold", participant.time_credit
            )
        ),
        AsyncCodeBlock(
            finish_background_work,
            wait=True,
            expected_wait=3,
            check_interval=1.0,
        ),
        CodeBlock(
            lambda participant: participant.var.set(
                "hold_credit",
                participant.time_credit - participant.var.credit_before_hold,
            )
        ),
        PageMaker(
            lambda participant: InfoPage(
                Markup(
                    "Background feedback processing finished."
                    f"<span id='hold-credit'>{participant.var.hold_credit}</span>"
                    f"<span id='hold-metric'>{participant.total_wait_page_time}</span>"
                ),
                time_estimate=1,
            ),
            time_estimate=1,
        ),
    )

from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage, wait_while
from psynet.timeline import CodeBlock, PageMaker, Timeline


class Exp(psynet.experiment.Experiment):
    label = "Timeline hold timeout"

    timeline = Timeline(
        InfoPage("Start a timeline hold that will time out.", time_estimate=1),
        CodeBlock(
            lambda participant: participant.var.set(
                "credit_before_hold", participant.time_credit
            )
        ),
        wait_while(
            lambda: True,
            expected_wait=0.5,
            max_wait_time=1,
            check_interval=5,
            fail_on_timeout=False,
            fix_time_credit=True,
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
                    "The timeline hold timed out."
                    f"<span id='fixed-hold-credit'>{participant.var.hold_credit}</span>"
                ),
                time_estimate=1,
            ),
            time_estimate=1,
        ),
    )

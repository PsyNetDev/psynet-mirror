import psynet.experiment
from psynet.page import InfoPage, wait_while
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Timeline hold client behavior"

    timeline = Timeline(
        InfoPage(
            "Submit this page to start a hold that stays until the test finishes.",
            time_estimate=1,
        ),
        wait_while(
            lambda: True,
            expected_wait=5,
            max_wait_time=60,
            check_interval=5.0,
            fail_on_timeout=False,
        ),
        InfoPage(
            "The client-behavior hold should not reach this page.",
            time_estimate=1,
        ),
    )

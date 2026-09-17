import time

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import AsyncCodeBlock, Timeline


def finish_background_work(participant):
    time.sleep(2)
    participant.var.reload_hold_finished = True


class Exp(psynet.experiment.Experiment):
    label = "Timeline hold reload lifecycle"

    timeline = Timeline(
        InfoPage(
            "This page requires a full reload after its hold.",
            time_estimate=1,
            requires_full_page_reload=True,
            js_page_code=("window.holdReloadMarker = {pageUuid: window.pageUuid};"),
        ),
        AsyncCodeBlock(
            finish_background_work,
            wait=True,
            expected_wait=2,
            check_interval=5,
        ),
        InfoPage("The reload-required hold finished.", time_estimate=1),
    )

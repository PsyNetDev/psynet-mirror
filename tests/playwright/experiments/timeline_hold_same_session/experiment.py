import time

from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import AsyncCodeBlock, Timeline


def finish_background_work(participant):
    time.sleep(2)
    participant.var.same_session_hold_finished = True


class Exp(psynet.experiment.Experiment):
    label = "Timeline hold same-session lifecycle"

    timeline = Timeline(
        InfoPage(
            Markup(
                "<p id='hold-session-marker'>First session page</p>"
                "<button id='intentionally-disabled-response' "
                "class='response' disabled>Unavailable choice</button>"
            ),
            time_estimate=1,
            session_id="hold-session",
            contents={"step": 1},
            js_page_code="""
                window.holdSessionMessages = [];
                window.unityInstance = {
                    SendMessage: function (objectName, methodName, payload) {
                        window.holdSessionMessages.push({
                            objectName: objectName,
                            methodName: methodName,
                            payload: JSON.parse(payload),
                        });
                    },
                };
                psynet.trial.onEvent("responseEnable", function () {
                    document.getElementById(
                        "intentionally-disabled-response"
                    ).disabled = true;
                }, {priority: -1});
            """,
        ),
        AsyncCodeBlock(
            finish_background_work,
            wait=True,
            expected_wait=2,
            check_interval=5,
        ),
        InfoPage(
            Markup("<p id='hold-session-marker'>Second session page</p>"),
            time_estimate=1,
            session_id="hold-session",
            contents={"step": 2},
        ),
        InfoPage("Different-session finish page", time_estimate=1),
    )

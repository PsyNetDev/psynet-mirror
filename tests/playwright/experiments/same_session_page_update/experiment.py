from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline

SESSION_ID = "shared-session"


class Exp(psynet.experiment.Experiment):
    label = "Same-session page update test"

    timeline = Timeline(
        InfoPage(
            Markup("<p id='same-session-marker'>First same-session page</p>"),
            time_estimate=1,
            session_id=SESSION_ID,
            js_vars={
                "same_session_unity": {
                    "attributes": {
                        "session_id": SESSION_ID,
                        "is_unity_page": True,
                        "requires_full_page_reload": True,
                    },
                    "contents": {"step": 1, "label": "first"},
                }
            },
            js_page_modules=["/static/unity-stub-page.js"],
            contents={"step": 1, "label": "first"},
        ),
        InfoPage(
            Markup("<p id='same-session-marker'>Second same-session page</p>"),
            time_estimate=1,
            session_id=SESSION_ID,
            contents={"step": 2, "label": "second"},
        ),
        InfoPage("Different-session finish page", time_estimate=1),
    )

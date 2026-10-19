from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Broken page module bootstrap test"

    timeline = Timeline(
        InfoPage(
            Markup('<p id="broken-module-marker">Broken module page</p>'),
            time_estimate=1,
            js_page_modules=["/static/does-not-exist.js"],
        ),
    )

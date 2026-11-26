from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Page module with an invalid activate() result"

    timeline = Timeline(
        InfoPage(
            Markup('<p id="bad-result-marker">Bad result page</p>'),
            time_estimate=1,
            js_page_modules=["/static/returns-node.js"],
        ),
    )

from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Broken page dependency bootstrap test"

    timeline = Timeline(
        InfoPage(
            Markup('<p id="broken-dependency-marker">Broken dependency page</p>'),
            time_estimate=1,
            js_dependencies=["/static/does-not-exist.js"],
        ),
    )

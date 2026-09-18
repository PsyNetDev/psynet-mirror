from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Legacy JavaScript variable global lifecycle test"

    timeline = Timeline(
        InfoPage(
            Markup('<p id="js-var-page-marker">Alpha page</p>'),
            js_vars={"legacy_alpha": 1},
            time_estimate=1,
        ),
        InfoPage(
            Markup('<p id="js-var-page-marker">Beta page</p>'),
            js_vars={"legacy_beta": 2},
            time_estimate=1,
        ),
        InfoPage(
            Markup('<p id="js-var-page-marker">Descriptor page</p>'),
            js_vars={
                "nonconfigurable_global": 4,
                "restored_global": 3,
            },
            time_estimate=1,
        ),
        InfoPage(
            Markup('<p id="js-var-page-marker">Cleanup page</p>'),
            time_estimate=1,
        ),
    )

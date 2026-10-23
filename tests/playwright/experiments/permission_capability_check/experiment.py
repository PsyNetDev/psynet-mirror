from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.prescreen import BrowserCapabilityCheck
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Permission capability check test"
    browser_capabilities = {"microphone", "camera"}

    timeline = Timeline(
        BrowserCapabilityCheck(),
        InfoPage(
            Markup('<p id="capability-check-passed">Capability check passed</p>'),
            time_estimate=1,
        ),
    )

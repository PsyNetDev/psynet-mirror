from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Audio no prescreener test"
    browser_capabilities = {"audio_playback"}

    timeline = Timeline(
        InfoPage(
            Markup('<p id="page-loaded">Page loaded without prescreener</p>'),
            time_estimate=1,
        ),
    )

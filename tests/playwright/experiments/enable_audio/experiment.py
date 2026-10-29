from markupsafe import Markup

import psynet.experiment
from psynet.modular_page import AudioPrompt, ModularPage
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Enable audio test"

    timeline = Timeline(
        InfoPage(
            Markup('<p id="no-audio-page">This page has no audio.</p>'),
            time_estimate=1,
        ),
        ModularPage(
            "audio_page",
            AudioPrompt(
                "static/silence.wav",
                Markup('<p id="audio-page">This page plays audio.</p>'),
            ),
            time_estimate=1,
        ),
    )

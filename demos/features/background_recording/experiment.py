"""Optional camera recording alongside ordinary button answers.

The two pages deliberately share a label: each clip is keyed by its page UUID.
No page waits for media. Inspect Recording assets in the dashboard afterwards.
"""

import psynet.experiment
from psynet.consent import AudiovisualConsent
from psynet.modular_page import ModularPage, PushButtonControl, VideoRecordConfig
from psynet.page import InfoPage
from psynet.timeline import PageMaker, Timeline


def _choice(prompt):
    """Build a button page with optional camera capture."""
    return ModularPage(
        "judgment",
        prompt,
        PushButtonControl(["Yes", "No"]),
        time_estimate=5,
        background_recording=VideoRecordConfig(source="camera"),
    )


class Exp(psynet.experiment.Experiment):
    label = "Optional background recording"
    timeline = Timeline(
        AudiovisualConsent(time_estimate=5),
        _choice("First judgment: choose Yes or No."),
        PageMaker(
            lambda: _choice("Second judgment: choose Yes or No."), time_estimate=5
        ),
        InfoPage(
            "Independent page reached. Your answers are saved; recordings may still be uploading.",
            time_estimate=2,
        ),
    )

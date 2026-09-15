from markupsafe import Markup

import psynet.experiment
from psynet.consent import MainConsent
from psynet.page import InfoPage
from psynet.timeline import MediaSpec, Timeline


class _MainConsentWithFooter(MainConsent):
    class MainConsentPage(MainConsent.MainConsentPage):
        def __init__(self, time_estimate=30):
            super().__init__(time_estimate=time_estimate)
            self.show_early_exit_button = True


def _media_page(label, marker_id, show_early_exit_button):
    return InfoPage(
        Markup(
            f"""
            <p id="{marker_id}">{label}</p>
            <button type="button" class="btn btn-primary wait-for-media-load"
                    onclick="psynet.audio.bier.play();">
                Play bier
            </button>
            """
        ),
        time_estimate=1,
        media=MediaSpec(audio={"bier": "/static/bier.wav"}),
        show_early_exit_button=show_early_exit_button,
    )


class Exp(psynet.experiment.Experiment):
    label = "Media download progress bar check"

    timeline = Timeline(
        InfoPage(
            Markup("<p id='intro-marker'>Intro without media</p>"),
            time_estimate=1,
        ),
        _MainConsentWithFooter(),
        _media_page(
            "First media page",
            "first-media-marker",
            show_early_exit_button=True,
        ),
        _media_page(
            "Second media page",
            "second-media-marker",
            show_early_exit_button=False,
        ),
        InfoPage(
            Markup("<p id='finish-marker'>Done</p>"),
            time_estimate=1,
        ),
    )

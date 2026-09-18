from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import MediaSpec, Timeline


def _media_page(label, marker_id):
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
    )


class Exp(psynet.experiment.Experiment):
    label = "Media download progress bar check"

    timeline = Timeline(
        InfoPage(
            Markup("<p id='intro-marker'>Intro without media</p>"),
            time_estimate=1,
        ),
        _media_page("First media page", "first-media-marker"),
        _media_page("Second media page", "second-media-marker"),
        InfoPage(
            Markup("<p id='finish-marker'>Done</p>"),
            time_estimate=1,
        ),
    )

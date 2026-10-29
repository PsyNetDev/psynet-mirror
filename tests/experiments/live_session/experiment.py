"""The test experiment for live sessions. Its page opens the page's websocket."""

from dominate import tags

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Live session test experiment"

    timeline = Timeline(
        InfoPage(
            tags.p("Connecting...", id="socket-status"),
            time_estimate=5,
            js_page_code=(
                "psynet.websocket.onConnect(() => {"
                ' root.querySelector("#socket-status").textContent = "Connected";'
                " });"
            ),
        ),
    )

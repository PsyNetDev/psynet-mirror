from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Legacy page JavaScript test"

    timeline = Timeline(
        InfoPage(
            Markup(
                """
                <p id="legacy-script-marker">Legacy scripts page</p>
                <p id="legacy-global-marker">unset</p>
                """
            ),
            time_estimate=1,
            # Deprecated scripts/js_links force reload and raise under inplace
            # unless the page explicitly opts out of the SPA migration error.
            requires_full_page_reload=True,
            scripts=[
                "var legacyGlobal = 'from-scripts';",
                "document.getElementById('legacy-global-marker').textContent = "
                "legacyGlobal;",
            ],
            js_links=["/static/legacy-page-link.js"],
        ),
        InfoPage(
            Markup("<p id='legacy-checkpoint-marker'>Legacy checkpoint page</p>"),
            time_estimate=1,
            js_page_code="""
                document.getElementById("legacy-checkpoint-marker").dataset.legacyGlobal =
                    typeof legacyGlobal === "undefined" ? "missing" : legacyGlobal;
                document.getElementById("legacy-checkpoint-marker").dataset.legacyLinks =
                    String(window.__legacyLinkActivations || 0);
            """,
        ),
        InfoPage(
            Markup("<p id='legacy-finish-marker'>Legacy finish page</p>"),
            time_estimate=1,
        ),
    )

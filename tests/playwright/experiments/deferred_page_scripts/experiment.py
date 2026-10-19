from markupsafe import Markup

import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Page, Timeline

MANAGED_JAVASCRIPT = {
    "js_dependencies": ["/static/page-lifecycle-dependency.js"],
    "js_page_modules": [
        "/static/page-lifecycle-first.js",
        "/static/page-lifecycle-second.js",
    ],
}


class CustomStylesheetPage(Page):
    def __init__(self):
        super().__init__(
            label="custom_stylesheet",
            template_fragment_path="templates/custom-stylesheet-page.html",
            save_answer=False,
            time_estimate=1,
            js_page_modules=["/static/custom-style-page.js"],
            css_links=["/static/custom-stylesheet-page.css"],
        )

    def get_bot_response(self, experiment, bot):
        return None


class Exp(psynet.experiment.Experiment):
    label = "In-place timeline transition lifecycle test"

    timeline = Timeline(
        InfoPage(
            Markup(
                """
                <p>First page</p>
                <p id="managed-javascript-marker">Managed JavaScript has not activated</p>
                <script>
                    window.__psynetManagedDependencyAvailableInBody =
                        window.__psynetManagedJavascript?.dependencyLoads === 1;
                </script>
                <script src="/static/redeclared-body-library.js"></script>
                """
            ),
            time_estimate=1,
            js_page_code="""
                window.__pageCodeLifecycle = window.__pageCodeLifecycle || [];
                window.__pageCodeLifecycle.push("activate:first");
                return function cleanup() {
                    window.__pageCodeLifecycle.push("cleanup:first");
                };
            """,
            **MANAGED_JAVASCRIPT,
        ),
        InfoPage(
            Markup(
                """
                <p>Embedded script lifecycle page</p>
                <p id="managed-javascript-marker">Managed JavaScript has not activated</p>
                <script>
                    window.__psynetManagedDependencyAvailableInBody =
                        window.__psynetManagedJavascript?.dependencyLoads === 1;
                </script>
                <script src="/static/redeclared-body-library.js"></script>
                <p id="body-library-load-count-marker">
                    Body library load count marker
                </p>
                <script>
                    document.getElementById(
                        "body-library-load-count-marker"
                    ).dataset.loadCount = window.__psynetBodyLibraryLoads;
                </script>
                <p
                    id="deferred-trial-construct-marker"
                    data-trial-construct-handler-ran="false"
                >
                    trialConstruct handler has not run
                </p>
                <p id="deferred-css-marker">Inline partial CSS marker</p>
                """
            ),
            time_estimate=1,
            js_dependencies=MANAGED_JAVASCRIPT["js_dependencies"],
            js_page_code="""
                window.__pageCodeLifecycle = window.__pageCodeLifecycle || [];
                window.__pageCodeLifecycle.push("activate:second");
                return function cleanup() {
                    window.__pageCodeLifecycle.push("cleanup:second");
                };
            """,
            js_page_modules=[
                *MANAGED_JAVASCRIPT["js_page_modules"],
                "/static/deferred-script.js",
            ],
            css_links=["/static/deferred-page-scripts.css"],
        ),
        CustomStylesheetPage(),
        InfoPage(
            Markup(
                """
                <p>Repeated linked page module lifecycle page</p>
                <p
                    id="deferred-trial-construct-marker"
                    data-trial-construct-handler-ran="false"
                >
                    repeated trialConstruct handler has not run
                </p>
                """
            ),
            time_estimate=1,
            js_page_modules=["/static/deferred-script.js"],
        ),
        InfoPage(
            Markup(
                """
                <p>Cleanup page</p>
                <p id="custom-stylesheet-marker">Unstyled cleanup marker</p>
                """
            ),
            time_estimate=1,
        ),
        InfoPage(
            Markup(
                """
                <p id="shell-stylesheet-marker">Shell stylesheet page</p>
                """
            ),
            time_estimate=1,
            css_links=["/static/shell-stylesheet-page.css"],
        ),
        InfoPage(
            Markup(
                """
                <p>Shell stylesheet cleanup page</p>
                """
            ),
            time_estimate=1,
        ),
    )

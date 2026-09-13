"""
Exercises the participant-facing layout primitives that the structural
invariants check: plain prose, option rows, push buttons, a tall graphic,
and a landscape graphic that would outgrow the content surface if sized
only against the window.
"""

# pylint: disable=unused-import,abstract-method,unused-argument,no-member

from markupsafe import Markup

import psynet.experiment
from psynet.graphics import Circle, Frame, GraphicPrompt, Path, Rectangle
from psynet.modular_page import (
    ModularPage,
    PushButtonControl,
    RadioButtonControl,
)
from psynet.page import InfoPage
from psynet.timeline import Timeline

LONG_TEXT = Markup(
    "<p>Invariant check: deliberately long page.</p>"
    + "".join(
        f"<p>Filler paragraph {i} used to push the page well beyond the "
        "height of the browser window.</p>"
        for i in range(1, 25)
    )
)


class Exp(psynet.experiment.Experiment):
    label = "Participant page invariants"

    timeline = Timeline(
        InfoPage(
            "Invariant check: plain information page.",
            time_estimate=1,
        ),
        ModularPage(
            "radio",
            prompt="Invariant check: radio options.",
            control=RadioButtonControl(
                ["alpha", "beta", "gamma"],
                ["Alpha", "Beta", "Gamma"],
                name="letters",
            ),
            time_estimate=1,
        ),
        ModularPage(
            "push",
            prompt="Invariant check: push buttons.",
            control=PushButtonControl(["left", "right"], ["Left", "Right"]),
            time_estimate=1,
        ),
        ModularPage(
            "graphic",
            prompt=GraphicPrompt(
                text="Invariant check: tall graphic.",
                dimensions=[100, 100],
                viewport_width=0.6,
                frames=[
                    Frame(
                        [
                            Path(
                                "triangle",
                                "M50,10 L10,50 L90,50 z",
                                attributes={"fill": "red"},
                            ),
                            Circle(
                                "circle",
                                20,
                                70,
                                radius=5,
                                attributes={"fill": "blue"},
                            ),
                        ]
                    )
                ],
            ),
            time_estimate=1,
        ),
        ModularPage(
            "landscape_graphic",
            prompt=GraphicPrompt(
                text="Invariant check: landscape graphic.",
                dimensions=[16, 9],
                viewport_width=0.9,
                frames=[
                    Frame(
                        [
                            Rectangle(
                                "panel",
                                0,
                                0,
                                width=16,
                                height=9,
                                attributes={"fill": "#dfe5ee"},
                            )
                        ]
                    )
                ],
            ),
            time_estimate=1,
        ),
        # Declares that scrolling is expected, so the reachability check is
        # waived; the permanent-occlusion check still applies.
        InfoPage(LONG_TEXT, time_estimate=1, expect_scrolling=True),
        # Option panels grow with their rows rather than scrolling internally,
        # so a long list has to declare its scrolling like any other tall page.
        ModularPage(
            "long_radio",
            prompt="Invariant check: long radio list.",
            control=RadioButtonControl(
                [f"row_{i}" for i in range(1, 17)],
                [f"Row {i}" for i in range(1, 17)],
                name="rows",
            ),
            time_estimate=1,
            expect_scrolling=True,
        ),
    )

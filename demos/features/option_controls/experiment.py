import psynet.experiment
from psynet.modular_page import (
    CheckboxControl,
    DropdownControl,
    ModularPage,
    PushButtonControl,
    RadioButtonControl,
)
from psynet.timeline import Timeline
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Option controls demo"

    timeline = Timeline(
        ModularPage(
            "response",
            prompt="This is an example of a push button page with vertically arranged buttons.",
            control=PushButtonControl(
                ["red", "green", "blue"],
                ["Red", "Green", "Blue"],
            ),
            time_estimate=5,
        ),
        ModularPage(
            "response",
            prompt="This is an example of a push button page with horizontally arranged buttons.",
            control=PushButtonControl(
                ["red", "green", "blue"],
                ["Red", "Green", "Blue"],
                arrange_vertically=False,
            ),
            time_estimate=5,
        ),
        ModularPage(
            "response",
            prompt="This is an example of a dropdown page.",
            control=DropdownControl(
                ["cirrus", "stratus", "cumulus"],
                ["Cirrus", "Stratus", "Cumulus"],
                name="clouds",
            ),
            time_estimate=5,
        ),
        ModularPage(
            "response",
            prompt="This is an example of a checkbox page with vertically arranged checkboxes.",
            control=CheckboxControl(
                ["sneakers", "sandals", "clogs"],
                ["Sneakers", "Sandals", "Clogs"],
                name="shoes",
            ),
            time_estimate=5,
        ),
        ModularPage(
            "response",
            prompt="This is an example of a checkbox page with horizontally arranged checkboxes forcing an answer and a 'Reset' button.",
            control=CheckboxControl(
                ["sneakers", "sandals", "clogs"],
                ["Sneakers", "Sandals", "Clogs"],
                name="shoes",
                arrange_vertically=False,
                force_selection=True,
                show_reset_button="always",
            ),
            time_estimate=5,
        ),
        ModularPage(
            "response",
            prompt="This is an example of a radiobutton page with vertically arranged radiobuttons and a 'Reset' button displayed only on selection.",
            control=RadioButtonControl(
                ["maple", "cottonwood", "alder"],
                ["Maple", "Cottonwood", "Alder"],
                name="trees",
                arrange_vertically=True,
                show_reset_button="on_selection",
            ),
            time_estimate=5,
        ),
        ModularPage(
            "response",
            prompt="This is an example of a radiobutton page with horizontally arranged radiobuttons without forcing an answer.",
            control=RadioButtonControl(
                ["maple", "cottonwood", "alder"],
                ["Maple", "Cottonwood", "Alder"],
                name="trees",
                arrange_vertically=False,
                force_selection=False,
            ),
            time_estimate=5,
        ),
        # A list too long for the window grows the page instead of scrolling
        # inside the control, so the page declares expect_scrolling.
        ModularPage(
            "response",
            prompt="This is an example of a radiobutton page with more options than fit the window.",
            control=RadioButtonControl(
                [f"option_{i}" for i in range(1, 17)],
                [f"Option {i}" for i in range(1, 17)],
                name="long_list",
            ),
            time_estimate=5,
            expect_scrolling=True,
        ),
    )

import json

from markupsafe import Markup

import psynet.experiment
from psynet.modular_page import ModularPage, SliderControl
from psynet.page import DebugResponsePage
from psynet.timeline import Timeline, join


def print_dict(x):
    return "<pre>" + json.dumps(x, indent=4) + "</pre>"


def make_example(args):
    prompt = Markup(
        f"""
        Raw slider value is <strong id="slider-raw-value">NA</strong> <br>
        Output slider value is <strong id="slider-output-value">NA</strong>
        (phase = <strong id="phase">NA</strong>, random wrap = <strong id="random-wrap">NA</strong>)
        {print_dict(args)}
        """
    )

    return join(
        ModularPage(
            "slider_page",
            prompt,
            control=SliderControl(**args),
            time_estimate=5,
            js_page_modules=["/static/slider-debug.js"],
        ),
        DebugResponsePage(),
    )


example_1 = {
    "start_value": 15,
    "min_value": 10,
    "max_value": 20,
    "n_steps": 11,
    "snap_values": None,
    "minimal_interactions": 3,
    "random_wrap": False,
}

example_2 = {
    "start_value": 15,
    "min_value": 10,
    "max_value": 20,
    "n_steps": 11,
    "snap_values": None,
    "minimal_interactions": 3,
    "random_wrap": True,
}
# TODO reverse direction

example_3 = {
    "start_value": 10,
    "min_value": 5,
    "max_value": 15,
    "n_steps": 100,
    "snap_values": None,
    "minimal_interactions": 3,
    "input_type": "circular_slider",
    "random_wrap": False,
}

example_4 = {
    "start_value": 10,
    "min_value": 5,
    "max_value": 15,
    "n_steps": 100,
    "snap_values": None,
    "minimal_interactions": 3,
    "input_type": "circular_slider",
    "random_wrap": True,
}

example_5 = {
    "start_value": 0.5,
    "min_value": 0.1,
    "max_value": 0.9,
    "n_steps": 48,
    "snap_values": None,
    "minimal_interactions": 5,
    "input_type": "circular_slider",
    "random_wrap": True,
}

example_6 = {
    "start_value": 15,
    "min_value": 10,
    "max_value": 20,
    "n_steps": 1000,
    "snap_values": [10, 11, 12, 13, 14, 15, 20],
    "minimal_interactions": 0,
}


class CustomExp(psynet.experiment.Experiment):
    label = "Slider demo"
    timeline = Timeline(
        make_example(example_1),
        make_example(example_2),
        make_example(example_3),
        make_example(example_4),
        make_example(example_5),
        make_example(example_6),
    )

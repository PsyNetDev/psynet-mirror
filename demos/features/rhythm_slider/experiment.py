import json

import numpy as np
from markupsafe import Markup, escape

import psynet.experiment
from psynet.modular_page import AudioSliderControl, ModularPage
from psynet.page import DebugResponsePage
from psynet.timeline import MediaSpec, Timeline, join
from psynet.utils import get_logger

logger = get_logger()


GRANULARITY_SLIDER = 9  # set the number of audio files per slider


def print_dict(x, **kwargs):
    return (
        "<pre style='overflow: scroll; max-height: 200px'>"
        + json.dumps(x, indent=4)
        + "</pre>"
    )


def new_example(
    description, **kwargs
):  # TODO: Peter, rewrite this section to use the new PsyNet event scheduler
    assert len(kwargs["sound_locations"]) == GRANULARITY_SLIDER
    media = MediaSpec(
        audio={
            "batch": {
                "url": "/static/audio/batch.rhythms",
                "ids": [_id for _id, _ in kwargs["sound_locations"].items()],
                "type": "batch",
            }
        }
    )

    prompt = Markup(
        f"""
        {escape(description)}
        {print_dict(kwargs)}
        <p>
            Raw slider value is <strong id="slider-raw-value">NA</strong> <br>
            Output slider value is <strong id="slider-output-value">NA</strong>
            (phase = <strong id="phase">NA</strong>, random wrap = <strong id="random-wrap">NA</strong>)
        </p>
        <p>
            Closest audio: <strong id="slider-audio">NA</strong>
        </p>
        """
    )
    time_estimate = kwargs.pop("time_estimate")

    return join(
        ModularPage(
            "slider_page",
            prompt,
            control=AudioSliderControl(audio=media.audio, **kwargs),
            media=media,
            time_estimate=time_estimate,
            js_page_modules=["/static/slider-debug.js"],
        ),
        DebugResponsePage(),
    )


class CustomExp(psynet.experiment.Experiment):
    label = "Demo rhythm slider"

    ids = [f"rhythm_{i}" for i in range(GRANULARITY_SLIDER)]
    ratios = np.linspace(0.1, 0.9, num=GRANULARITY_SLIDER)

    timeline = Timeline(
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                Normal slider without wrapping. There is a 2-interval rhythm
                located at each integer position. The dimension manipulated is the ratio
                of the rhythm (from 0.1 to 0.9). The user must wait 2 seconds and
                interact 3 times with the slider before they are allowed to submit their response.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                Same example with slider reversed.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            reverse_scale=True,
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                This time the slider is disabled while the audio is playing,
                so participants are forced to listen the stimulus before moving the slider.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            reverse_scale=True,
            disable_slider_on_change="while_playing",
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                Now, we use random wrapping to overcome boundary issues: i.e.,
                the range of the slider is wrapped (e.g., min-max-max-min)
                and the phase to initialise the wrapping is randomised.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            random_wrap=True,
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                Same example now using both wrapping and disable slider while playing.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            random_wrap=True,
            disable_slider_on_change="while_playing",
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                In this example we show how to use a circular slider without wrapping.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            random_wrap=False,
            input_type="circular_slider",
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                Same example but this time we disable the slider while the audio is playing. For now,
                the circular slider is hidden while the audio is playing. This can improve by adding
                a transparent div on top of the slider instead.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            random_wrap=False,
            input_type="circular_slider",
            disable_slider_on_change="while_playing",
        ),
        new_example(
            Markup(
                """
                <h3>Rhythm Slider</h3>
                Now we use the circular slider with random wrapping.
                """
            ),
            sound_locations=dict(zip(ids, [i for i in ratios])),
            snap_values=None,
            start_value=0.5,
            min_value=0.1,
            max_value=0.9,
            autoplay=True,
            minimal_time=2,
            minimal_interactions=3,
            time_estimate=5,
            random_wrap=True,
            input_type="circular_slider",
        ),
    )

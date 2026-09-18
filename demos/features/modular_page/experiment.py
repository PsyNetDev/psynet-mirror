# pylint: disable=unused-import,abstract-method,unused-argument,no-member
import random
from typing import Union

from markupsafe import Markup

import psynet.experiment
from psynet.modular_page import (
    AudioPrompt,
    Control,
    FrameSliderControl,
    ModularPage,
    MultiRatingControl,
    Prompt,
    PushButtonControl,
    RatingControl,
    RatingScale,
    TimedPushButtonControl,
    VideoSliderControl,
)
from psynet.page import DebugResponsePage
from psynet.timeline import MediaSpec, Timeline
from psynet.utils import NoArgumentProvided


class HelloPrompt(Prompt):
    macro = "with_hello"
    external_template = "custom-prompts.html"

    def __init__(
        self,
        username: str,
        text: Union[None, str, Markup] = None,
        text_align: str = "left",
    ):
        super().__init__(text=text, text_align=text_align)
        self.username = username


class ColorText(Control):
    macro = "color_text_area"
    external_template = "custom-controls.html"

    def __init__(self, color, bot_response=NoArgumentProvided):
        super().__init__(bot_response=bot_response)
        self.color = color

    @property
    def metadata(self):
        return {"color": self.color}

    def get_bot_response(self, experiment, bot, page, prompt):
        return "Hello, I am a bot!"

    def get_js_page_modules(self):
        return ["/static/color-text.js"]


video_slider_media_spec = MediaSpec()
video_slider_media_spec.add(
    "video",
    {
        "slider_stimuli": {
            "url": "/static/video/video-slider.batch",
            "ids": [f"slider_stimulus_{x}" for x in range(25)],
            "type": "batch",
        }
    },
)


class Exp(psynet.experiment.Experiment):
    label = "Modular page demo"

    timeline = Timeline(
        ModularPage(
            "text", prompt="This is an example of a simple text page.", time_estimate=5
        ),
        ModularPage(
            "text",
            prompt=Markup(
                "This is an example of a text page with some <strong>simple formatting</strong>."
            ),
            time_estimate=5,
        ),
        ModularPage(
            "rating",
            prompt=Prompt(
                "This is an example of the RatingControl. Use it to rate this page.",
            ),
            control=RatingControl(
                values=5,
                min_description="Rubbish",
                max_description="Great",
            ),
            time_estimate=5,
        ),
        DebugResponsePage(),
        ModularPage(
            "multirating",
            "This is an example of the MultiRatingControl.",
            MultiRatingControl(
                RatingScale(
                    "happiness",
                    values=5,
                    title="How happy are you feeling?",
                    min_description="Very unhappy",
                    max_description="Very happy",
                    required=False,
                ),
                RatingScale(
                    "energy",
                    values=5,
                    title="How energetic are you feeling?",
                    min_description="Very tired",
                    max_description="Very energetic",
                ),
            ),
            time_estimate=10,
        ),
        DebugResponsePage(),
        ModularPage(
            "response",
            prompt=AudioPrompt(
                audio="/static/audio/bier.wav",
                text="Here is an example of an audio prompt combined with a push button control.",
            ),
            control=PushButtonControl(["Response A", "Response B"]),
            time_estimate=5,
        ),
        DebugResponsePage(),
        ModularPage(
            "timed_push_button",
            AudioPrompt(
                audio="https://headphone-check.s3.amazonaws.com/funk_game_loop.wav",
                text="""
            This page illustrates the timed push button control combined with an audio prompt.
            """,
            ),
            TimedPushButtonControl(choices=["A", "B", "C"], arrange_vertically=False),
            time_estimate=5,
        ),
        DebugResponsePage(),
        ModularPage(
            "frame_slider",
            prompt="This is an example of a frame slider that cycles through the frames of one single video.",
            control=FrameSliderControl(
                url="https://psynet.s3.amazonaws.com/video-slider.mp4",
                file_type="mp4",
                width="400px",
                height="400px",
                reverse_scale=True,
                directional=False,
            ),
            time_estimate=5,
        ),
        DebugResponsePage(),
        ModularPage(
            "video_slider",
            prompt=Prompt(
                "This is an example of a video slider page where every slider position is linked to a separate video.",
                text_align="center",
            ),
            control=VideoSliderControl(
                start_value=random.sample(range(256), 1)[0],
                min_value=0,
                max_value=255,
                slider_media={
                    "slider_stimuli": {
                        "url": "/static/video/video-slider.batch",
                        "ids": [f"slider_stimulus_{x}" for x in range(25)],
                        "type": "batch",
                    }
                },
                media_locations={
                    "slider_stimulus_0": 0.0,
                    "slider_stimulus_1": 10.625,
                    "slider_stimulus_2": 21.25,
                    "slider_stimulus_3": 31.875,
                    "slider_stimulus_4": 42.5,
                    "slider_stimulus_5": 53.125,
                    "slider_stimulus_6": 63.75,
                    "slider_stimulus_7": 74.375,
                    "slider_stimulus_8": 85.0,
                    "slider_stimulus_9": 95.625,
                    "slider_stimulus_10": 106.25,
                    "slider_stimulus_11": 116.875,
                    "slider_stimulus_12": 127.5,
                    "slider_stimulus_13": 138.125,
                    "slider_stimulus_14": 148.75,
                    "slider_stimulus_15": 159.375,
                    "slider_stimulus_16": 170.0,
                    "slider_stimulus_17": 180.625,
                    "slider_stimulus_18": 191.25,
                    "slider_stimulus_19": 201.875,
                    "slider_stimulus_20": 212.5,
                    "slider_stimulus_21": 223.125,
                    "slider_stimulus_22": 233.75,
                    "slider_stimulus_23": 244.375,
                    "slider_stimulus_24": 255.0,
                },
                # width="400px",
                # height="400px",
                autoplay=True,
                disable_slider_on_change="while_playing",
                n_steps="n_media",
                input_type="HTML5_range_slider",
                random_wrap=False,
                reverse_scale=False,
                directional=False,
                snap_values="media_locations",
                minimal_time=0,
                minimal_interactions=1,
            ),
            media=video_slider_media_spec,
            time_estimate=5,
        ),
        DebugResponsePage(),
        ModularPage(
            "example_hello",
            prompt=HelloPrompt(
                username="stranger",
                text="""
                    This is an example of a custom prompt that adds 'Hello' to every page.
                    The custom prompt is defined in the class 'HelloPrompt' and the template
                    'custom-prompts.html'. Note that the template inherits from the built-in
                    'prompt.simple' macro as defined in PsyNet's 'prompt.html' file.
                    """,
            ),
            time_estimate=5,
        ),
        ModularPage(
            "example_text_input",
            prompt=Prompt(
                """\
                This is an example of a custom control interface, defined in the class
                'ColorText' and the template 'custom-controls.html'.
                Note how you can customise the background color by changing the input
                to 'ColorText'.\
            """
            ),
            control=ColorText("aquamarine"),
            time_estimate=5,
        ),
        DebugResponsePage(),
    )

import json

from markupsafe import Markup, escape

import psynet.experiment
from psynet.modular_page import MediaSliderControl, ModularPage
from psynet.page import DebugResponsePage
from psynet.timeline import MediaSpec, Timeline, join

N_AUDIO_LOCATIONS = 472
N_VIDEO_LOCATIONS = 17


def print_dict(x, **kwargs):
    return (
        "<pre style='overflow: scroll; max-height: 200px'>"
        + json.dumps(x, indent=4)
        + "</pre>"
    )


def new_example(description, **kwargs):
    if "modality" not in kwargs.keys():
        kwargs["modality"] = "audio"  # Default modality is audio

    if kwargs["modality"] == "audio":
        assert len(kwargs["media_locations"]) == N_AUDIO_LOCATIONS
        media = MediaSpec(
            audio={
                "batch": {
                    "url": "/static/stimuli/audio.batch",
                    "ids": [_id for _id, _ in kwargs["media_locations"].items()],
                    "type": "batch",
                }
            }
        )
        slider_media = media.audio
    elif kwargs["modality"] == "video":
        assert len(kwargs["media_locations"]) == N_VIDEO_LOCATIONS
        media = MediaSpec(
            video={
                "batch": {
                    "url": "/static/stimuli/video.batch",
                    "ids": [_id for _id, _ in kwargs["media_locations"].items()],
                    "type": "batch",
                }
            }
        )
        slider_media = media.video
    else:
        raise NotImplementedError(f"Modality {kwargs['modality']} not implemented")
    prompt = f"{escape(description)} {print_dict(kwargs)}"
    prompt += """
    <p>
            Raw slider value is <strong id="slider-raw-value">NA</strong> <br>
            Output slider value is <strong id="slider-output-value">NA</strong>
            (phase = <strong id="phase">NA</strong>, random wrap = <strong id="random-wrap">NA</strong>)
        </p>
        <p>
            Just played <strong id="slider-audio">NA</strong>
        </p>
        """
    prompt = Markup(prompt)
    time_estimate = kwargs.pop("time_estimate")

    return join(
        ModularPage(
            "slider_page",
            prompt,
            # No need to specify modality, as it is already in kwargs
            control=MediaSliderControl(slider_media=slider_media, **kwargs),
            media=media,
            time_estimate=time_estimate,
            js_page_modules=["/static/slider-debug.js"],
            css=[
                """
                .video {
                    width: 256px;
                    height: 256px;
                    margin: 20px auto;
                }
                """
            ],
        ),
        DebugResponsePage(),
    )


class CustomExp(psynet.experiment.Experiment):
    label = "Simple multimedia slider"

    audio_ids = [f"audio_{i}" for i in range(N_AUDIO_LOCATIONS)]
    video_ids = [f"video_{i}" for i in range(N_VIDEO_LOCATIONS)]

    video_locations = dict(zip(video_ids, [i for i in range(N_VIDEO_LOCATIONS)]))
    sound_locations = dict(zip(audio_ids, [i for i in range(N_AUDIO_LOCATIONS)]))

    timeline = Timeline(
        new_example(
            """
            Simple video example where no slider snapping is performed. There is one stimulus
            located at each integer position. The user must wait 2 seconds before
            they are allowed to submit their response.
            """,
            media_locations=video_locations,
            modality="video",
            snap_values=None,
            start_value=0,
            min_value=0,
            max_value=N_VIDEO_LOCATIONS - 1,
            autoplay=True,
            minimal_time=2,
            time_estimate=5,
        ),
        new_example(
            """
            Same example but for audio
            """,
            media_locations=sound_locations,
            # You should explicitly specify modality, although for this example audio it is the default modality
            modality="audio",
            snap_values=None,
            start_value=0,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_time=2,
            time_estimate=5,
        ),
        new_example(
            """
            Same example with wrapping, i.e., then slider is wrapped twice so that there are no boundary jumps.
            """,
            media_locations=sound_locations,
            snap_values=None,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_time=2,
            time_estimate=5,
            random_wrap=True,
        ),
        new_example(
            """
            Example with circular slider and wrapping.
            """,
            media_locations=sound_locations,
            snap_values=None,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_time=2,
            time_estimate=5,
            random_wrap=True,
            input_type="circular_slider",
        ),
        new_example(
            """
            We come back to the simple example (without wrapping), but this
            with slider snapping to sound locations
            (as close as can be achieved given the underlying step size of the slider).
            """,
            media_locations=sound_locations,
            snap_values="media_locations",
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_interactions=3,
            time_estimate=5,
        ),
        new_example(
            "Same example but with slider snapping to deciles.",
            media_locations=sound_locations,
            snap_values=11,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_interactions=3,
            time_estimate=5,
        ),
        new_example(
            "Same example but where the slider can only be dragged through deciles.",
            media_locations=sound_locations,
            n_steps=11,
            snap_values=11,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_interactions=3,
            time_estimate=5,
        ),
        new_example(
            "Same example but where the slider can only be dragged through sound locations.",
            media_locations=sound_locations,
            snap_values=None,
            n_steps="n_media",
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_interactions=3,
            time_estimate=5,
        ),
        new_example(
            "Same example with non-directional slider.",
            media_locations=sound_locations,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_interactions=1,
            time_estimate=5,
            directional=False,
        ),
        new_example(
            "Same example with slider reversed.",
            media_locations=sound_locations,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=True,
            minimal_interactions=1,
            time_estimate=5,
            reverse_scale=True,
        ),
        new_example(
            "Same example with reversed non-directional slider.",
            media_locations=sound_locations,
            start_value=200,
            min_value=0,
            max_value=471,
            autoplay=N_AUDIO_LOCATIONS - 1,
            minimal_interactions=1,
            time_estimate=5,
            reverse_scale=True,
            directional=False,
        ),
        new_example(
            "Without reversal, with non-integer sound locations.",
            media_locations=dict(zip(audio_ids, [100 + i / 3 for i in range(472)])),
            start_value=200,
            min_value=100,
            max_value=260,
            autoplay=True,
            minimal_interactions=1,
            time_estimate=5,
        ),
        new_example(
            "Without autoplay, without minimal interactions.",
            media_locations=sound_locations,
            snap_values=None,
            start_value=200,
            min_value=0,
            max_value=N_AUDIO_LOCATIONS - 1,
            autoplay=False,
            minimal_interactions=0,
            time_estimate=5,
        ),
    )

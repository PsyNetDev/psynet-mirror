# pylint: disable=unused-import,abstract-method,unused-argument,no-member
import math
import urllib

import numpy as np
from markupsafe import Markup

from psynet.modular_page import ImagePrompt
from psynet.timeline import Event, ProgressDisplay, ProgressStage
from psynet.trial import ChainNode, ChainTrial
from psynet.trial.create_and_rate import CreateTrialMixin, RateOrSelectTrialMixin


def readlines(filename):
    with open(filename, "r") as f:
        lines = f.readlines()
    return [line.replace("\n", "") for line in lines]


# Make sure all images are used
main_experiment_urls = [
    "static/" + urllib.parse.quote(file) for file in readlines("robot_names.txt")
]


def prepare_media_events(
    media_type, media_keys, media_duration, base_label, stage_colors
):
    assert media_type in ["audio", "video"]

    # Prepare events and stages
    # disable all buttons before start
    events = {
        "hideButtons": Event(
            is_triggered_by="trialStart",
            js="document.getElementsByClassName('push-button-container')[0].hidden = true",
        )
    }
    stages = []
    time_past = 0
    count = 0
    for idx, media_key in enumerate(media_keys):
        # Alternate colors
        color_idx = count % len(stage_colors)
        color = stage_colors[color_idx]
        label = f"{base_label} {idx + 1}"
        stages.append(
            ProgressStage(media_duration, Markup(f"""Listen to {label}"""), color)
        )

        media_key = media_keys[idx]
        key = "play_" + media_key
        events[key] = Event(
            is_triggered_by="trialStart",
            delay=time_past,
            js="psynet."
            + media_type
            + "."
            + media_key.replace(" ", "_").lower()
            + ".play()",
        )
        time_past += media_duration
        count += 1

    # enable the buttons
    events["showButtons"] = Event(
        is_triggered_by="trialStart",
        delay=time_past,
        js="document.getElementsByClassName('push-button-container')[0].hidden = false",
    )
    progress_display = ProgressDisplay(stages=stages)
    return events, progress_display


def prepare_audio_events(
    keys, expected_duration, base_label="Recording", stage_colors=["blue", "red"]
):
    return prepare_media_events(
        "audio", keys, expected_duration, base_label, stage_colors
    )


def get_target_gibbs_answer(target):
    if issubclass(target.__class__, ChainNode):
        definition = target.definition
        vector = definition["vector"]
        active_index = definition["active_index"]
        return vector[active_index]
    elif issubclass(target.__class__, ChainTrial):
        return target.answer


def find_nearest(array, value):
    idx = np.searchsorted(array, value, side="left")
    if idx > 0 and (
        idx == len(array)
        or math.fabs(value - array[idx - 1]) < math.fabs(value - array[idx])
    ):
        return array[idx - 1]
    else:
        return array[idx]


class RobotVoicePrompt(ImagePrompt):
    def get_css_links(self):
        return ["/static/robot-voice-prompt.css"]


def get_prompt(trial):
    if issubclass(trial.__class__, CreateTrialMixin):
        prompt = (
            "Adjust the slider to make the voice match the robot as best as you can"
        )
    elif issubclass(trial.__class__, RateOrSelectTrialMixin):
        prompt = "How well does the voice match the robot?"
    else:
        raise ValueError(f"Unknown class type: {trial.__class__}")
    return RobotVoicePrompt(
        trial.context["img_url"], Markup(prompt), width="", height=""
    )

"""
This is a simple experiment that allows participants to rate sounds on a scale of 1 to 5.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring

from pathlib import Path

import psynet.experiment
from psynet.asset import asset  # noqa
from psynet.modular_page import (
    AudioPrompt,
    ModularPage,
    MultiRatingControl,
    RatingScale,
)
from psynet.page import InfoPage
from psynet.timeline import Event, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

N_TRIALS_PER_PARTICIPANT = 6


# Note: for a more automatic approach, one could use the `audio_stimulus_set_from_dir` function
# to generate the nodes from a structured directory of audio files.
# See the `audio_stimulus_set_from_dir` demo for an example.
def get_nodes():
    return [
        StaticNode(
            definition={"stimulus_name": stimulus["name"]},
            assets={
                "stimulus_audio": asset(
                    stimulus["path"],
                    extension=".mp3",
                )
            },
        )
        for stimulus in list_stimuli()
    ]


def list_stimuli():
    stimulus_dir = Path("data/instrument_sounds")
    return [
        {
            "name": path.stem,
            "path": path,
        }
        for path in list(stimulus_dir.glob("*.mp3"))
    ]


# Run `python3 experiment.py` to list the stimuli.
if __name__ == "__main__":
    stimuli = list_stimuli()
    print(f"Found {len(stimuli)} stimuli:")
    for stimulus in stimuli:
        print(f"- {stimulus['name']}")


class CustomTrial(StaticTrial):
    time_estimate = 10

    def show_trial(self, experiment, participant):
        return ModularPage(
            "ratings",
            AudioPrompt(
                self.assets["stimulus_audio"],
                "Please rate the sound. You can replay it as many times as you like.",
                controls={"Play from start": "Replay"},
            ),
            MultiRatingControl(
                RatingScale(
                    name="brightness",
                    values=5,
                    title="Brightness",
                    min_description="Dark",
                    max_description="Bright",
                ),
                RatingScale(
                    name="roughness",
                    values=5,
                    title="Roughness",
                    min_description="Smooth",
                    max_description="Rough",
                ),
            ),
            events={
                "submitEnable": Event(is_triggered_by="promptEnd"),
            },
            time_estimate=10,
        )


class Exp(psynet.experiment.Experiment):
    label = "Subjective rating"

    timeline = Timeline(
        InfoPage(
            """
            In this experiment you will hear some sounds. Your task will be to rate
            them on a scale of 1 to 5 on several scales.
            """,
            time_estimate=5,
        ),
        StaticTrialMaker(
            id_="ratings",
            trial_class=CustomTrial,
            nodes=get_nodes,
            expected_trials_per_participant="n_nodes",
            max_trials_per_participant="n_nodes",
        ),
        InfoPage(
            """
            Thank you for your participation!
            """,
            time_estimate=5,
        ),
    )

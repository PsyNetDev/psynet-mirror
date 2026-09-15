"""
In this experiment participants mark and describe interesting moments in a piece of music.
"""
# pylint: disable=missing-class-docstring,missing-function-docstring

from pathlib import Path

from markupsafe import Markup

import psynet.experiment
from psynet.asset import asset  # noqa
from psynet.modular_page import AudioPrompt, ModularPage, TextControl
from psynet.page import InfoPage
from psynet.timeline import PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

from .control import SingleTimedPushButtonControl

STIMULUS_DIR = "data/global_music"
STIMULUS_PATTERN = "*.mp3"
TRIALS_PER_PARTICIPANT = 2


def get_timeline():
    return Timeline(
        InfoPage(
            "Welcome! You will listen to audio and mark interesting moments.",
            time_estimate=5,
        ),
        StaticTrialMaker(
            id_="audio_timed_button_trial",
            trial_class=AudioTimedButtonTrial,
            nodes=get_nodes,  # not get_nodes()!
            expected_trials_per_participant=TRIALS_PER_PARTICIPANT,
            max_trials_per_participant=TRIALS_PER_PARTICIPANT,
        ),
        InfoPage("Thank you for participating!", time_estimate=5),
    )


def get_nodes():
    return [
        StaticNode(
            definition={"stimulus_name": path.stem},
            assets={
                "stimulus_audio": asset(path, cache=False),
            },
        )
        for path in Path(STIMULUS_DIR).glob(STIMULUS_PATTERN)
    ]


class AudioTimedButtonTrial(StaticTrial):
    time_estimate = 120
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        return join(
            self.mark_interesting_moments(participant),
            PageMaker(self.describe_interesting_moments, time_estimate=45),
        )

    def mark_interesting_moments(self, participant):
        return ModularPage(
            "event_times",
            prompt=AudioPrompt(
                audio=self.assets["stimulus_audio"],
                text=Markup(
                    "<div style='text-align: center;'>Listen to the music and press the button when it's <strong>interesting</strong><br><br></div>"
                ),
                controls=False,
            ),
            control=SingleTimedPushButtonControl(
                label="Interesting", button_highlight_duration=0.75
            ),
            time_estimate=15,
            save_answer="event_times",
        )

    def describe_interesting_moments(self, participant):
        return [
            ModularPage(
                f"event_description_{i}",
                AudioPrompt(
                    self.assets["stimulus_audio"],
                    Markup(f"""<div style='text-align: center;'>
                           You indicated that at {event_time} seconds you found the music interesting.<br>
                           Can you tell us why? We'll play that moment again for you.
                           </div>"""),
                    play_window=[max(0, event_time - 3), event_time + 3],
                    controls={"Play": "Replay"},
                ),
                TextControl(one_line=False, width="800px", height="400px"),
                time_estimate=30,
            )
            for i, event_time in enumerate(participant.var.event_times)
        ]


class Exp(psynet.experiment.Experiment):
    timeline = get_timeline()

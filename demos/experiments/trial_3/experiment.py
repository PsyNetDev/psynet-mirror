import random

import psynet.experiment
from psynet.asset import asset
from psynet.bot import Bot
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.timeline import Module, Timeline, for_loop
from psynet.trial.main import Trial

from .custom_synth import synth_prosody


def synth_stimulus(path, frequency_gradient, start_frequency):
    frequencies = [start_frequency + i * frequency_gradient for i in range(5)]
    synth_prosody(vector=frequencies, output_path=path)


class RateTrial(Trial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        return ModularPage(
            "audio_rating",
            AudioPrompt(
                self.assets["audio"],
                text="How happy is the following word?",
            ),
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
            ),
        )


audio_ratings = Module(
    "audio_ratings",
    # Deliver 5 trials with randomly sampled parameters.
    for_loop(
        iterate_over=lambda: [
            {
                "frequency_gradient": random.uniform(-100, 100),
                "start_frequency": random.uniform(-100, 100),
            }
            for _ in range(5)
        ],
        logic=lambda definition: RateTrial.cue(
            definition,
            assets={
                "audio": asset(synth_stimulus, extension=".wav", on_demand=True),
            },
        ),
        time_estimate_per_iteration=RateTrial.time_estimate,
    ),
)


class Exp(psynet.experiment.Experiment):
    label = "Simple trial demo (3)"

    timeline = Timeline(
        audio_ratings,
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == 5

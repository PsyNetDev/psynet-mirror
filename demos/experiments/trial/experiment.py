import random

from markupsafe import Markup

import psynet.experiment
from psynet.bot import Bot
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import Module, Timeline, for_loop
from psynet.trial.main import Trial

WORDS = [
    "cat",
    "dog",
    "fish",
    "monkey",
    "giraffe",
    "octopus",
]


class RateTrial(Trial):
    time_estimate = 3

    def show_trial(self, experiment, participant):
        word = self.definition["word"]

        return ModularPage(
            "rate_trial",
            Markup("How happy is the following word: <strong>{}</strong>").format(word),
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
            ),
        )


word_ratings = Module(
    "word_ratings",
    for_loop(
        iterate_over=lambda: random.sample(WORDS, 3),
        logic=lambda word: RateTrial.cue(
            {
                "word": word,
            }
        ),
        time_estimate_per_iteration=3,
    ),
)


class Exp(psynet.experiment.Experiment):
    label = "Simple trial demo"

    timeline = Timeline(
        word_ratings,
    )

    test_n_bots = 3

    def test_check_bot(self, bot: Bot, **kwargs):
        assert not bot.failed
        trials = bot.all_trials
        assert len(trials) == 3
        assert len(set([t.definition["word"] for t in trials])) == 3
        assert all([t.definition["word"] in WORDS for t in trials])
        assert all([t.complete for t in trials])
        assert all([t.finalized for t in trials])

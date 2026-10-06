import psynet.experiment
from psynet.bot import Bot
from psynet.pytest_psynet import AnimalTrial, ColorTrial, trial_maker_1, trial_maker_2
from psynet.timeline import Timeline, for_loop, join


class Exp(psynet.experiment.Experiment):
    label = "Static experiment demo"

    timeline = Timeline(
        trial_maker_1.custom(
            trial_maker_2.custom(
                for_loop(
                    label="loop over pairs of trials",
                    iterate_over=lambda: range(3),
                    logic=lambda _: join(
                        trial_maker_1.cue_trial(),
                        trial_maker_2.cue_trial(),
                    ),
                    time_estimate_per_iteration=6,
                )
            )
        ),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == 6
        trials = sorted(bot.alive_trials, key=lambda t: t.id)
        for i in [0, 2, 4]:
            assert isinstance(trials[i], AnimalTrial)
        for i in [1, 3, 5]:
            assert isinstance(trials[i], ColorTrial)

import psynet.experiment
from psynet.bot import Bot
from psynet.pytest_psynet import AnimalTrial, ColorTrial, trial_maker_1, trial_maker_2
from psynet.timeline import Timeline, randomize
from psynet.utils import get_logger

logger = get_logger()


class Exp(psynet.experiment.Experiment):
    label = "Randomize demo 2"

    timeline = Timeline(
        randomize(
            logic=[
                trial_maker_1,
                trial_maker_2,
            ],
        ),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == 18
        assert len([t for t in bot.alive_trials if isinstance(t, AnimalTrial)]) == 9
        assert len([t for t in bot.alive_trials if isinstance(t, ColorTrial)]) == 9

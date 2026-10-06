import psynet.experiment
from psynet.bot import Bot
from psynet.page import InfoPage
from psynet.prescreen import ColorBlindnessTest
from psynet.timeline import Timeline


class Exp(psynet.experiment.Experiment):
    label = "Colour blindness demo"

    timeline = Timeline(
        ColorBlindnessTest(),
        InfoPage(
            "You passed the color blindness task! Congratulations.", time_estimate=3
        ),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        from psynet.prescreen import ColorBlindnessTrial

        trials = ColorBlindnessTrial.query.filter_by(participant_id=bot.id).all()
        assert len(trials) == 6
        n_correct = sum(trial.score for trial in trials)
        score = bot.module_states["color_blindness_test"][0].performance_check["score"]
        assert score == n_correct

import psynet.experiment
from psynet.bot import Bot
from psynet.modular_page import ColorPrompt, PushButtonControl
from psynet.page import InfoPage, ModularPage
from psynet.timeline import Timeline
from psynet.trial.dense import (
    DenseNode,
    DenseTrialMaker,
    Dimension,
    SingleStimulusTrial,
)
from psynet.utils import get_logger

logger = get_logger()

PARAMS = {
    "dimensions": [
        Dimension("Hue", min_value=0, max_value=360),
        Dimension("Saturation", min_value=0, max_value=100),
        Dimension("Lightness", min_value=0, max_value=100),
    ]
}

CONDITIONS = [
    DenseNode(
        {
            **PARAMS,
            "adjective": "angry",
        }
    ),
    DenseNode(
        {
            **PARAMS,
            "adjective": "happy",
        }
    ),
]


class CustomTrial(SingleStimulusTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        adjective = self.definition["adjective"]
        color = self.definition["location"]
        caption = f"Please rate how well the color matches the following adjective: {adjective}"

        return ModularPage(
            "color",
            ColorPrompt(color=color, text=caption),
            PushButtonControl(choices=[1, 2, 3, 4], arrange_vertically=False),
            time_estimate=self.time_estimate,
        )


class Exp(psynet.experiment.Experiment):
    label = "Dense color demo"
    trials_per_participant = 6

    timeline = Timeline(
        DenseTrialMaker(
            id_="color",
            trial_class=CustomTrial,
            conditions=CONDITIONS,
            recruit_mode="n_participants",
            target_n_participants=1,
            target_trials_per_condition=None,
            expected_trials_per_participant=trials_per_participant,
            max_trials_per_participant=trials_per_participant,
        ),
        InfoPage("You finished the experiment!", time_estimate=0),
    )

    def test_check_bot(self, bot: Bot):
        assert not bot.failed
        assert len(bot.alive_trials) == self.trials_per_participant

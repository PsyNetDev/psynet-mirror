import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import CodeBlock, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

N_TRIALS = 4
BREAK_BEFORE = 2


class RatingTrial(StaticTrial):
    time_estimate = 2

    def show_trial(self, experiment, participant):
        return ModularPage(
            "rating",
            f"Trial {self.position + 1}",
            PushButtonControl(["yes", "no"]),
            bot_response="yes",
        )


class RatingTrialMaker(StaticTrialMaker):
    def show_before_trial(self, participant, trial):
        if trial.position != BREAK_BEFORE:
            return None

        def record(participant):
            participant.var.breaks = participant.var.get("breaks", []) + [
                trial.position
            ]

        return join(
            CodeBlock(record),
            InfoPage("Take a break.", label="trial_break", time_estimate=3),
        )


class Exp(psynet.experiment.Experiment):
    label = "Trial breaks"

    timeline = Timeline(
        RatingTrialMaker(
            id_="ratings",
            trial_class=RatingTrial,
            nodes=[StaticNode(definition={"item": i}) for i in range(N_TRIALS)],
            expected_trials_per_participant=N_TRIALS,
            node_order="listed",
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = sorted(bot.all_trials, key=lambda trial: trial.position)
        assert [trial.answer for trial in trials] == ["yes"] * N_TRIALS
        assert bot.var.breaks == [BREAK_BEFORE]

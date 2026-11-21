import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import CodeBlock, Response, Timeline, join
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

        # Saves its answer, unlike an InfoPage, which mustn't reach the trial.
        return join(
            CodeBlock(record),
            ModularPage(
                "trial_break",
                "Take a break.",
                PushButtonControl(["rested"]),
                bot_response="rested",
                time_estimate=3,
            ),
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
        # The break page's time and response don't count towards its trial.
        assert len({trial.time_taken for trial in trials}) == 1
        (break_response,) = Response.query.filter_by(
            participant_id=bot.id, question="trial_break"
        ).all()
        assert break_response.trial_id is None

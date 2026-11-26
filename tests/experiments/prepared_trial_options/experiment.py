import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

N_NODES = 5
N_REPEAT_TRIALS = 4


class RatingTrial(StaticTrial):
    time_estimate = 2

    def show_trial(self, experiment, participant):
        return ModularPage(
            "rating",
            f"Item {self.definition['item']}",
            PushButtonControl(["yes", "no"]),
            bot_response="yes",
        )


class RatingTrialMaker(StaticTrialMaker):
    def should_check_performance_after(self, participant, trial):
        assert participant.id == trial.participant_id
        return trial.position % 2 == 1

    def performance_check(self, experiment, participant, participant_trials):
        participant.var.checked = participant.var.get("checked", []) + [
            [trial.complete for trial in participant_trials]
        ]
        return {"score": None, "passed": not participant.var.get("fail_checks", False)}


class Exp(psynet.experiment.Experiment):
    label = "Prepared trials with other trial maker options"

    timeline = Timeline(
        RatingTrialMaker(
            id_="ratings",
            trial_class=RatingTrial,
            nodes=[StaticNode(definition={"item": i}) for i in range(N_NODES)],
            expected_trials_per_participant=N_NODES,
            node_order="listed",
            prepare_trials_in_advance=True,
            n_repeat_trials=N_REPEAT_TRIALS,
            check_performance_every_trial=True,
            recruit_mode="n_trials",
            target_trials_per_node=1,
            target_n_participants=None,
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = sorted(bot.all_trials, key=lambda trial: trial.id)
        main = [trial for trial in trials if not trial.is_repeat_trial]
        repeats = [trial for trial in trials if trial.is_repeat_trial]
        assert [trial.definition["item"] for trial in main] == list(range(N_NODES))
        assert len(repeats) == N_REPEAT_TRIALS
        assert {trial.node_id for trial in repeats} <= {trial.node_id for trial in main}
        assert all(trial.complete and trial.answer == "yes" for trial in trials)
        # Every second trial is checked, and each check sees only the trials
        # answered so far, not the ones prepared ahead.
        assert [len(seen) for seen in bot.var.checked] == list(
            range(2, len(trials) + 1, 2)
        )
        assert all(all(seen) for seen in bot.var.checked)

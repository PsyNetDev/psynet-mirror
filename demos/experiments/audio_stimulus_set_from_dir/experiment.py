import random

import psynet.experiment
from psynet.modular_page import AudioPrompt, ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.trial import compile_nodes_from_directory
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


class CustomTrial(StaticTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        return ModularPage(
            "question_page",
            AudioPrompt(self.definition["url"], "Do you like this audio file?"),
            PushButtonControl(["Yes", "No"]),
            time_estimate=self.time_estimate,
        )


class Exp(psynet.experiment.Experiment):
    label = "Audio stimulus set from directory demo"

    timeline = Timeline(
        InfoPage("We begin with the practice trials.", time_estimate=5),
        StaticTrialMaker(
            id_="audio_practice",
            trial_class=CustomTrial,
            nodes=compile_nodes_from_directory(
                input_dir="static/practice", media_ext=".wav", node_class=StaticNode
            ),
            target_n_participants=0,
            recruit_mode="n_participants",
            expected_trials_per_participant=2,
            max_trials_per_participant=2,
        ),
        InfoPage("We continue with the experiment trials.", time_estimate=5),
        StaticTrialMaker(
            id_="audio_experiment",
            trial_class=CustomTrial,
            nodes=compile_nodes_from_directory(
                input_dir="static/experiment", media_ext=".wav", node_class=StaticNode
            ),
            target_n_participants=10,
            recruit_mode="n_participants",
            expected_trials_per_participant=7,
            choose_participant_group=lambda participant: random.choice(
                ["participant-group-1", "participant-group-2"]
            ),
        ),
    )

    def test_experiment(self):
        super().test_experiment()

        practice = StaticNode.query.filter_by(trial_maker_id="audio_practice").all()
        experiment = StaticNode.query.filter_by(trial_maker_id="audio_experiment").all()
        assert len(practice) == 2
        assert len(experiment) == 11
        for node in (*practice, *experiment):
            assert node.definition["url"].startswith("/static/")

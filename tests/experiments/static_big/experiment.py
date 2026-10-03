# pylint: disable=unused-import,abstract-method

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

nodes = [
    StaticNode(
        definition={"animal": animal, "repetition": repetition},
    )
    for animal in ["cats", "dogs", "fish", "ponies"]
    for repetition in range(500)
]


class AnimalTrial(StaticTrial):
    time_estimate = 3

    def show_trial(self, experiment, participant):
        animal = self.definition["animal"]

        return ModularPage(
            "animal_trial",
            f"How much do you like {animal}?",
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
                bot_response="Very much",
            ),
            time_estimate=self.time_estimate,
        )


trial_maker = StaticTrialMaker(
    id_="animals",
    trial_class=AnimalTrial,
    nodes=nodes,
    expected_trials_per_participant=6,
    max_trials_per_block=2,
    allow_repeated_nodes=True,
    check_performance_at_end=False,
    check_performance_every_trial=False,
    target_n_participants=1,
    target_trials_per_node=None,
    recruit_mode="n_participants",
    n_repeat_trials=3,
)


class Exp(psynet.experiment.Experiment):
    label = "Static experiment demo"

    timeline = Timeline(
        trial_maker,
    )

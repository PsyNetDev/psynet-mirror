import random

import psynet.experiment
from psynet.consent import MainConsent
from psynet.modular_page import Prompt, PushButtonControl
from psynet.page import InfoPage, ModularPage
from psynet.timeline import Timeline
from psynet.trial.mcmcp import MCMCPNode, MCMCPTrial, MCMCPTrialMaker
from psynet.utils import get_logger

logger = get_logger()

MAX_AGE = 100
OCCUPATIONS = ["doctor", "babysitter", "teacher"]
SAMPLE_RANGE = 5


class CustomTrial(MCMCPTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        occupation = self.context["occupation"]
        age_1 = self.first_stimulus["age"]
        age_2 = self.second_stimulus["age"]
        prompt = (
            f"Person A is {age_1} years old. "
            f"Person B is {age_2} years old. "
            f"Which one is the {occupation}?"
        )
        return ModularPage(
            "mcmcp_trial",
            Prompt(prompt),
            control=PushButtonControl(
                ["0", "1"], labels=["Person A", "Person B"], arrange_vertically=False
            ),
            time_estimate=self.time_estimate,
        )


class CustomNode(MCMCPNode):
    def create_initial_seed(self, experiment, participant):
        return {"age": random.randint(0, MAX_AGE)}

    def get_proposal(self, state, experiment, participant):
        age = state["age"] + random.randint(-SAMPLE_RANGE, SAMPLE_RANGE)
        age = age % (MAX_AGE + 1)
        return {"age": age}


def start_nodes(participant):
    return [
        CustomNode(
            context={
                "occupation": occupation,
            },
        )
        for occupation in OCCUPATIONS
    ]


class Exp(psynet.experiment.Experiment):
    label = "MCMCP demo experiment"

    timeline = Timeline(
        MainConsent(),
        MCMCPTrialMaker(
            id_="mcmcp_demo",
            start_nodes=start_nodes,
            trial_class=CustomTrial,
            node_class=CustomNode,
            chain_type="within",  # can be "within" or "across"
            expected_trials_per_participant=9,
            max_trials_per_participant=9,
            chains_per_participant=3,  # set to None if chain_type="across"
            chains_per_experiment=None,  # set to None if chain_type="within"
            max_nodes_per_chain=3,
            trials_per_node=1,
            balance_across_chains=True,
            check_performance_at_end=False,
            check_performance_every_trial=False,
            fail_trials_on_participant_performance_check=True,
            recruit_mode="n_participants",
            target_n_participants=1,
        ),
        InfoPage("You finished the experiment!", time_estimate=0),
    )

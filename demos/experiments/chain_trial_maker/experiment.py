"""
This demo shows how to design a custom chain trial maker.
"""

import psynet.experiment
from psynet.modular_page import (
    ModularPage,
    TextControl,
)
from psynet.page import InfoPage
from psynet.timeline import Timeline, join
from psynet.trial.chain import ChainNode, ChainTrial, ChainTrialMaker


def get_timeline():
    return Timeline(
        ChainTrialMaker(
            id_="stories",
            trial_class=CustomTrial,
            node_class=CustomChainNode,
            chain_type="across",
            start_nodes=get_start_nodes,
            expected_trials_per_participant="n_start_nodes",
            max_nodes_per_chain=10,
            recruit_mode="n_trials",
        )
    )


STORIES = [
    "A man walked to the park and saw a duck...",
    "It was a rainy day in London...",
]


class CustomChainNode(ChainNode):
    def make_next_definition(self, experiment, participant):
        return {"story": self.completed_and_processed_trials[0].answer}


def get_start_nodes():
    return [
        CustomChainNode(
            definition={
                "story": story,
            }
        )
        for story in STORIES
    ]


class CustomTrial(ChainTrial):
    time_estimate = 60

    def show_trial(self, experiment, participant):
        return join(
            InfoPage(
                f"""
                Read the following story carefully:

                {self.definition["story"]}
                """,
            ),
            ModularPage(
                "recall_story",
                "Now recall the story in your own words.",
                TextControl(),
            ),
        )


class Exp(psynet.experiment.Experiment):
    timeline = get_timeline()
    test_n_bots = 3

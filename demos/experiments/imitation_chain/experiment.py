# pylint: disable=unused-import,abstract-method,unused-argument

import random
import re
from statistics import mean

import psynet.experiment
from psynet.bot import Bot
from psynet.modular_page import ModularPage, Prompt, TextControl
from psynet.page import InfoPage
from psynet.timeline import FailedValidation, Timeline
from psynet.trial.imitation_chain import (
    ImitationChainNetwork,
    ImitationChainNode,
    ImitationChainTrial,
    ImitationChainTrialMaker,
)
from psynet.utils import get_logger

logger = get_logger()


class FixedDigitInputPage(ModularPage):
    def __init__(self, label: str, prompt: str, time_estimate: float, bot_response):
        self.n_digits = 7

        super().__init__(
            label,
            Prompt(prompt),
            control=TextControl(
                block_copy_paste=True,
                bot_response=bot_response,
            ),
            time_estimate=time_estimate,
        )

    def format_answer(self, raw_answer, **kwargs):
        try:
            pattern = re.compile("^[0-9]*$")
            assert len(raw_answer) == self.n_digits
            assert pattern.match(raw_answer)
            return int(raw_answer)
        except (ValueError, AssertionError):
            return "INVALID_RESPONSE"

    def validate(self, response, **kwargs):
        if response.answer == "INVALID_RESPONSE":
            return FailedValidation("Please enter a 7-digit number.")
        return None


class CustomTrial(ImitationChainTrial):
    time_estimate = 2 + 3

    def show_trial(self, experiment, participant):
        page_1 = InfoPage(
            f"Try to remember this 7-digit number: {self.definition['number']:07d}",
            time_estimate=2,
        )
        page_2 = FixedDigitInputPage(
            "number",
            "What was the number?",
            time_estimate=3,
            bot_response=lambda: self.definition["number"],
        )

        return [page_1, page_2]


class CustomNetwork(ImitationChainNetwork):
    pass


class CustomNode(ImitationChainNode):
    def create_initial_seed(self, experiment, participant):
        return {"number": random.randint(0, 9999999)}

    def summarize_trials(self, trials: list, experiment, participant):
        return {"number": round(mean([trial.answer for trial in trials]))}


class CustomTrialMaker(ImitationChainTrialMaker):
    response_timeout_sec = 60
    check_timeout_interval_sec = 30


class Exp(psynet.experiment.Experiment):
    label = "Imitation chain demo"

    timeline = Timeline(
        CustomTrialMaker(
            id_="imitation_chain",
            network_class=CustomNetwork,
            trial_class=CustomTrial,
            node_class=CustomNode,
            chain_type="within",
            max_nodes_per_chain=5,
            max_trials_per_participant=5,
            expected_trials_per_participant=5,
            chains_per_participant=1,
            chains_per_experiment=None,
            trials_per_node=1,
            chain_order="balanced",
            check_performance_at_end=False,
            check_performance_every_trial=False,
            recruit_mode="n_participants",
            target_n_participants=10,
        ),
        InfoPage("You finished the experiment!", time_estimate=0),
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        assert len(bot.alive_trials) == 5

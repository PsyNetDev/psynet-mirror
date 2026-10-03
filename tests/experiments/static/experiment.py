# pylint: disable=unused-import,abstract-method
import random

from markupsafe import Markup

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.trial.static import StaticNetwork, StaticNode, StaticTrial, StaticTrialMaker

from . import test_imports  # noqa  (this is for PsyNet's regression tests)

nodes = [
    StaticNode(
        definition={"animal": animal},
        block=block,
    )
    for animal in ["cats", "dogs", "fish", "ponies"]
    for block in ["A", "B", "C"]
]


class AnimalTrial(StaticTrial):
    time_estimate = 3

    def finalize_definition(self, definition, experiment, participant):
        definition["text_color"] = random.choice(["red", "green", "blue"])
        return definition

    def show_trial(self, experiment, participant):
        text_color = self.definition["text_color"]
        animal = self.definition["animal"]
        block = self.block

        header = f"<h4 id='trial-position'>Trial {self.position + 1}</h3>"

        if self.is_repeat_trial:
            header = (
                header
                + f"<h4>Repeat trial {self.repeat_trial_index + 1} out of {self.n_repeat_trials}</h3>"
            )
        else:
            header = header + f"<h4>Block {block}</h3>"

        page = ModularPage(
            "animal_trial",
            Markup(
                f"""
                {header}
                <p id='question' style='color: {text_color}'>How much do you like {animal}?</p>
                """
            ),
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
                bot_response="Very much",
            ),
            time_estimate=self.time_estimate,
        )

        return page

    # def show_feedback(self, experiment, participant):
    #     return InfoPage(f"You responded '{self.answer}'.")

    def score_answer(self, answer, definition):
        if answer == "Not at all":
            return 0.0
        return 1.0

    def compute_performance_reward(self, score):
        # Here we give the participant 1 cent per point immediately after each trial.
        return 0.01 * score


class AnimalTrialMaker(StaticTrialMaker):
    def performance_check(self, experiment, participant, participant_trials):
        """Should return a dict: {"score": float, "passed": bool}"""
        score = 0
        failed = False
        for trial in participant_trials:
            if trial.answer == "Not at all":
                failed = True
            else:
                score += 1
        return {"score": score, "passed": not failed}

    def compute_performance_reward(self, score, passed):
        # At the end of the trial maker, we give the participant 1 dollar for each point.
        # This is combined with their trial-level performance reward to give their overall performance reward.
        return 1.0 * score

    give_end_feedback_passed = True

    def get_end_feedback_passed_page(self, score):
        return InfoPage(
            Markup(f"You finished the animal questions! Your score was {score}."),
            time_estimate=5,
        )


trial_maker = AnimalTrialMaker(
    id_="animals",
    trial_class=AnimalTrial,
    nodes=nodes,
    expected_trials_per_participant=6,
    max_trials_per_block=2,
    allow_repeated_nodes=True,
    balance_across_nodes=True,
    check_performance_at_end=True,
    check_performance_every_trial=True,
    target_n_participants=1,
    target_trials_per_node=None,
    recruit_mode="n_participants",
    n_repeat_trials=3,
)


class Exp(psynet.experiment.Experiment):
    label = "Static experiment demo"
    test_n_bots = 2

    config = {
        # Asserted by the end-to-end tests; generic recruitment now hides
        # rewards unless the experiment opts in.
        "show_reward": True,
    }

    timeline = Timeline(
        trial_maker,
    )

    def test_check_bot(self, participant):
        self.check_network_participants_relationship(participant)

    def check_network_participants_relationship(self, participant):
        """
        This function checks that the network.participants relationship works correctly.
        The relationship works by retrieving all participants with trials in that network.
        We check this relationship by cross-referencing it against the participant.all_trials relationship.
        """
        participant_networks = set([trial.network for trial in participant.all_trials])
        all_networks = StaticNetwork.query.all()

        assert len(participant_networks) > 0

        counter = 0
        for network in all_networks:
            if participant in network.participants:
                assert network in participant_networks
                counter += 1
            else:
                assert network not in participant_networks

        assert counter == len(participant_networks)

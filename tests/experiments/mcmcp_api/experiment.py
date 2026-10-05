import random
import time

from markupsafe import Markup

import psynet.experiment
from psynet.consent import MainConsent
from psynet.modular_page import Prompt, PushButtonControl
from psynet.page import InfoPage, ModularPage
from psynet.timeline import Timeline
from psynet.trial.mcmcp import MCMCPNode, MCMCPTrial, MCMCPTrialMaker
from psynet.utils import get_logger

logger = get_logger()


# This demo illustrates how one might design an MCMCP experiment that involves a call to an external API.
# The crucial method is Trial.async_on_deploy, which defines a function that is run asynchronously
# whenever a node is created on the web server. This function can be used to make a call to an API
# without worrying about blocking web requests.

MAX_AGE = 100
OCCUPATIONS = ["doctor", "babysitter", "teacher"]
SAMPLE_RANGE = 5


class CustomTrial(MCMCPTrial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        occupation = self.context["occupation"]
        age_1 = self.first_stimulus["age"]
        age_2 = self.second_stimulus["age"]
        prompt = Markup(
            f"<p>Person A is {age_1} years old. "
            f"Person B is {age_2} years old. "
            f"Which one is the {occupation}?</p>"
            f"<em>API output: {self.node.var.api_response['output']}</em>"
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
    def async_on_deploy(self):
        super().async_on_deploy()
        self.var.api_response = self.make_api_call(
            current_state=self.definition["current_state"],
            proposal=self.definition["proposal"],
        )

    def make_api_call(self, current_state, proposal):
        # In a real experiment you would replace this with a call to a real API. You could write
        # something like this:

        # import requests
        # result = requests.post(
        #     "https://my-api.org",
        #     json={
        #         "current_state": current_state,
        #         "proposal": proposal,
        #     },
        #     # verify=False,  # Sometimes disabling SSL can be necessary if you have tricky certificate issues
        # ).json()
        # return result

        # Another use case might have the API generate some media that can be accessed via a URL returned from the
        # API response. In this case you could consider creating an ExternalAsset for this media,
        # so that the media is properly logged within the database, and then can be included within data exports.

        # from dallinger import db
        # from psynet.asset import ExternalAsset
        #
        # asset = ExternalAsset(
        #     result["url"],
        #     label="stimulus",
        #     parent=self,
        # )
        # db.session.add(asset)
        # db.session.commit()
        #
        # You could then access the asset as follows:
        # self.assets["stimulus"]
        # self.assets["stimulus"].url

        # The following code is a basic simulation that just waits a little while then returns some data.
        # It does not actually talk to any API.
        time.sleep(0.25)
        return {
            "current_state": current_state,
            "proposal": proposal,
            "output": random.choice(range(1000)),
        }

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
    label = "MCMCP demo experiment (inc. API)"

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
            wait_for_networks=True,
        ),
        InfoPage("You finished the experiment!", time_estimate=0),
    )

    def test_experiment(self):
        super().test_experiment()
        time.sleep(1)  # Wait for any async processes to complete
        nodes = CustomNode.query.all()
        assert len(nodes) > 0
        for n in nodes:
            assert n.var.has("api_response")
            assert 0 <= n.var.api_response["output"] < 1000

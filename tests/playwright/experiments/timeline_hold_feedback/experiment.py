import time

import psynet.experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.timeline import Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker


class FeedbackTrial(StaticTrial):
    time_estimate = 2

    def show_trial(self, experiment, participant):
        return ModularPage(
            "response",
            "Choose a response before feedback processing.",
            PushButtonControl(["response"]),
            time_estimate=1,
        )

    def async_post_trial(self):
        time.sleep(3)

    def show_feedback(self, experiment, participant):
        return InfoPage("Asynchronous feedback is ready.", time_estimate=1)


class Exp(psynet.experiment.Experiment):
    label = "Timeline hold feedback"

    timeline = Timeline(
        StaticTrialMaker(
            id_="feedback",
            trial_class=FeedbackTrial,
            nodes=[StaticNode(definition={"condition": "feedback"})],
            expected_trials_per_participant=1,
            max_trials_per_participant=1,
        )
    )

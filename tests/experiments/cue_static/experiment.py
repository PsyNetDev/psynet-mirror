import psynet.experiment
from psynet.page import InfoPage
from psynet.timeline import Timeline, for_loop
from psynet.trial.static import StaticTrial

# This test is here to catch a historic bug where, if Trial.cue was called outside a PageMaker,
# the experiment would fail with a sqlalchemy.orm.exc.DetachedInstanceError.


class CustomTrial(StaticTrial):
    time_estimate = 10

    def show_trial(self, experiment, participant):
        return InfoPage(
            "This is a custom trial",
        )


class Exp(psynet.experiment.Experiment):
    label = "Static cue"
    timeline = Timeline(
        for_loop(
            label="loop over custom trials",
            iterate_over=lambda: range(3),
            logic=CustomTrial.cue(definition={}),
            time_estimate_per_iteration=10,
        )
    )

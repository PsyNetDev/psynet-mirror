"""Parallel bots answer filler trials while waiting for their group, then get grouped."""

import psynet.experiment
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper, SyncGroup
from psynet.timeline import PageMaker, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

GROUP_SIZE = 8


class FillerTrial(StaticTrial):
    time_estimate = 3

    def show_trial(self, experiment, participant):
        return InfoPage("While you wait, here is a fact.", time_estimate=3)


filler = StaticTrialMaker(
    id_="filler",
    trial_class=FillerTrial,
    nodes=[StaticNode(definition={})],
    expected_trials_per_participant=6,
    max_trials_per_participant=5000,
    allow_repeated_nodes=True,
)


class Exp(psynet.experiment.Experiment):
    label = "Grouper waiting logic"

    timeline = Timeline(
        filler.custom(
            SimpleGrouper(
                "lobby",
                initial_group_size=GROUP_SIZE,
                quorum=GROUP_SIZE,
                waiting_logic=PageMaker(filler.cue_trial, time_estimate=3),
                max_wait_time=30,
            ),
        ),
        InfoPage("Your group is complete.", time_estimate=1),
    )

    test_n_bots = GROUP_SIZE
    test_mode = "parallel"

    def test_check_bots(self, bots):
        super().test_check_bots(bots)
        assert SyncGroup.query.count() == 1
        assert all(bot.sync_group_links for bot in bots)

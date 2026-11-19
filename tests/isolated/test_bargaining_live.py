"""The bargaining demo's rules: proposals, and accepting the proposal the
player saw."""

from types import SimpleNamespace

import pytest
from dallinger.realtime import Reject

from psynet.experiment import import_local_experiment
from psynet.live_game.testing import LocalGame
from psynet.pytest_psynet import path_to_demo_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("bargaining_live")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestBargainingLive:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    @pytest.fixture
    def game(self, demo):
        return LocalGame(demo.Bargain, players=2, settings={"stake": 10})

    def test_a_quick_pair_waits_for_the_other_pair_to_finish_its_round(self, demo):
        round_takes = demo.BargainTrial.time_estimate + demo.RESULT_SECONDS + 5
        assert demo.ROUND_DEADLINE_SECONDS > round_takes

    def test_a_partner_who_doesn_t_arrive_leaves_the_cohort_too(self, demo):
        # So that the next pairing doesn't wait for them.
        trial = SimpleNamespace(definition={"stake": 10})
        barrier = demo.BargainTrial.show_trial(trial, None, None).barrier
        assert (barrier.late_action, barrier.also_leave) == ("leave_group", ["cohort"])

    def test_accepting_a_proposal_makes_the_deal_it_offered(self, demo, game):
        game.send(0, demo.Propose(keep=7))
        game.send(1, demo.Accept(keep=7), now=12.5)

        assert game.is_over()
        assert game.outcome() == {"deal": [7, 3], "deal_at": 12.5, "n_proposals": 1}
        assert (game.answer(0), game.answer(1)) == (
            {"deal": True, "coins": 7},
            {"deal": True, "coins": 3},
        )

    def test_a_proposal_that_changed_can_t_be_accepted(self, demo, game):
        game.send(0, demo.Propose(keep=6))
        game.send(0, demo.Propose(keep=8), now=1)

        with pytest.raises(Reject, match="just changed"):
            game.send(1, demo.Accept(keep=6), now=1)
        assert not game.is_over()
        assert game.view(1)["theirs"] == 8

    def test_a_proposal_keeps_between_none_and_all_of_the_stake(self, demo, game):
        with pytest.raises(Reject, match="between 0 and 10"):
            game.send(0, demo.Propose(keep=11))

    def test_without_a_deal_nobody_is_paid(self, demo, game):
        game.send(0, demo.Propose(keep=9))
        assert game.answer(1) == {"deal": False, "coins": 0}
        assert game.game.performance_reward(game.outcome(), "finished", 1) == 0

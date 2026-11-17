"""The bargaining demo's rules: proposals, and accepting the proposal the
player saw."""

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

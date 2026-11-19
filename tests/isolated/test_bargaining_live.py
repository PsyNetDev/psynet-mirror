"""The bargaining demo's rules: proposals, accepting the proposal the
player saw, and what players are told when a partner doesn't arrive."""

from types import SimpleNamespace

import pytest
from dallinger.realtime import Reject

from psynet.experiment import import_local_experiment
from psynet.live_game import PlayerReady
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
        # Even a round whose partner arrived just before LATE_AFTER.
        round_takes = (
            demo.LATE_AFTER + demo.BargainTrial.time_estimate + demo.RESULT_SECONDS + 5
        )
        assert demo.ROUND_DEADLINE_SECONDS > round_takes

    def test_a_player_who_reached_the_game_too_late_is_told_on_the_last_page(
        self, demo
    ):
        def text(reason):
            participant = SimpleNamespace(
                sync_group_removal_reason=lambda group_type: (
                    reason if group_type == "cohort" else None
                )
            )
            return str(demo.end_of_game(participant).content)

        assert text("late") == "You didn't arrive in time, so the game is over for you."
        assert text("finished") == "That's the end of the game."

    def test_a_partner_who_never_opens_the_game_ends_it_at_the_start(self, demo):
        game = LocalGame(demo.Bargain, players=2, settings={"stake": 10}, start=False)
        game.send(0, PlayerReady())
        game.tick(demo.Bargain.ready_timeout)

        assert game.is_over()

        def feedback(player):
            trial = SimpleNamespace(answer=game.answer(player))
            return str(demo.BargainTrial.show_feedback(trial, None, None).content)

        assert feedback(0) == (
            "Your partner didn't arrive, so there was no game this round."
        )
        assert feedback(1) == (
            "You didn't arrive in time, so there was no game this round."
        )

    def test_accepting_a_proposal_makes_the_deal_it_offered(self, demo, game):
        game.send(0, demo.Propose(keep=7))
        game.send(1, demo.Accept(keep=7), now=12.5)

        assert game.is_over()
        assert game.outcome() == {
            "deal": [7, 3],
            "deal_at": 12.5,
            "n_proposals": 1,
            "no_shows": [],
        }
        assert [game.answer(player)["coins"] for player in (0, 1)] == [7, 3]

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
        trial = SimpleNamespace(answer=game.answer(1))

        assert game.game.performance_reward(game.outcome(), "finished", 1) == 0
        assert str(demo.BargainTrial.show_feedback(trial, None, None).content) == (
            "You didn't reach a deal in time, so nobody was paid."
        )

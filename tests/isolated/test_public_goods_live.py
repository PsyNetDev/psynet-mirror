"""The public goods demo's rules: contributions and each player's
payoff."""

from types import SimpleNamespace

import pytest
from dallinger.realtime import Reject

from psynet.experiment import import_local_experiment
from psynet.live_game import PLAYERS_LEFT
from psynet.live_game.testing import LocalGame
from psynet.pytest_psynet import path_to_demo_experiment


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("public_goods_live")],
    indirect=True,
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestPublicGoodsLive:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    def test_the_pot_is_multiplied_and_shared_equally(self, demo):
        game = LocalGame(demo.PublicGoods, players=3)
        for player, tokens in enumerate([10, 4, 0]):
            game.send(player, demo.Contribute(tokens=tokens))
        # A player can change their mind until the time is up.
        game.send(1, demo.Contribute(tokens=2), now=5)

        outcome = game.outcome()
        share = demo.MULTIPLIER * 12 / 3
        assert (outcome["pot"], outcome["share"]) == (12, share)
        assert outcome["payoffs"] == [
            demo.ENDOWMENT - 10 + share,
            demo.ENDOWMENT - 2 + share,
            demo.ENDOWMENT + share,
        ]
        assert game.answer(2) == {
            "arrived": True,
            "contributed": 0,
            "earned": demo.ENDOWMENT + share,
        }
        assert game.view(0)["contributions"] == [10, 2, 0]

    def _started_without(self, demo, no_shows):
        """A round of three that starts without the players ``no_shows``."""
        game = LocalGame(demo.PublicGoods, players=3, start=False)
        for player in {0, 1, 2} - set(no_shows):
            game.send(player, {"type": "psynet_ready", "message": {}})
        game.tick(demo.PublicGoods.ready_timeout)
        return game

    def test_a_player_who_never_opens_the_game_page_is_left_out_of_the_pot(self, demo):
        game = self._started_without(demo, [2])
        game.send(0, demo.Contribute(tokens=4))
        assert game.view(0)["no_shows"] == [2]
        game.tick(demo.ROUND_SECONDS)
        assert game.is_over() and game.end_reason() == "finished"

        outcome = game.outcome()
        share = demo.MULTIPLIER * 4 / 2
        assert (outcome["pot"], outcome["n_players"], outcome["share"]) == (4, 2, share)
        assert outcome["payoffs"] == [
            demo.ENDOWMENT - 4 + share,
            demo.ENDOWMENT + share,
            0,
        ]
        assert game.game.performance_reward(outcome, "finished", 2) == 0
        trial = SimpleNamespace(
            sync_group_id=1,
            participant_id=3,
            id=3,
            sync_group_round=0,
            group_round=SimpleNamespace(live_game_outcome=outcome),
            live_game=SimpleNamespace(answer=game.answer(2)),
        )
        row = demo._player_round_row(trial)
        assert (row["arrived"], row["contributed"], row["share"], row["earned"]) == (
            False,
            None,
            None,
            0,
        )

    def test_a_round_with_one_player_left_ends_early_without_a_pot(self, demo):
        game = self._started_without(demo, [1, 2])
        game.send(0, demo.Contribute(tokens=4))
        game.tick(demo.PublicGoods.away_timeout)

        assert game.is_over() and game.end_reason() == PLAYERS_LEFT
        outcome = game.outcome(PLAYERS_LEFT)
        assert (outcome["pot"], outcome["payoffs"]) == (0, [demo.ENDOWMENT, 0, 0])

    def test_a_contribution_is_between_none_and_the_endowment(self, demo):
        game = LocalGame(demo.PublicGoods, players=3)
        with pytest.raises(Reject, match="between 0 and"):
            game.send(0, demo.Contribute(tokens=demo.ENDOWMENT + 1))

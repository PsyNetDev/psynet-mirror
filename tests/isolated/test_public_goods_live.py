"""The public goods demo's rules: contributions and each player's
payoff."""

import pytest
from dallinger.realtime import Reject

from psynet.experiment import import_local_experiment
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
        assert game.answer(2) == {"contributed": 0, "earned": demo.ENDOWMENT + share}
        assert game.view(0)["contributions"] == [10, 2, 0]

    def test_a_player_who_never_opens_the_game_page_is_left_out_of_the_pot(self, demo):
        game = LocalGame(demo.PublicGoods, players=3, start=False)
        for player in [0, 1]:
            game.send(player, {"type": "psynet_ready", "message": {}})
        game.tick(demo.PublicGoods.ready_timeout)
        game.send(0, demo.Contribute(tokens=4))

        outcome = game.outcome()
        share = demo.MULTIPLIER * 4 / 2
        assert (outcome["n_players"], outcome["share"]) == (2, share)
        assert outcome["payoffs"] == [
            demo.ENDOWMENT - 4 + share,
            demo.ENDOWMENT + share,
            0,
        ]
        assert game.view(0)["no_shows"] == [2]

    def test_a_contribution_is_between_none_and_the_endowment(self, demo):
        game = LocalGame(demo.PublicGoods, players=3)
        with pytest.raises(Reject, match="between 0 and"):
            game.send(0, demo.Contribute(tokens=demo.ENDOWMENT + 1))

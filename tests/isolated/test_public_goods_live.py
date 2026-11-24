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
        settings = {"endowment": 10, "multiplier": 2}
        game = LocalGame(demo.PublicGoods, players=3, settings=settings)
        for player, tokens in enumerate([10, 4, 0]):
            game.send(player, demo.Contribute(tokens=tokens))
        # A player can change their mind until the time is up.
        game.send(1, demo.Contribute(tokens=2), now=5)

        outcome = game.outcome()
        assert (outcome["pot"], outcome["share"]) == (12, 8)
        assert outcome["payoffs"] == [8, 16, 18]
        assert game.answer(2) == {"contributed": 0, "earned": 18}
        # The page shows the pot from the settings in the view.
        view = game.view(0)
        assert (view["endowment"], view["multiplier"]) == (10, 2)
        assert view["contributions"] == [10, 2, 0]

    def test_a_contribution_is_between_none_and_the_endowment(self, demo):
        game = LocalGame(demo.PublicGoods, players=3, settings=demo.SETTINGS)
        with pytest.raises(Reject, match="between 0 and"):
            game.send(0, demo.Contribute(tokens=demo.SETTINGS["endowment"] + 1))

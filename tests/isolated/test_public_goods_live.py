"""The public goods demo's rules: contributions and each player's
payoff."""

from types import SimpleNamespace

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

    @pytest.mark.parametrize(
        "outcome, player, answer, expected",
        [
            # The player closed their page, so it saved no answer, but they
            # were paid from the game's outcome.
            ({"contributions": [0, 10], "payoffs": [17.5, 7.5]}, 1, None, (10, 7.5)),
            # The round hasn't ended yet.
            (None, 1, None, (None, None)),
            # The game ended before it could add the player.
            ({"contributions": [0], "payoffs": [10]}, None, None, (None, None)),
        ],
    )
    def test_the_export_has_each_players_round_from_the_outcome(
        self, demo, outcome, player, answer, expected
    ):
        game = SimpleNamespace(outcome=outcome, player=player)
        trial = SimpleNamespace(live_game=game, answer=answer)
        assert demo.round_result(trial) == expected

    def test_a_contribution_is_between_none_and_the_endowment(self, demo):
        game = LocalGame(demo.PublicGoods, players=3)
        with pytest.raises(Reject, match="between 0 and"):
            game.send(0, demo.Contribute(tokens=demo.ENDOWMENT + 1))

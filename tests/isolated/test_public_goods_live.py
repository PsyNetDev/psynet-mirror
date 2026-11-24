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
        settings = {"endowment": 10, "multiplier": 2}
        game = LocalGame(demo.PublicGoods, players=3, settings=settings)
        for player, tokens in enumerate([10, 4, 0]):
            game.send(player, demo.Contribute(tokens=tokens))
        # A player can change their mind until the time is up.
        game.send(1, demo.Contribute(tokens=2), now=5)

        outcome = game.outcome()
        assert (outcome["pot"], outcome["share"]) == (12, 8)
        assert outcome["payoffs"] == [8, 16, 18]
        assert game.answer(2) == {"arrived": True, "contributed": 0, "earned": 18}
        # The page shows the pot from the settings in the view.
        view = game.view(0)
        assert (view["endowment"], view["multiplier"]) == (10, 2)
        assert view["contributions"] == [10, 2, 0]

    def _started_without(self, demo, no_shows):
        """A round of three that starts without the players ``no_shows``."""
        game = LocalGame(
            demo.PublicGoods, players=3, settings=demo.SETTINGS, start=False
        )
        for player in {0, 1, 2} - set(no_shows):
            game.send(player, {"type": "psynet_ready", "message": {}})
        game.tick(demo.PublicGoods.ready_timeout)
        return game

    def _export_row(self, demo, game, player):
        """The player's export row for the round ``game`` played."""
        reason = game.end_reason()
        outcome = game.outcome(reason)
        trial = SimpleNamespace(
            sync_group_id=1,
            participant_id=player + 1,
            id=player + 1,
            sync_group_round=0,
            group_round=SimpleNamespace(live_game_outcome=outcome),
            live_game=SimpleNamespace(
                answer=game.answer(player, reason), end_reason=reason
            ),
        )
        row = demo._player_round_row(trial)
        keys = ["end_reason", "arrived", "contributed", "pot", "n_players"]
        return {key: row[key] for key in keys + ["share", "earned"]}

    def test_a_player_who_never_opens_the_game_page_is_left_out_of_the_pot(self, demo):
        game = self._started_without(demo, [2])
        game.send(0, demo.Contribute(tokens=4))
        assert game.view(0)["no_shows"] == [2]
        game.tick(demo.ROUND_SECONDS)
        assert game.is_over() and game.end_reason() == "finished"

        share = demo.SETTINGS["multiplier"] * 4 / 2
        # The page shows the pot and payoffs the server pays.
        assert game.view(0)["payoffs"] == [
            demo.SETTINGS["endowment"] - 4 + share,
            demo.SETTINGS["endowment"] + share,
            0,
        ]
        assert game.game.performance_reward(game.outcome(), "finished", 2) == 0
        assert self._export_row(demo, game, 2) == {
            "end_reason": "finished",
            "arrived": False,
            "contributed": None,
            "pot": 4,
            "n_players": 2,
            "share": None,
            "earned": 0,
        }

    def test_a_round_that_too_few_players_open_ends_at_the_start_without_a_pot(
        self, demo
    ):
        game = self._started_without(demo, [1, 2])

        assert game.is_over() and game.end_reason() == demo.TOO_FEW
        assert game.view(0)["payoffs"] == [demo.SETTINGS["endowment"], 0, 0]
        assert self._export_row(demo, game, 0) == {
            "end_reason": demo.TOO_FEW,
            "arrived": True,
            "contributed": 0,
            "pot": None,
            "n_players": 1,
            "share": None,
            "earned": demo.SETTINGS["endowment"],
        }

    def test_a_contribution_is_between_none_and_the_endowment(self, demo):
        game = LocalGame(demo.PublicGoods, players=3, settings=demo.SETTINGS)
        with pytest.raises(Reject, match="between 0 and"):
            game.send(0, demo.Contribute(tokens=demo.SETTINGS["endowment"] + 1))

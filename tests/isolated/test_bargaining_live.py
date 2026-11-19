"""The bargaining demo's rules: proposals, accepting the proposal the
player saw, and what players are told when a partner doesn't arrive."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from dallinger.realtime import Reject

from psynet.experiment import get_experiment, import_local_experiment
from psynet.live_game import PlayerReady
from psynet.live_game.testing import LocalGame
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.sync import SimpleSyncGroup, leave_group

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import new_participant  # noqa: E402


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

    @pytest.mark.parametrize(
        "reason, text",
        [
            ("late", "You didn't arrive in time, so the game is over for you."),
            ("no_show", "You didn't arrive in time, so the game is over for you."),
            ("left_game", "You left the game, so it's over for you."),
            (None, "That's the end of the game."),
        ],
    )
    def test_a_player_who_left_the_cohort_without_playing_is_told_on_the_last_page(
        self, demo, db_session, reason, text
    ):
        experiment = get_experiment()
        cohort = SimpleSyncGroup(
            group_type="cohort",
            initial_group_size=3,
            quorum=2,
            accepts_top_ups=False,
            below_quorum="continue_without_group",
        )
        db_session.add(cohort)
        players = [new_participant(experiment) for _ in range(3)]
        for player in players:
            player.status = "working"
            cohort.add_participant(player)
        cohort.check_numbers()
        db_session.commit()
        player = players[0]
        if reason is not None:
            cohort.remove_participant(player, reason)

        # The rounds end for them, and the timeline's last steps run.
        assert demo.keep_playing(player) is (reason is None)
        if reason is not None:
            assert demo.round_status(player) == "no_cohort"
        leave_group("cohort").consume(experiment, player)
        assert str(demo.end_of_game(player).content) == text

    def _feedback(self, demo, answer):
        trial = SimpleNamespace(answer=answer)
        return str(demo.BargainTrial.show_feedback(trial, None, None).content)

    def test_a_partner_who_never_opens_the_game_ends_it_at_the_start(self, demo):
        game = LocalGame(demo.Bargain, players=2, settings={"stake": 10}, start=False)
        game.send(0, PlayerReady())
        game.tick(demo.Bargain.ready_timeout)

        assert game.is_over()
        assert [game.view(player)["no_show"] for player in (0, 1)] == [
            "partner",
            "you",
        ]
        assert self._feedback(demo, game.answer(0)) == (
            "Your partner didn't arrive, so there was no game this round."
        )
        assert self._feedback(demo, game.answer(1)) == (
            "You didn't arrive in time, so there was no game this round."
        )

    @pytest.mark.parametrize("reason", ["finished", "not_joined"])
    def test_players_who_both_miss_the_game_are_each_told_they_didn_t_arrive(
        self, demo, reason
    ):
        game = LocalGame(demo.Bargain, players=2, settings={"stake": 10}, start=False)
        if reason == "finished":
            # They opened the game, then left before it started.
            game.tick(demo.Bargain.ready_timeout)

        for player in (0, 1):
            assert self._feedback(demo, game.answer(player, reason)) == (
                "You didn't arrive in time, so there was no game this round."
            )
        assert game.outcome(reason)["no_shows"] == [0, 1]

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

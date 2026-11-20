"""The fishing microsociety's rules: who fishes, who leaves and when, and
what a boat catches, tested by playing the game in Python."""

import random

import pytest
from dallinger.realtime import Reject

from psynet.experiment import import_local_experiment
from psynet.live_game.testing import LocalGame
from psynet.pytest_psynet import path_to_demo_experiment


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("microsociety_live")],
    indirect=True,
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestMicrosocietyLive:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    @pytest.fixture
    def lake(self, demo):
        def lake(members):
            random.seed(20261117)
            return LocalGame(demo.Fishing, players=members)

        return lake

    def test_a_newcomer_beyond_the_society_size_retires_the_longest_serving(
        self, demo, lake
    ):
        game = lake(demo.SOCIETY_SIZE)
        game.tick(10)
        newcomer = game.add(now=10)

        assert newcomer == demo.SOCIETY_SIZE
        assert game.is_done(0) and game.done_reason(0) == demo.RETIRED
        assert [game.is_done(p) for p in range(1, newcomer + 1)] == [False] * 3
        # The others no longer see the retired member's boat, and the
        # newcomer's boat has a colour of its own.
        seen = [boat["who"] for boat in game.view(1)["boats"]]
        assert seen == ["you", "pink", "grey"]
        assert not game.is_over()

    def test_each_member_fishes_for_stay_seconds_and_the_lake_closes_when_all_leave(
        self, demo, lake
    ):
        game = lake(1)
        game.tick(demo.STAY_SECONDS - 1)
        assert not game.is_done(0)

        # A member leaves at the first catch once their time is up.
        game.tick(demo.STAY_SECONDS + demo.CATCH_SECONDS)
        assert game.is_done(0) and game.done_reason(0) == demo.STAYED
        assert game.is_over()

    def test_a_boat_catches_only_at_a_spot_it_has_reached(self, demo, lake):
        game = lake(1)
        game.send(0, demo.Move(spot=6), now=2)
        # The boat arrives at 4, after the catch at 3.
        game.tick(3)
        assert game.state["latest"]["caught"] == []
        game.tick(6)
        (catch,) = game.state["latest"]["caught"]
        assert (catch["player"], catch["spot"]) == (0, 6)
        assert game.state["fish"][0] == catch["fish"]

    def test_a_move_to_no_spot_or_the_same_spot_is_rejected(self, demo, lake):
        game = lake(1)
        with pytest.raises(Reject, match="no such spot"):
            game.send(0, demo.Move(spot=0))
        game.send(0, demo.Move(spot=3))
        with pytest.raises(Reject, match="already there"):
            game.send(0, demo.Move(spot=3), now=1)
        assert game.state["moves"] == [1]

    def test_a_member_still_fishing_when_the_lake_closes_leaves_with_it(
        self, demo, lake
    ):
        game = lake(2)
        game.tick(20)
        game.add(now=20)
        game.tick(demo.STAY_SECONDS + demo.CATCH_SECONDS)

        assert game.answer(0, reason="timeout")["left"] == demo.STAYED
        # The newcomer joined later, so their time wasn't up.
        assert game.answer(2, reason="timeout")["left"] == "timeout"

    def test_a_newcomer_reads_the_tips_of_members_who_have_left(self, demo, db_session):
        from timeline_hold_helpers import new_participant

        from psynet.experiment import get_experiment
        from psynet.sync import SimpleSyncGroup

        founder, stayer, newcomer = [
            new_participant(get_experiment()) for _ in range(3)
        ]
        society = SimpleSyncGroup(group_type="society", initial_group_size=3)
        db_session.add(society)
        for member in (founder, stayer, newcomer):
            member.status = "working"
            society.add_participant(member)
        db_session.commit()
        # As the timeline does: the founder leaves the society, then tips.
        society.remove_participant(founder, reason="finished")
        founder.var.tip = "Spot C is good."

        assert "Spot C is good." in str(demo.history_page(newcomer).content)

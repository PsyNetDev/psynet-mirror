"""The rock, paper, scissors demo's rules, tested by calling the game's
methods directly, without starting the experiment."""

import json
from types import SimpleNamespace

import pytest

from psynet.experiment import import_local_experiment
from psynet.live_game import Reject
from psynet.live_game.testing import LocalGame
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.timeline import StartSwitch


def _choose(game, player, throw, action):
    message = {"type": "choose", "message": {"throw": throw, "action": action}}
    try:
        game.send(player, message)
    except Reject as rejection:
        return rejection.reason
    return "accepted"


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_demo_experiment("rock_paper_scissors_live")],
    indirect=True,
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestRockPaperScissorsLive:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    @pytest.fixture
    def new_game(self, demo):
        def new_game(throws=5):
            return LocalGame(
                demo.RockPaperScissors, players=2, settings={"throws": throws}
            )

        return new_game

    @pytest.fixture
    def finished(self, new_game):
        """A game of three throws. Player 0 wins the first two, choosing
        first in one and second in the other, and the last is a draw."""
        game = new_game(throws=3)
        plays = [
            (0, "paper", 1, "rock"),
            (1, "rock", 0, "paper"),
            (0, "paper", 1, "paper"),
        ]
        for throw, (first, first_action, second, second_action) in enumerate(plays, 1):
            assert not game.is_over()
            _choose(game, first, throw, first_action)
            _choose(game, second, throw, second_action)
        assert game.is_over()
        return game

    def test_a_view_hides_the_partners_choice_until_the_throw_is_over(self, new_game):
        game = new_game()
        _choose(game, 0, 1, "rock")
        waiting = game.view(1)
        assert waiting["partner_chosen"] and not waiting["chosen"]
        assert waiting["results"] == []
        assert "rock" not in json.dumps(waiting)

        _choose(game, 1, 1, "scissors")
        winner, loser = game.view(0), game.view(1)
        assert winner["results"] == [
            {"mine": "rock", "theirs": "scissors", "result": "win"}
        ]
        assert loser["results"] == [
            {"mine": "scissors", "theirs": "rock", "result": "loss"}
        ]
        assert (winner["wins"], winner["partner_wins"], winner["throw"]) == (1, 0, 2)

    def test_the_game_rejects_a_repeated_choice_another_throw_and_an_unknown_action(
        self, new_game
    ):
        game = new_game()
        _choose(game, 0, 1, "rock")
        _choose(game, 1, 1, "rock")

        assert _choose(game, 0, 2, "rock") == "accepted"
        assert _choose(game, 0, 2, "paper") == "You've already chosen this throw."
        assert _choose(game, 1, 1, "paper") == "That isn't the current throw."
        assert _choose(game, 1, 3, "paper") == "That isn't the current throw."
        assert "action" in _choose(game, 1, 2, "lizard")

    def test_the_game_has_the_throws_its_settings_say(self, new_game, finished):
        assert new_game(throws=3).view(0)["n_throws"] == 3
        assert finished.outcome() == {
            "throws": [["paper", "rock"], ["paper", "rock"], ["paper", "paper"]]
        }

    def test_each_player_s_answer_is_their_part_of_the_outcome(self, finished):
        assert finished.answer(1) == {
            "finished": True,
            "throws": [
                {"mine": "rock", "theirs": "paper", "result": "loss"},
                {"mine": "rock", "theirs": "paper", "result": "loss"},
                {"mine": "paper", "theirs": "paper", "result": "draw"},
            ],
            "wins": 0,
            "partner_wins": 2,
        }

    def test_the_trial_scores_the_throws_won_and_pays_its_definition_s_reward(
        self, demo, finished
    ):
        score = demo.RockPaperScissorsTrial.score_answer
        assert score(None, finished.answer(0), None) == 2
        assert score(None, finished.answer(1), None) == 0
        # A trial whose pair didn't start a game has no answer.
        assert score(None, None, None) == 0
        # Two throws won, at the 0.1 a throw that the trial's definition says.
        paid = SimpleNamespace(definition={"reward_per_win": 0.1})
        assert demo.RockPaperScissorsTrial.compute_performance_reward(
            paid, 2
        ) == pytest.approx(0.2)

    @pytest.mark.parametrize(
        "case, player, summary, score",
        [
            ("finished", 0, "You won the game!", "You won 2 of the 3 throws played"),
            (
                "finished",
                1,
                "Your partner won the game.",
                "You won 0 of the 3 throws played",
            ),
            ("draw", 0, "The game was a draw.", "You won 0 of the 1 throws played"),
            ("early", 0, "The game ended early.", "You won 2 of the 3 throws played"),
        ],
    )
    def test_the_feedback_page_shows_how_the_game_ended_and_the_bonus_paid(
        self, demo, new_game, finished, case, player, summary, score
    ):
        draw = new_game(throws=1)
        _choose(draw, 0, 1, "rock")
        _choose(draw, 1, 1, "rock")
        game, reason = {
            "finished": (finished, "finished"),
            "draw": (draw, "finished"),
            "early": (finished, "timeout"),
        }[case]
        feedback = str(demo.show_result(game.answer(player, reason), 0.2).content)
        assert f"<h2>{summary}</h2>" in feedback
        assert score in feedback
        assert "Your bonus for this game is $0.20." in feedback

    def test_the_feedback_page_says_when_no_throw_was_played(self, demo, new_game):
        answer = new_game().answer(0, "not_joined")
        page = demo.show_result(answer, 0.2)
        assert str(page.content) == "The game ended before any throws were played."

    def test_a_trial_without_an_answer_shows_no_feedback(self, demo, finished):
        gives_feedback = demo.RockPaperScissorsTrial.gives_feedback
        assert gives_feedback(SimpleNamespace(answer=finished.answer(0)), None, None)
        # A trial whose pair didn't start a game.
        assert not gives_feedback(SimpleNamespace(answer=None), None, None)

    @pytest.mark.parametrize(
        "in_pair, index, plays_a_game, told_no_more_games",
        [
            (True, 0, True, False),
            (True, 1, True, False),
            # Both games played.
            (True, 2, False, False),
            (False, 1, False, True),
        ],
    )
    def test_a_participant_without_a_partner_plays_no_more_games(
        self, demo, in_pair, index, plays_a_game, told_no_more_games
    ):
        # The conditions of the timeline's loop of games and of the page
        # after it, asked of a participant about to start the game at index.
        switches = {
            elt.label: elt
            for elt in demo.Exp.timeline.all_elts
            if isinstance(elt, StartSwitch)
        }
        participant = SimpleNamespace(
            id=1,
            in_sync_group=lambda group_type: in_pair and group_type == "pair",
            for_loops={"games": {"lst": [0, 1], "index": index}},
            module_state=None,
            append_branch_log=lambda entry: None,
        )

        def goes(label):
            return switches[label].function(experiment=None, participant=participant)

        assert goes("for_loop") is plays_a_game
        assert goes("no_more_games") is told_no_more_games

    def test_the_page_after_the_games_says_why_there_are_no_more(self, demo):
        def text(reason):
            participant = SimpleNamespace(
                sync_group_removal_reason=lambda group_type: (
                    reason if group_type == "pair" else None
                ),
                performance_reward=0.25,
            )
            return str(demo.no_more_games(participant).content)

        assert {reason: text(reason) for reason in demo.NO_PARTNER_TEXTS} == {
            "late": (
                "You didn't come back in time for the next game. Your bonus is $0.25."
            ),
            "group_dissolved": (
                "Your partner has left, so there are no more games. "
                "Your bonus is $0.25."
            ),
            "removed_by_experimenter": (
                "You were removed from the game. Your bonus is $0.25."
            ),
        }

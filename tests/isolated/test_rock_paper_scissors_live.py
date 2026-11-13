"""The rock, paper, scissors demo's rules, tested by calling the game's
methods directly, without starting the experiment."""

import json
from types import SimpleNamespace

import pytest
from dallinger.realtime import Reject, Sent

from psynet.experiment import import_local_experiment
from psynet.live_session.testing import start_session
from psynet.pytest_psynet import path_to_demo_experiment
from psynet.timeline import StartSwitch


def _choose(game, state, player_id, round, action):
    message = {"type": "choose", "message": {"round": round, "action": action}}
    try:
        game.apply(state, player_id, message, 0, Sent())
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
        def new_game(rounds=5):
            game = demo.RockPaperScissors()
            state = game.initial_state(["1", "2"], {"rounds": rounds})
            start_session(game, state)
            return game, state

        return new_game

    @pytest.fixture
    def finished(self, new_game):
        """The outcome of a game of three rounds. Player 1 wins the first two,
        choosing first in one and second in the other, and the last is a
        draw."""
        game, state = new_game(rounds=3)
        plays = [
            ("1", "paper", "2", "rock"),
            ("2", "rock", "1", "paper"),
            ("1", "paper", "2", "paper"),
        ]
        for round, (first, first_action, second, second_action) in enumerate(plays, 1):
            assert not game.is_over(state)
            _choose(game, state, first, round, first_action)
            _choose(game, state, second, round, second_action)
        assert game.is_over(state)
        return game.outcome(state, "finished")

    def test_a_view_hides_the_partners_choice_until_the_round_is_over(self, new_game):
        game, state = new_game()
        _choose(game, state, "1", 1, "rock")
        waiting = game.view(state, "2")
        assert waiting["partner_chosen"] and not waiting["chosen"]
        assert waiting["results"] == []
        assert "rock" not in json.dumps(waiting)

        _choose(game, state, "2", 1, "scissors")
        winner, loser = game.view(state, "1"), game.view(state, "2")
        assert winner["results"] == [
            {"mine": "rock", "theirs": "scissors", "result": "win"}
        ]
        assert loser["results"] == [
            {"mine": "scissors", "theirs": "rock", "result": "loss"}
        ]
        assert (winner["wins"], winner["partner_wins"], winner["round"]) == (1, 0, 2)

    def test_the_game_rejects_a_repeated_choice_another_round_and_an_unknown_action(
        self, new_game
    ):
        game, state = new_game()
        _choose(game, state, "1", 1, "rock")
        _choose(game, state, "2", 1, "rock")

        assert _choose(game, state, "1", 2, "rock") == "accepted"
        assert _choose(game, state, "1", 2, "paper") == (
            "You've already chosen this round."
        )
        assert _choose(game, state, "2", 1, "paper") == "That isn't the current round."
        assert _choose(game, state, "2", 3, "paper") == "That isn't the current round."
        assert "action" in _choose(game, state, "2", 2, "lizard")

    def test_the_game_has_the_rounds_its_settings_say(self, new_game, finished):
        game, state = new_game(rounds=3)
        assert game.view(state, "1")["n_rounds"] == 3
        assert finished["reason"] == "finished"
        assert len(finished["rounds"]) == 3
        assert finished["wins"] == {"1": 2, "2": 0}

    def test_the_trial_scores_the_rounds_won_and_pays_its_definition_s_bonus(
        self, demo, finished
    ):
        trial = demo.RockPaperScissorsTrial
        player, partner = (SimpleNamespace(participant_id=id) for id in (1, 2))
        assert trial.score_answer(player, finished, None) == 2
        assert trial.score_answer(partner, finished, None) == 0
        # A trial whose game page had no session has no answer.
        assert trial.score_answer(player, None, None) == 0
        # Two rounds won, at the 0.1 a round that the trial's definition says.
        paid = SimpleNamespace(definition={"bonus_per_win": 0.1})
        assert trial.compute_performance_reward(paid, 2) == pytest.approx(0.2)

    @pytest.mark.parametrize(
        "case, participant_id, summary, score",
        [
            ("finished", 1, "You won the game!", "You won 2 of the 3 rounds played"),
            (
                "finished",
                2,
                "Your partner won the game.",
                "You won 0 of the 3 rounds played",
            ),
            ("draw", 1, "The game was a draw.", "You won 1 of the 1 rounds played"),
            ("early", 1, "The game ended early.", "You won 2 of the 3 rounds played"),
        ],
    )
    def test_the_feedback_page_shows_how_the_game_ended_and_the_bonus_paid(
        self, demo, finished, case, participant_id, summary, score
    ):
        outcome = {
            "finished": finished,
            "draw": {"reason": "finished", "rounds": [{}], "wins": {"1": 1, "2": 1}},
            "early": {**finished, "reason": "max_duration"},
        }[case]
        participant = SimpleNamespace(id=participant_id)
        feedback = str(demo.show_result(participant, outcome, 0.2).content)
        assert f"<h2>{summary}</h2>" in feedback
        assert score in feedback
        assert "Your bonus for this game is $0.20." in feedback

    def test_the_feedback_page_says_when_no_round_was_played(self, demo):
        outcome = {"reason": "not_joined", "rounds": [], "wins": {"1": 0, "2": 0}}
        page = demo.show_result(SimpleNamespace(id=1), outcome, 0.2)
        assert str(page.content) == "The game ended before any rounds were played."

    def test_a_trial_without_an_answer_shows_no_feedback(self, demo, finished):
        gives_feedback = demo.RockPaperScissorsTrial.gives_feedback
        assert gives_feedback(SimpleNamespace(answer=finished), None, None)
        # A trial whose game page had no session.
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
            in_sync_group=lambda group_type: in_pair and group_type == demo.GROUP,
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
                    reason if group_type == demo.GROUP else None
                ),
                performance_reward=0.25,
            )
            return str(demo.no_more_games(participant).content)

        assert {reason: text(reason) for reason in demo.NO_PARTNER_TEXTS} == {
            "waited_too_long": (
                "Your partner didn't come back for the next game. Your bonus is $0.25."
            ),
            "group_dissolved": (
                "Your partner has left, so there are no more games. "
                "Your bonus is $0.25."
            ),
            "removed_by_experimenter": (
                "You were removed from the game. Your bonus is $0.25."
            ),
        }

"""The rock, paper, scissors demo's rules, tested by calling the game's
methods directly, without starting the experiment."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

DEMO = (
    Path(__file__).resolve().parents[2]
    / "demos"
    / "experiments"
    / "rock_paper_scissors_live"
)

# The cases run in the demo's directory, in a process of its own, so that
# importing the demo's experiment.py doesn't touch this test process's
# experiment.
CASES = """
import json, sys
from dallinger.realtime import Reject, Sent
from psynet.live_session.testing import start_session
import experiment


def new_game():
    game = experiment.RockPaperScissors()
    state = game.initial_state(["1", "2"], {"bonus_per_win": 0.1})
    start_session(game, state)
    return game, state


def choose(game, state, player_id, round, action):
    message = {"type": "choose", "message": {"round": round, "action": action}}
    try:
        game.apply(state, player_id, message, 0, Sent())
    except Reject as rejection:
        return rejection.reason
    return "accepted"


results = {}

game, state = new_game()
choose(game, state, "1", 1, "rock")
results["waiting"] = game.view(state, "2")
choose(game, state, "2", 1, "scissors")
results["round"] = {"1": game.view(state, "1"), "2": game.view(state, "2")}

game, state = new_game()
results["rejections"] = [
    choose(game, state, "1", 1, "rock"),
    choose(game, state, "1", 1, "paper"),
    choose(game, state, "2", 2, "paper"),
    choose(game, state, "2", 1, "lizard"),
]

game, state = new_game()
# Player 1 wins the first two rounds, choosing first in one and second in
# the other, and the rest are draws.
choose(game, state, "1", 1, "paper")
choose(game, state, "2", 1, "rock")
choose(game, state, "2", 2, "rock")
choose(game, state, "1", 2, "paper")
for round in range(3, experiment.N_ROUNDS + 1):
    over_before_last_round = game.is_over(state)
    choose(game, state, "1", round, "paper")
    choose(game, state, "2", round, "paper")
outcome = game.outcome(state, "finished")
results["game"] = {
    "over_before_last_round": over_before_last_round,
    "over": game.is_over(state),
    "wins": outcome["wins"],
    "bonus": game.bonus(outcome, "finished", "1"),
}

json.dump(results, sys.stdout)
"""


@pytest.fixture(scope="module")
def results():
    run = subprocess.run(
        [sys.executable, "-c", CASES],
        cwd=DEMO,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(run.stdout)


def test_a_view_hides_the_partners_choice_until_the_round_is_over(results):
    waiting = results["waiting"]
    assert waiting["partner_chosen"] and not waiting["chosen"]
    assert waiting["results"] == []
    assert "rock" not in json.dumps(waiting)
    winner, loser = results["round"]["1"], results["round"]["2"]
    assert winner["results"] == [
        {"mine": "rock", "theirs": "scissors", "result": "win"}
    ]
    assert loser["results"] == [
        {"mine": "scissors", "theirs": "rock", "result": "loss"}
    ]
    assert (winner["wins"], winner["partner_wins"], winner["round"]) == (1, 0, 2)


def test_the_game_rejects_a_repeated_choice_another_round_and_an_unknown_action(
    results,
):
    accepted, repeated, wrong_round, unknown = results["rejections"]
    assert accepted == "accepted"
    assert repeated == "You've already chosen this round."
    assert wrong_round == "That round is over."
    assert "action" in unknown


def test_the_game_ends_after_the_last_round_and_pays_for_each_round_won(results):
    game = results["game"]
    assert not game["over_before_last_round"]
    assert game["over"]
    assert game["wins"] == {"1": 2, "2": 0}
    # Two rounds won, at the 0.1 a round that the game's settings say.
    assert game["bonus"] == pytest.approx(0.2)

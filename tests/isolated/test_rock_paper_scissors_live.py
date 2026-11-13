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
import json, sys, types
from dallinger.realtime import Reject, Sent
from psynet.live_session.testing import start_session
import experiment


def new_game(rounds=5):
    game = experiment.RockPaperScissors()
    state = game.initial_state(["1", "2"], {"rounds": rounds})
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
choose(game, state, "1", 1, "rock")
choose(game, state, "2", 1, "rock")
results["rejections"] = [
    choose(game, state, "1", 2, "rock"),
    choose(game, state, "1", 2, "paper"),
    choose(game, state, "2", 1, "paper"),
    choose(game, state, "2", 3, "paper"),
    choose(game, state, "2", 2, "lizard"),
]

game, state = new_game(rounds=3)
results["n_rounds"] = game.view(state, "1")["n_rounds"]
# Player 1 wins the first two rounds, choosing first in one and second in
# the other, and the last is a draw.
plays = [
    ("1", "paper", "2", "rock"),
    ("2", "rock", "1", "paper"),
    ("1", "paper", "2", "paper"),
]
over_before_each_round = []
for round, (first, first_action, second, second_action) in enumerate(plays, 1):
    over_before_each_round.append(game.is_over(state))
    choose(game, state, first, round, first_action)
    choose(game, state, second, round, second_action)
finished = game.outcome(state, "finished")
results["game"] = {
    "over_before_each_round": over_before_each_round,
    "over": game.is_over(state),
    "outcome": finished,
}

trial = experiment.RockPaperScissorsTrial
player = types.SimpleNamespace(participant_id=1)
paid = types.SimpleNamespace(definition={"bonus_per_win": 0.1})
results["scores"] = [
    trial.score_answer(player, finished, None),
    trial.score_answer(types.SimpleNamespace(participant_id=2), finished, None),
    trial.score_answer(player, None, None),
]
results["reward"] = trial.compute_performance_reward(paid, 2)


def feedback(outcome, participant_id=1):
    participant = types.SimpleNamespace(id=participant_id)
    return str(experiment.show_result(participant, outcome, 0.2).content)


draw = {"reason": "finished", "rounds": [{}], "wins": {"1": 1, "2": 1}}
results["feedback"] = {
    "won": feedback(finished),
    "lost": feedback(finished, participant_id=2),
    "draw": feedback(draw),
    "early": feedback({**finished, "reason": "max_duration"}),
    "no_rounds": feedback(
        {"reason": "not_joined", "rounds": [], "wins": {"1": 0, "2": 0}}
    ),
}

results["feedback_given"] = [
    trial.gives_feedback(types.SimpleNamespace(answer=answer), None, None)
    for answer in (finished, None)
]


# The conditions of the timeline's loop of games and of the page after it,
# asked of a participant who is about to start the game at ``index``.
switches = {
    elt.label: elt
    for elt in experiment.Exp.timeline.all_elts
    if type(elt).__name__ == "StartSwitch"
}


def timeline_goes(in_pair, index, reason=None):
    participant = types.SimpleNamespace(
        id=1,
        in_sync_group=lambda group_type: in_pair and group_type == experiment.GROUP,
        for_loops={"games": {"lst": [0, 1], "index": index}},
        module_state=None,
        append_branch_log=lambda entry: None,
    )
    return {
        "plays_a_game": switches["for_loop"].function(
            experiment=None, participant=participant
        ),
        "told_no_more_games": switches["no_more_games"].function(
            experiment=None, participant=participant
        ),
    }


results["timeline"] = {
    "in_pair_first": timeline_goes(True, 0),
    "in_pair_second": timeline_goes(True, 1),
    "in_pair_after": timeline_goes(True, 2),
    "alone_second": timeline_goes(False, 1),
}


def no_more_games(reason):
    participant = types.SimpleNamespace(
        sync_group_removal_reason=lambda group_type: (
            reason if group_type == experiment.GROUP else None
        ),
        performance_reward=0.25,
    )
    return str(experiment.no_more_games(participant).content)


results["no_more_games"] = {
    reason: no_more_games(reason) for reason in experiment.NO_PARTNER_TEXTS
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
    accepted, repeated, earlier_round, later_round, unknown = results["rejections"]
    assert accepted == "accepted"
    assert repeated == "You've already chosen this round."
    assert earlier_round == later_round == "That isn't the current round."
    assert "action" in unknown


def test_the_game_has_the_rounds_its_settings_say(results):
    game = results["game"]
    assert results["n_rounds"] == 3
    assert game["over_before_each_round"] == [False, False, False]
    assert game["over"]
    assert game["outcome"]["reason"] == "finished"
    assert len(game["outcome"]["rounds"]) == 3
    assert game["outcome"]["wins"] == {"1": 2, "2": 0}


def test_the_trial_scores_the_rounds_won_and_pays_its_definition_s_bonus(results):
    # Player 1's rounds, player 2's, and those of a trial whose game page had
    # no session.
    assert results["scores"] == [2, 0, 0]
    # Two rounds won, at the 0.1 a round that the trial's definition says.
    assert results["reward"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    "case, summary, score",
    [
        ("won", "You won the game!", "You won 2 of the 3 rounds played"),
        ("lost", "Your partner won the game.", "You won 0 of the 3 rounds played"),
        ("draw", "The game was a draw.", "You won 1 of the 1 rounds played"),
        ("early", "The game ended early.", "You won 2 of the 3 rounds played"),
    ],
)
def test_the_feedback_page_shows_how_the_game_ended_and_the_bonus_paid(
    results, case, summary, score
):
    feedback = results["feedback"][case]
    assert f"<h2>{summary}</h2>" in feedback
    assert score in feedback
    assert "Your bonus for this game is $0.20." in feedback


def test_the_feedback_page_says_when_no_round_was_played(results):
    assert results["feedback"]["no_rounds"] == (
        "The game ended before any rounds were played."
    )


def test_a_trial_without_an_answer_shows_no_feedback(results):
    # A trial whose game was played, and one whose game page had no session.
    assert results["feedback_given"] == [True, False]


def test_a_participant_without_a_partner_plays_no_more_games(results):
    timeline = results["timeline"]
    played = {"plays_a_game": True, "told_no_more_games": False}
    assert timeline["in_pair_first"] == timeline["in_pair_second"] == played
    assert timeline["in_pair_after"] == {
        "plays_a_game": False,
        "told_no_more_games": False,
    }
    assert timeline["alone_second"] == {
        "plays_a_game": False,
        "told_no_more_games": True,
    }


def test_the_page_after_the_games_says_why_there_are_no_more(results):
    assert results["no_more_games"] == {
        "waited_too_long": (
            "Your partner didn't come back for the next game. Your bonus is $0.25."
        ),
        "group_dissolved": (
            "Your partner has left, so there are no more games. Your bonus is $0.25."
        ),
        "removed_by_experimenter": (
            "You were removed from the game. Your bonus is $0.25."
        ),
    }

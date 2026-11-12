"""The snake demo's rules: how the game moves the snakes on each tick, and
which turns it accepts."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[2] / "demos" / "experiments" / "snake_live"

# Each case sets up a game, plays it with the game's own methods, and reports
# what happened. It runs in the demo's
# directory, in a process of its own, so that importing the demo's
# experiment.py doesn't touch this test process's experiment.
CASES = """
import json, random, sys
from dallinger.realtime import Reject, Sent
from psynet.live_session.testing import start_session
import experiment


def game_with(snakes, food):
    # snakes maps each player to their snake's body, head first, and its
    # direction.
    game = experiment.Snake()
    state = game.initial_state(list(snakes))
    start_session(game, state)
    for player_id, (body, direction) in snakes.items():
        state["players"][player_id].update(body=body, direction=direction)
    state["food"] = food
    return game, state


def turn(game, state, direction):
    message = {"type": "turn", "message": {"direction": direction}}
    try:
        game.apply(state, "1", message, 0, Sent())
    except Reject as rejection:
        return rejection.reason
    return "accepted"


results = {}

game, state = game_with(
    {"1": ([[5, 5], [4, 5], [3, 5]], "right"), "2": ([[5, 20], [4, 20], [3, 20]], "right")},
    food=[[6, 5], [29, 29]],
)
game.tick(state, 1)
results["eat"] = state["players"]

game, state = game_with(
    {"1": ([[10, 10], [9, 10], [8, 10]], "right"), "2": ([[5, 20], [4, 20], [3, 20]], "right")},
    food=[[29, 29], [29, 28]],
)
results["turns"] = [turn(game, state, d) for d in ["left", "up", "left", "down"]]
bodies = []
for now in [1, 1.125]:
    game.tick(state, now)
    bodies.append(list(state["players"]["1"]["body"]))
results["u_turn"] = bodies

game, state = game_with(
    {"1": ([[29, 5], [28, 5], [27, 5]], "right"), "2": ([[5, 20], [4, 20], [3, 20]], "right")},
    food=[[0, 29], [1, 29]],
)
game.tick(state, 1)
crashed = dict(state["players"]["1"])
results["crash_turn"] = turn(game, state, "up")
game.tick(state, 2.5)
early = list(state["players"]["1"]["body"])
game.tick(state, 3)
results["crash"] = {"crashed": crashed, "early": early, "back": state["players"]["1"]}

game, state = game_with(
    {"1": ([[10, 10], [9, 10], [8, 10]], "right"), "2": ([[12, 10], [13, 10], [14, 10]], "left")},
    food=[[0, 29], [1, 29]],
)
game.tick(state, 1)
results["head_on"] = state["players"]

# A snake can follow another's tail, since the tail moves on in the same
# tick, unless the snake ahead eats and keeps its tail.
for case, food in [("follow", [[0, 29], [1, 29]]), ("follow_eater", [[14, 10], [1, 29]])]:
    game, state = game_with(
        {"1": ([[10, 10], [9, 10], [8, 10]], "right"), "2": ([[13, 10], [12, 10], [11, 10]], "right")},
        food=food,
    )
    game.tick(state, 1)
    results[case] = state["players"]

game, state = game_with(
    {"1": ([[10, 10], [9, 10], [8, 10]], "right"), "2": ([[11, 10], [12, 10], [13, 10]], "left")},
    food=[[0, 29], [1, 29]],
)
game.tick(state, 1)
results["swap"] = state["players"]


def squares_ahead(player):
    square, squares = player["body"][0], []
    for _ in range(3):
        square = experiment.step(square, player["direction"])
        squares.append(tuple(square))
    return squares


# Two crashed snakes come back on the same tick as a long snake moves.
random.seed(20261110)
room = []
for _ in range(200):
    long = [[x, 15] for x in range(20, 4, -1)]
    game, state = game_with(
        {"1": ([], "right"), "2": ([], "right"), "3": (long, "right")},
        food=[[0, 0], [29, 29], [0, 29]],
    )
    for player_id in ["1", "2"]:
        state["players"][player_id]["back_at"] = 1
    game.tick(state, 1)
    players = state["players"]
    if not len(players["1"]["body"]) == len(players["2"]["body"]) == 3:
        room.append(False)
        continue
    # The squares that must be clear of everything else: each returning
    # snake's body and its three squares ahead, and the long snake's body
    # and the squares next to its head, which it could turn into.
    long_snake = [tuple(square) for square in players["3"]["body"]]
    around = {tuple(experiment.step(long_snake[0], d)) for d in experiment.DIRECTIONS}
    claimed = [
        [tuple(square) for square in players[p]["body"]] + squares_ahead(players[p])
        for p in ["1", "2"]
    ] + [long_snake + sorted(around - set(long_snake))]
    every = [square for squares in claimed for square in squares]
    room.append(
        len(set(every)) == len(every)
        and all(experiment.on_board(square) for square in every)
        and not set(every) & {(0, 0), (29, 29), (0, 29)}
    )
results["room"] = room

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


def test_every_snake_moves_a_square_each_tick_and_grows_when_it_eats(results):
    eater, other = results["eat"]["1"], results["eat"]["2"]
    assert eater["body"] == [[6, 5], [5, 5], [4, 5], [3, 5]]
    assert eater["food"] == 1
    assert other["body"] == [[6, 20], [5, 20], [4, 20]]
    assert other["food"] == 0


def test_two_quick_turns_make_a_u_turn_but_a_snake_cant_reverse(results):
    assert results["turns"] == [
        "A snake can't turn back on itself.",
        "accepted",
        "accepted",
        "You've pressed too many keys at once.",
    ]
    # The snake makes one turn a tick: up, then left.
    assert results["u_turn"] == [
        [[10, 9], [10, 10], [9, 10]],
        [[9, 9], [10, 9], [10, 10]],
    ]


def test_a_snake_that_hits_a_wall_comes_back_two_seconds_later(results):
    crash = results["crash"]
    assert crash["crashed"]["body"] == []
    assert crash["crashed"]["crashes"] == 1
    assert crash["crashed"]["back_at"] == 3
    assert results["crash_turn"] == "Your snake will be back in a moment."
    assert crash["early"] == []
    assert len(crash["back"]["body"]) == 3
    assert crash["back"]["back_at"] is None


def test_a_snake_can_follow_a_tail_unless_the_snake_ahead_eats(results):
    assert results["follow"]["1"]["body"] == [[11, 10], [10, 10], [9, 10]]
    assert results["follow"]["2"]["body"] == [[14, 10], [13, 10], [12, 10]]
    assert results["follow_eater"]["1"]["body"] == []
    assert results["follow_eater"]["2"]["food"] == 1


def test_crashed_snakes_come_back_with_room_ahead(results):
    assert all(results["room"]), results["room"].index(False)


def test_two_heads_that_meet_both_crash(results):
    assert results["head_on"]["1"]["body"] == []
    assert results["head_on"]["2"]["body"] == []
    assert results["head_on"]["1"]["crashes"] == results["head_on"]["2"]["crashes"] == 1
    # Heads that pass through each other meet too.
    assert results["swap"]["1"]["body"] == results["swap"]["2"]["body"] == []

"""The snake demo's rules: how the game moves the snakes on each tick, and
which turns it accepts."""

import random

import pytest
from dallinger.realtime import Reject, Sent

from psynet.experiment import import_local_experiment
from psynet.live_session.testing import start_session
from psynet.pytest_psynet import path_to_demo_experiment

# Food that no snake in these games reaches.
FAR_FOOD = [[0, 29], [1, 29]]


def _turn(game, state, direction):
    message = {"type": "turn", "message": {"direction": direction}}
    try:
        game.apply(state, "1", message, 0, Sent())
    except Reject as rejection:
        return rejection.reason
    return "accepted"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("snake_live")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
class TestSnakeLive:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    @pytest.fixture
    def game_with(self, demo):
        def game_with(snakes, food):
            # snakes maps each player to their snake's body, head first, and
            # its direction.
            game = demo.Snake()
            state = game.initial_state(list(snakes))
            start_session(game, state)
            for player_id, (body, direction) in snakes.items():
                state["players"][player_id].update(body=body, direction=direction)
            state["food"] = [list(square) for square in food]
            return game, state

        return game_with

    def test_every_snake_moves_a_square_each_tick_and_grows_when_it_eats(
        self, game_with
    ):
        game, state = game_with(
            {
                "1": ([[5, 5], [4, 5], [3, 5]], "right"),
                "2": ([[5, 20], [4, 20], [3, 20]], "right"),
            },
            food=[[6, 5], [29, 29]],
        )
        game.tick(state, 1)
        eater, other = state["players"]["1"], state["players"]["2"]
        assert eater["body"] == [[6, 5], [5, 5], [4, 5], [3, 5]]
        assert eater["food"] == 1
        assert other["body"] == [[6, 20], [5, 20], [4, 20]]
        assert other["food"] == 0

    def test_two_quick_turns_make_a_u_turn_but_a_snake_cant_reverse(self, game_with):
        game, state = game_with(
            {
                "1": ([[10, 10], [9, 10], [8, 10]], "right"),
                "2": ([[5, 20], [4, 20], [3, 20]], "right"),
            },
            food=[[29, 29], [29, 28]],
        )
        assert [_turn(game, state, d) for d in ["left", "up", "left", "down"]] == [
            "A snake can't turn back on itself.",
            "accepted",
            "accepted",
            "You've pressed too many keys at once.",
        ]
        # The snake makes one turn a tick: up, then left.
        game.tick(state, 1)
        assert state["players"]["1"]["body"] == [[10, 9], [10, 10], [9, 10]]
        game.tick(state, 1.125)
        assert state["players"]["1"]["body"] == [[9, 9], [10, 9], [10, 10]]

    def test_a_snake_that_hits_a_wall_comes_back_two_seconds_later(self, game_with):
        game, state = game_with(
            {
                "1": ([[29, 5], [28, 5], [27, 5]], "right"),
                "2": ([[5, 20], [4, 20], [3, 20]], "right"),
            },
            food=FAR_FOOD,
        )
        game.tick(state, 1)
        crashed = state["players"]["1"]
        assert crashed["body"] == []
        assert crashed["crashes"] == 1
        assert crashed["back_at"] == 3
        assert _turn(game, state, "up") == "Your snake will be back in a moment."
        game.tick(state, 2.5)
        assert state["players"]["1"]["body"] == []
        game.tick(state, 3)
        back = state["players"]["1"]
        assert len(back["body"]) == 3
        assert back["back_at"] is None

    @pytest.mark.parametrize(
        "food, follower, leader_food",
        [
            # The tail ahead moves on in the same tick.
            (FAR_FOOD, [[11, 10], [10, 10], [9, 10]], 0),
            # A snake that eats keeps its tail.
            ([[14, 10], [1, 29]], [], 1),
        ],
    )
    def test_a_snake_can_follow_a_tail_unless_the_snake_ahead_eats(
        self, game_with, food, follower, leader_food
    ):
        game, state = game_with(
            {
                "1": ([[10, 10], [9, 10], [8, 10]], "right"),
                "2": ([[13, 10], [12, 10], [11, 10]], "right"),
            },
            food=food,
        )
        game.tick(state, 1)
        assert state["players"]["1"]["body"] == follower
        assert state["players"]["2"]["body"][0] == [14, 10]
        assert state["players"]["2"]["food"] == leader_food

    @pytest.mark.parametrize(
        "other",
        [
            # The heads meet on one square.
            [[12, 10], [13, 10], [14, 10]],
            # The heads pass through each other.
            [[11, 10], [12, 10], [13, 10]],
        ],
    )
    def test_two_heads_that_meet_both_crash(self, game_with, other):
        game, state = game_with(
            {"1": ([[10, 10], [9, 10], [8, 10]], "right"), "2": (other, "left")},
            food=FAR_FOOD,
        )
        game.tick(state, 1)
        for player in state["players"].values():
            assert player["body"] == []
            assert player["crashes"] == 1

    def test_crashed_snakes_come_back_with_room_ahead(self, demo, game_with):
        def squares_ahead(player):
            square, squares = player["body"][0], []
            for _ in range(3):
                square = demo.step(square, player["direction"])
                squares.append(tuple(square))
            return squares

        food = [[0, 0], [29, 29], [0, 29]]
        random.seed(20261110)
        for attempt in range(200):
            # Two crashed snakes come back on the same tick as a long snake
            # moves.
            long = [[x, 15] for x in range(20, 4, -1)]
            game, state = game_with(
                {"1": ([], "right"), "2": ([], "right"), "3": (long, "right")},
                food=food,
            )
            for player_id in ["1", "2"]:
                state["players"][player_id]["back_at"] = 1
            game.tick(state, 1)
            players = state["players"]
            assert len(players["1"]["body"]) == len(players["2"]["body"]) == 3
            # The squares that must be clear of everything else: each
            # returning snake's body and its three squares ahead, and the
            # long snake's body and the squares next to its head, which it
            # could turn into.
            long_snake = [tuple(square) for square in players["3"]["body"]]
            around = {tuple(demo.step(long_snake[0], d)) for d in demo.DIRECTIONS}
            claimed = [
                [tuple(square) for square in players[p]["body"]]
                + squares_ahead(players[p])
                for p in ["1", "2"]
            ] + [long_snake + sorted(around - set(long_snake))]
            every = [square for squares in claimed for square in squares]
            assert len(set(every)) == len(every), attempt
            assert all(demo.on_board(square) for square in every), attempt
            assert not set(every) & {tuple(square) for square in food}, attempt

"""The shared canvas demo holds every player to the game's clock, and its page
works out each move just as the game does, so its prediction of the player's
own piece lands where the game puts it."""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest
from dallinger.realtime import Reject, Sent

from psynet.experiment import import_local_experiment
from psynet.live_session.testing import start_session
from psynet.pytest_psynet import path_to_demo_experiment

DEMO = path_to_demo_experiment("shared_canvas_live")

# Node 20 doesn't load a .js file written as a module, so the page's script
# is imported from its source.
PAGE_MOVES = """
import fs from "node:fs";
const [script, input] = process.argv.slice(1);
const source = fs.readFileSync(script, "utf8");
const { advance } = await import("data:text/javascript," + encodeURIComponent(source));
const { rules, cases } = JSON.parse(fs.readFileSync(input, "utf8"));
const results = cases.map((case_) => {
  const view = { me: "1", players: { 1: case_.player }, coins: case_.coins };
  for (const [dx, dy, seconds] of case_.moves) {
    advance(rules, view, dx, dy, seconds);
  }
  return { player: view.players[1], coins: view.coins };
});
process.stdout.write(JSON.stringify(results));
"""


def random_case(rng):
    """A player somewhere on the canvas, sometimes against a wall, a few
    coins and a run of moves, some with no keys held so the player coasts."""
    player = {
        "x": rng.choice([12, 628, rng.uniform(12, 628)]),
        "y": rng.choice([12, 628, rng.uniform(12, 628)]),
        "vx": rng.uniform(-300, 300),
        "vy": rng.uniform(-300, 300),
        "coins": 0,
    }
    coins = [
        {"id": i, "x": rng.uniform(40, 600), "y": rng.uniform(40, 600)}
        for i in range(rng.randrange(10))
    ]
    moves = [
        [rng.choice([-1, 0, 0, 1]), rng.choice([-1, 0, 0, 1]), rng.uniform(0.001, 0.5)]
        for _ in range(rng.randrange(1, 40))
    ]
    return {"player": player, "coins": coins, "moves": moves}


@pytest.mark.parametrize("experiment_directory", [DEMO], indirect=True)
@pytest.mark.usefixtures("in_experiment_directory")
class TestSharedCanvasLive:
    @pytest.fixture
    def demo(self):
        return import_local_experiment()["module"]

    def test_a_page_cannot_move_its_player_faster_than_the_game_clock(self, demo):
        game = demo.SharedCanvas()
        state = game.initial_state(["1", "2"])
        start_session(game, state, now=10)

        def move(now):
            message = {"type": "move", "message": {"dx": 1, "dy": 0, "seconds": 0.5}}
            try:
                game.apply(state, "1", message, now, Sent())
            except Reject as rejection:
                return rejection.reason
            return state["players"]["1"]["moved_until"]

        used_up = "You've used up your movement time."
        # The session starts at session time 10, and nobody could move before
        # the start.
        assert move(10) == used_up
        # After 10 seconds standing still, the player can catch up on at most
        # SAVED_MOVEMENT of that time, so the first move is spent up to the
        # clock, and others sent at once get nothing.
        assert move(20) == 20
        assert move(20) == move(20) == used_up
        # By then the clock has moved on 0.2 seconds, so that's all the move
        # gets.
        assert move(20.2) == pytest.approx(20.2)

    def test_the_page_moves_players_exactly_as_the_game_does(self, demo, tmp_path):
        node = shutil.which("node")
        assert node, "node is required to run the page's moves"
        rng = random.Random(20261110)
        cases = [random_case(rng) for _ in range(500)]

        by_game = []
        # The game changes its state in place, so it gets a copy of each case.
        for case in json.loads(json.dumps(cases)):
            state = {
                "players": {"1": case["player"]},
                "coins": case["coins"],
                "collected": [],
            }
            for dx, dy, seconds in case["moves"]:
                demo.advance(state, "1", dx, dy, seconds, now=0)
            by_game.append({"player": state["players"]["1"], "coins": state["coins"]})

        page_input = tmp_path / "cases.json"
        page_input.write_text(json.dumps({"rules": demo.RULES, "cases": cases}))
        page = subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                PAGE_MOVES,
                str(Path(DEMO) / "static" / "shared-canvas.js"),
                str(page_input),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        by_page = json.loads(page.stdout)

        assert len(by_page) == len(cases)
        for case, game_result, page_result in zip(cases, by_game, by_page):
            expected = {
                key: game_result["player"][key]
                for key in ("x", "y", "vx", "vy", "coins")
            }
            assert page_result["player"] == expected, case
            assert page_result["coins"] == game_result["coins"], case

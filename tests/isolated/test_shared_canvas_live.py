"""The shared canvas demo holds every player to the game's clock, and its page
works out each move just as the game does, so its prediction of the player's
own piece lands where the game puts it."""

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demos" / "experiments" / "shared_canvas_live"


def run_in_demo(script, stdin=""):
    """Run ``script`` in the demo's directory and return what it prints, read
    as JSON. It runs in a process of its own, so that importing the demo's
    experiment.py doesn't touch this test process's experiment."""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=DEMO,
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


# The session starts at session time 10. A move sent at once is rejected,
# since nobody could move before the start. Then a player who has stood still
# for 10 seconds sends half-second moves, three at once and one 0.2 seconds
# later.
FAST_MOVES = """
import json, sys
from dallinger.realtime import Reject, Sent
from psynet.live_session.testing import start_session
import experiment

game = experiment.SharedCanvas()
state = game.initial_state(["1", "2"])
start_session(game, state, now=10)
results = []
for now in [10, 20, 20, 20, 20.2]:
    move = {"type": "move", "message": {"dx": 1, "dy": 0, "seconds": 0.5}}
    try:
        game.apply(state, "1", move, now, Sent())
        results.append(state["players"]["1"]["moved_until"])
    except Reject as rejection:
        results.append(rejection.reason)
json.dump(results, sys.stdout)
"""


def test_a_page_cannot_move_its_player_faster_than_the_game_clock():
    at_start, accepted, second, third, later = run_in_demo(FAST_MOVES)
    used_up = "You've used up your movement time."
    assert at_start == used_up
    # The player can catch up on at most SAVED_MOVEMENT of the time they
    # stood still, so the first move is spent up to the clock.
    assert accepted == 20
    assert second == third == used_up
    # By then the clock has moved on 0.2 seconds, so that's all the move gets.
    assert later == pytest.approx(20.2)


GAME_MOVES = """
import json, sys
import experiment

cases = json.load(sys.stdin)
results = []
for case in cases:
    state = {"players": {"1": case["player"]}, "coins": case["coins"], "collected": []}
    for dx, dy, seconds in case["moves"]:
        experiment.advance(state, "1", dx, dy, seconds, now=0)
    results.append({"player": state["players"]["1"], "coins": state["coins"]})
json.dump({"rules": experiment.RULES, "results": results}, sys.stdout)
"""

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


def test_the_page_moves_players_exactly_as_the_game_does(tmp_path):
    node = shutil.which("node")
    assert node, "node is required to run the page's moves"
    rng = random.Random(20261110)
    cases = [random_case(rng) for _ in range(500)]

    game = run_in_demo(GAME_MOVES, json.dumps(cases))
    page_input = tmp_path / "cases.json"
    page_input.write_text(json.dumps({"rules": game["rules"], "cases": cases}))
    page = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            PAGE_MOVES,
            str(DEMO / "static" / "shared-canvas.js"),
            str(page_input),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    page = json.loads(page.stdout)

    assert len(page) == len(cases)
    for case, by_game, by_page in zip(cases, game["results"], page):
        expected = {
            key: by_game["player"][key] for key in ("x", "y", "vx", "vy", "coins")
        }
        assert by_page["player"] == expected, case
        assert by_page["coins"] == by_game["coins"], case

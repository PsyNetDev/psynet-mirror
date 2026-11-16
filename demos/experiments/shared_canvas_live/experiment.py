"""A shared canvas, played as a live session.

A group of players moves around one canvas with the arrow keys, collecting
coins, for ``ROUND_SECONDS``. Players speed up while a key is held and slow
down once it's released. The server works out where each player is from the
moves their page sends, and which coins they pass over. The page shows the
player's own moves at once by predicting them, and draws the other players
moving smoothly between the game's ticks. Each coin collected pays a bonus.
"""

import math
import random
from typing import Literal

import pytest
from dallinger.realtime import Reject
from dominate import tags
from pydantic import Field

import psynet.experiment
from psynet.live_game import (
    LiveGame,
    LiveGameControl,
    LiveMessage,
    PlayLiveGame,
    live_game_id,
    live_game_result,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import PageMaker, Timeline

#: Each player's color, in the order they signed up. There's one for each
#: player a game can have.
COLORS = [
    "#1f77b4",
    "#d62728",
    "#2ca02c",
    "#9467bd",
    "#ff7f0e",
    "#17becf",
    "#e377c2",
    "#8c564b",
]

#: Players in each game, from 2 to ``len(COLORS)``, the game's
#: ``max_players``.
GROUP_SIZE = 2

#: The canvas is this many pixels square.
SIZE = 640
PLAYER_RADIUS = 12
COIN_RADIUS = 10
#: A player collects every coin their path passes within this distance of.
REACH = PLAYER_RADIUS + COIN_RADIUS
BONUS_PER_COIN = 0.02
ROUND_SECONDS = 30

#: The canvas starts with this many coins per player, and never holds more.
#: While it holds fewer, a new coin appears every COIN_SECONDS divided by the
#: number of players.
COINS_PER_PLAYER = 3
COIN_SECONDS = 2

#: Holding a key accelerates a player at ACCELERATION pixels a second, each
#: second, and drag slows them in proportion to their speed, so their top
#: speed is ACCELERATION / DRAG pixels a second.
ACCELERATION = 1000
DRAG = 4
#: A player coasting slower than this, in pixels a second, stops.
STOP_SPEED = 5
#: Movement is worked out in steps of this many seconds, with a shorter last
#: step.
STEP = 1 / 120
DIAGONAL = math.sqrt(0.5)

#: The most movement time a player can save up, in seconds, which is also the
#: most one move can cover. Moves reach the game unevenly, so a player held up
#: for a moment can catch up, but no more.
SAVED_MOVEMENT = 0.5

#: When a page stops sending moves while its player is moving, as when it's
#: closed, no move carries the player on. Each move the game accepts leaves
#: the player's movement time at most SAVED_MOVEMENT behind the session clock.
#: So once a moving player's movement time is COAST_AFTER behind, the game has
#: accepted no move from them for COAST_AFTER - SAVED_MOVEMENT seconds, and it
#: lets them coast on its ticks.
COAST_AFTER = 2

#: The rules the page needs to work out a move just as ``advance`` does. The
#: game page passes them to static/shared-canvas.js, which repeats
#: ``advance``'s arithmetic step for step.
RULES = {
    "size": SIZE,
    "player_radius": PLAYER_RADIUS,
    "coin_radius": COIN_RADIUS,
    "reach": REACH,
    "acceleration": ACCELERATION,
    "drag": DRAG,
    "stop_speed": STOP_SPEED,
    "step": STEP,
    "diagonal": DIAGONAL,
    "longest_move": SAVED_MOVEMENT,
    "colors": COLORS,
}


def clamp(value, low, high):
    return min(high, max(low, value))


def passes_near(x1, y1, x2, y2, coin):
    """Whether the path from ``x1``, ``y1`` to ``x2``, ``y2`` comes within
    ``REACH`` of ``coin``."""
    sx, sy = x2 - x1, y2 - y1
    length = sx * sx + sy * sy
    # How far along the path the closest point to the coin is, from 0 to 1.
    along = (
        0 if length == 0 else ((coin["x"] - x1) * sx + (coin["y"] - y1) * sy) / length
    )
    along = clamp(along, 0, 1)
    px = x1 + along * sx - coin["x"]
    py = y1 + along * sy - coin["y"]
    return px * px + py * py <= REACH * REACH


def is_moving(player):
    return player["vx"] != 0 or player["vy"] != 0


def advance(state, player_id, dx, dy, seconds, now):
    """Move a player for ``seconds``, holding the keys for ``dx``, ``dy``, and
    collect the coins they pass, each counted at session time ``now``. Return
    the number of coins collected.

    The page's ``advance`` does the same arithmetic in the same order, so its
    prediction lands where the game does, unless the game shortens or rejects
    the move.
    """
    player = state["players"][player_id]
    scale = DIAGONAL if dx != 0 and dy != 0 else 1
    ax = ACCELERATION * dx * scale
    ay = ACCELERATION * dy * scale
    elapsed = 0
    collected = 0
    while elapsed < seconds:
        dt = min(STEP, seconds - elapsed)
        elapsed += dt
        x, y = player["x"], player["y"]
        player["vx"] += (ax - DRAG * player["vx"]) * dt
        player["vy"] += (ay - DRAG * player["vy"]) * dt
        player["x"] += player["vx"] * dt
        player["y"] += player["vy"] * dt
        # A player who reaches a wall stops moving into it.
        if not PLAYER_RADIUS <= player["x"] <= SIZE - PLAYER_RADIUS:
            player["x"] = clamp(player["x"], PLAYER_RADIUS, SIZE - PLAYER_RADIUS)
            player["vx"] = 0
        if not PLAYER_RADIUS <= player["y"] <= SIZE - PLAYER_RADIUS:
            player["y"] = clamp(player["y"], PLAYER_RADIUS, SIZE - PLAYER_RADIUS)
            player["vy"] = 0
        speed_squared = player["vx"] * player["vx"] + player["vy"] * player["vy"]
        if dx == 0 and dy == 0 and speed_squared < STOP_SPEED * STOP_SPEED:
            player["vx"] = player["vy"] = 0
        for coin in list(state["coins"]):
            if passes_near(x, y, player["x"], player["y"], coin):
                state["coins"].remove(coin)
                player["coins"] += 1
                collected += 1
                state["collected"].append(
                    {"coin": coin["id"], "by": player_id, "time": now}
                )
    return collected


def starting_points(n):
    """Where ``n`` players start: evenly around a circle in the middle."""
    return [
        (
            SIZE / 2 + 200 * math.cos(2 * math.pi * i / n),
            SIZE / 2 + 200 * math.sin(2 * math.pi * i / n),
        )
        for i in range(n)
    ]


def add_coin(state):
    """Put a coin somewhere at random, away from every player, since only a
    move collects it."""
    while True:
        x = round(random.uniform(40, SIZE - 40), 1)
        y = round(random.uniform(40, SIZE - 40), 1)
        players = state["players"].values()
        if all(math.dist((x, y), (p["x"], p["y"])) > 2 * REACH for p in players):
            break
    state["coins"].append({"id": state["next_coin_id"], "x": x, "y": y})
    state["next_coin_id"] += 1


class Move(LiveMessage):
    """Which arrow keys the player held, and for how many seconds. A move
    with no keys held, ``dx`` and ``dy`` both 0, lets the player coast."""

    type = "move"
    dx: Literal[-1, 0, 1]
    dy: Literal[-1, 0, 1]
    seconds: float = Field(gt=0, le=SAVED_MOVEMENT)
    # Whether the move collected a coin, which apply notes for should_save.
    _found_coin: bool = False

    def apply(self, game, state, player_id, now):
        player = state["players"][player_id]
        # Movement time is spent against the session clock, so however many
        # moves a page sends, its player moves no further than the rules
        # allow.
        start = max(player["moved_until"], now - SAVED_MOVEMENT)
        seconds = min(self.seconds, now - start)
        if seconds <= 0:
            raise Reject("You've used up your movement time.")
        player["moved_until"] = start + seconds
        coins = advance(state, player_id, self.dx, self.dy, seconds, now)
        self._found_coin = coins > 0

    def should_save(self, game, state, player_id, rejection):
        # Pages send many moves a second, so only the moves that collected a
        # coin go in the session's record.
        return self._found_coin


class SharedCanvas(LiveGame):
    """Players move around a canvas and collect coins.

    The state holds each player's position, velocity and coins, the coins
    still on the canvas, and every coin collected, with who collected it and
    when the game counted it. A player's page sends moves, each saying which
    keys were held and for how long, and the game works out where that takes
    the player. The game lasts ``ROUND_SECONDS`` from its start, and more
    coins appear while it runs.
    """

    channel = "shared_canvas_live"
    messages = [Move]
    # A color for each player.
    max_players = len(COLORS)
    # Each tick sends every player a view, which the page interpolates
    # between.
    tick_rate = 20
    # Pages send many moves a second and show their own at once, so the
    # sender gets its view with the next tick, like everyone else.
    send_views_on_messages = False
    duration = ROUND_SECONDS

    def initial_state(self, players):
        state = {
            "players": {
                player_id: {
                    "number": number,
                    "x": x,
                    "y": y,
                    "vx": 0,
                    "vy": 0,
                    "coins": 0,
                    # The session time up to which the player's movement
                    # time is spent.
                    "moved_until": 0,
                }
                for number, (player_id, (x, y)) in enumerate(
                    zip(players, starting_points(len(players))), start=1
                )
            },
            "coins": [],
            "next_coin_id": 0,
            "collected": [],
            "next_coin": None,
        }
        for _ in range(self.most_coins(state)):
            add_coin(state)
        return state

    def most_coins(self, state):
        return COINS_PER_PLAYER * len(state["players"])

    def coin_seconds(self, state):
        return COIN_SECONDS / len(state["players"])

    def on_start(self, state, now):
        # Nobody can move before the start, so there's no movement time to
        # save up from then.
        for player in state["players"].values():
            player["moved_until"] = now
        state["next_coin"] = now + self.coin_seconds(state)

    def tick(self, state, now):
        while now >= state["next_coin"]:
            if len(state["coins"]) < self.most_coins(state):
                add_coin(state)
            state["next_coin"] += self.coin_seconds(state)
        coast_until = now - COAST_AFTER
        for player_id, player in state["players"].items():
            if is_moving(player) and player["moved_until"] < coast_until:
                seconds = coast_until - player["moved_until"]
                player["moved_until"] = coast_until
                advance(state, player_id, 0, 0, seconds, now)

    def view(self, state, player_id):
        return {
            "me": player_id,
            "players": {
                other_id: {
                    "number": player["number"],
                    "x": player["x"],
                    "y": player["y"],
                    "vx": player["vx"],
                    "vy": player["vy"],
                    "coins": player["coins"],
                }
                for other_id, player in state["players"].items()
            },
            "coins": state["coins"],
        }

    def outcome(self, state, reason):
        return {
            "reason": reason,
            "coins": {
                player_id: player["coins"]
                for player_id, player in state["players"].items()
            },
            "collected": state["collected"],
        }

    def answer(self, outcome, reason, player_id):
        """The player's own part of the outcome, for their result page: their
        score, the coins they collected, whether it was the best, and the
        group's total, as in the snake demo."""
        coins = outcome["coins"]
        score = coins[player_id]
        return {
            "reason": reason,
            "score": score,
            "best": all(score > n for other, n in coins.items() if other != player_id),
            "group_total": sum(coins.values()),
        }

    def performance_reward(self, outcome, reason, player_id):
        return BONUS_PER_COIN * outcome["coins"][player_id]

    def bot(self, view, player_id, now):
        """Head for the nearest coin worth chasing (see
        ``coin_worth_chasing``). If there isn't one, wait in the middle of the
        part of the canvas nearer to the bot than to anyone else, so that bots
        spread out and each is ready for the coins in its part. The bot aims short of
        where it's heading by the distance it would coast, so it slows down as
        it gets there."""
        me = view["players"][player_id]
        others = [p for other_id, p in view["players"].items() if other_id != player_id]
        coin = coin_worth_chasing(me, others, view["coins"])
        target = coin if coin is not None else territory_center(me, others)
        dx, dy = steps_toward(me, target)
        if dx == dy == 0 and not is_moving(me):
            return None
        return Move(dx=dx, dy=dy, seconds=BOT_SPEED / self.tick_rate)


# How the game plays for bots, as in `psynet test`.

#: How hard the bots are to beat, above 0 and up to 1. Each bot move covers this share
#: of a tick, so a bot plays in slow motion: at 0.8 it reaches 80% of a
#: player's top speed, and speeds up and slows down more gently. At 1 it's
#: as fast as a person.
BOT_SPEED = 0.8

#: A bot goes for a coin that it's at most this many times as far from as the
#: nearest other player, so it contests coins that are nearer to someone else.
BOT_MARGIN = 3

#: A bot leaves a coin to the others when more than this many players are
#: nearer to it. Players pass through each other, so without this, bots in a
#: group of three or more would all chase the newest coin together and end up
#: moving as a pack. With two players, only BOT_MARGIN matters.
BOT_RIVALS = 1

#: The squares, this many pixels across, that a bot's part of the canvas is
#: measured in. Coarser is cheaper, and a bot only needs to know roughly where
#: its part is.
TERRITORY_CELL = 64
TERRITORY_CELLS = [
    (x + TERRITORY_CELL / 2, y + TERRITORY_CELL / 2)
    for x in range(0, SIZE, TERRITORY_CELL)
    for y in range(0, SIZE, TERRITORY_CELL)
]


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def coin_worth_chasing(me, others, coins):
    """The nearest coin that ``me`` is at most ``BOT_MARGIN`` times as far
    from as the nearest of ``others`` is, and that at most ``BOT_RIVALS`` of
    them are nearer to, or ``None`` if there's no such coin."""

    def worth_chasing(coin):
        mine = distance(me, coin)
        theirs = [distance(other, coin) for other in others]
        nearer = sum(their < mine for their in theirs)
        return mine <= BOT_MARGIN * min(theirs) and nearer <= BOT_RIVALS

    chances = [coin for coin in coins if worth_chasing(coin)]
    return min(chances, key=lambda coin: distance(me, coin), default=None)


def territory_center(me, others):
    """The middle of the part of the canvas nearer to ``me`` than to any of
    ``others``."""

    def squared_distance(player, x, y):
        return (player["x"] - x) ** 2 + (player["y"] - y) ** 2

    mine = [
        (x, y)
        for x, y in TERRITORY_CELLS
        if squared_distance(me, x, y)
        <= min(squared_distance(other, x, y) for other in others)
    ]
    if not mine:
        return me
    return {
        "x": sum(x for x, _ in mine) / len(mine),
        "y": sum(y for _, y in mine) / len(mine),
    }


def steps_toward(me, target):
    """The ``dx`` and ``dy`` that head from ``me`` toward ``target``, aiming
    short by the distance ``me`` would coast at its velocity. An axis within
    half of ``REACH`` of that point is 0."""

    def step(gap):
        if abs(gap) < REACH / 2:
            return 0
        return 1 if gap > 0 else -1

    return (
        step(target["x"] - me["vx"] / DRAG - me["x"]),
        step(target["y"] - me["vy"] / DRAG - me["y"]),
    )


def coins_text(n):
    return f"{n} coin" if n == 1 else f"{n} coins"


def show_result(participant):
    answer = participant.var.shared_canvas_live
    if answer is None:
        return InfoPage("Your group couldn't play the game.", time_estimate=5)
    coins = answer["score"]
    if answer["reason"] != "finished":
        summary = "The game ended early."
    elif answer["best"]:
        summary = "You collected the most coins!"
    else:
        summary = "Time's up!"
    return InfoPage(
        tags.div(
            tags.h2(summary),
            tags.p(
                f"You collected {coins_text(coins)}, earning a bonus of "
                f"${BONUS_PER_COIN * coins:.2f}. Your group collected "
                f"{coins_text(answer['group_total'])} in all."
            ),
        ),
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Shared canvas live session demo"
    test_n_bots = GROUP_SIZE
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage(
            tags.div(
                tags.p(
                    "You'll move around a canvas with other participants, "
                    f"collecting coins, for {ROUND_SECONDS} seconds. Use the "
                    "arrow keys or W, A, S and D to move. You speed up while "
                    "you hold a key, and slow down once you let go."
                ),
                tags.p(
                    f"Each coin you collect earns a bonus of ${BONUS_PER_COIN:.2f}. "
                    "First, we'll find the other players."
                ),
            ),
            time_estimate=10,
        ),
        SimpleGrouper(
            group_type="canvas",
            initial_group_size=GROUP_SIZE,
            waiting_message="Waiting for other participants to join you",
            # A participant who waits longer than this leaves the experiment.
            max_wait_time=300,
        ),
        PlayLiveGame(
            group_type="canvas",
            game_class=SharedCanvas,
            id_="shared_canvas_live",
            page=ModularPage(
                "shared_canvas_live",
                Prompt(
                    tags.div(
                        tags.h4(id="canvas-status"),
                        tags.p(
                            "Time left: ",
                            tags.span(ROUND_SECONDS, id="canvas-timer"),
                            id="canvas-time",
                        ),
                        tags.canvas(
                            id="canvas",
                            width=SIZE,
                            height=SIZE,
                            tabindex="0",
                            aria_label="The canvas you move around",
                        ),
                        tags.ul(id="canvas-scores"),
                        id="canvas-game",
                    )
                ),
                LiveGameControl(),
                js_page_modules=["/static/shared-canvas.js"],
                css_links=["/static/shared-canvas.css"],
                js_vars={"canvas_rules": RULES},
                time_estimate=60,
                save_answer="shared_canvas_live",
            ),
        ),
        PageMaker(show_result, time_estimate=5),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        result = live_game_result(live_game_id(bot, "shared_canvas_live"))
        assert result.status == "ended", result.error
        assert result.end_reason == "finished"
        me = str(bot.id)
        assert bot.var.shared_canvas_live["score"] == result.outcome["coins"][me]
        collected = result.outcome["collected"]
        coins = result.outcome["coins"][me]
        assert coins == sum(entry["by"] == me for entry in collected)
        assert sum(result.outcome["coins"].values()) == len(collected)
        assert bot.performance_reward == pytest.approx(BONUS_PER_COIN * coins)

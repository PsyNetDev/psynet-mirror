"""Snake for a group, played as a live game.

Each player steers a snake around a shared board with the arrow keys for
``ROUND_SECONDS``. The game moves every snake one square on each tick, and a
snake that eats food grows longer. A snake that hits a wall or any snake, its
own body included, crashes and comes back a moment later somewhere else. Each
piece of food eaten pays a bonus.
"""

import random
from collections import Counter
from typing import Literal

import pytest
from dominate import tags

import psynet.experiment
from psynet.live_game import (
    FINISHED,
    LiveGame,
    LiveGamePage,
    LiveMessage,
    PlayLiveGame,
    Reject,
)
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import PageMaker, Timeline

#: Each player's color, by player number. There's one for each player a
#: game can have.
COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]

#: Players in each game, from 2 to ``len(COLORS)``, the game's
#: ``max_players``.
GROUP_SIZE = 2

#: The board is this many squares across and down.
SIZE = 30
#: Each square is drawn this many pixels across.
SQUARE = 20
ROUND_SECONDS = 60
#: Every snake starts, and comes back after a crash, this many squares long.
START_LENGTH = 3
#: A crashed snake comes back after this many seconds.
RESPAWN_SECONDS = 2
#: The board holds this many pieces of food for each player.
FOOD_PER_PLAYER = 1
#: How many turns a player can press before the snake has made them, so that
#: two quick presses make a U-turn.
MAX_TURNS_AHEAD = 2
BONUS_PER_FOOD = 0.02

DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}

#: What the game page needs to draw the board. The game page passes it to
#: static/snake.js.
RULES = {"size": SIZE, "square": SQUARE, "colors": COLORS}


def step(square, direction):
    """The square next to ``square`` in ``direction``."""
    dx, dy = DIRECTIONS[direction]
    return [square[0] + dx, square[1] + dy]


def distance(a, b):
    """The number of squares between ``a`` and ``b``, moving as a snake does."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def on_board(square):
    return 0 <= square[0] < SIZE and 0 <= square[1] < SIZE


def taken_squares(state):
    """Every square a snake or a piece of food is on."""
    taken = {tuple(square) for square in state["food"]}
    for snake in state["snakes"]:
        taken.update(tuple(square) for square in snake["body"])
    return taken


def add_food(state):
    """Put a piece of food on a random empty square."""
    taken = taken_squares(state)
    empty = [[x, y] for x in range(SIZE) for y in range(SIZE) if (x, y) not in taken]
    state["food"].append(random.choice(empty))


def place_snake(snake, state, kept_clear):
    """Put a crashed snake back on a random empty part of the board, with three
    empty squares ahead of it. It doesn't go next to any other snake's head,
    which could turn into it on the next tick, or on the squares
    ``kept_clear`` for snakes put back earlier in the same tick, and its own
    squares ahead are added to ``kept_clear``. If there's no room, it tries
    again next tick."""
    taken = taken_squares(state) | kept_clear
    for other in state["snakes"]:
        if other["body"]:
            for direction in DIRECTIONS:
                taken.add(tuple(step(other["body"][0], direction)))
    for _ in range(100):
        direction = random.choice(list(DIRECTIONS))
        squares = [[random.randrange(SIZE), random.randrange(SIZE)]]
        for _ in range(START_LENGTH - 1 + 3):
            squares.append(step(squares[-1], direction))
        if all(on_board(square) and tuple(square) not in taken for square in squares):
            # The body is listed head first.
            snake["body"] = squares[START_LENGTH - 1 :: -1]
            snake["direction"] = direction
            snake["back_at"] = None
            kept_clear.update(tuple(square) for square in squares[START_LENGTH:])
            return


def move_snakes(state, now):
    """Move every snake one square, then crash each one whose head hit
    something. All the snakes move before any crashes are worked out, so no
    player gains from having their snake moved first."""
    moving = [snake for snake in state["snakes"] if snake["body"]]
    food = {tuple(square) for square in state["food"]}
    for snake in moving:
        if snake["turns"]:
            snake["direction"] = snake["turns"].pop(0)
        head = step(snake["body"][0], snake["direction"])
        snake["body"].insert(0, head)
        # A snake that eats keeps its tail, so it grows a square.
        if tuple(head) not in food:
            snake["body"].pop()

    # A head that shares its square with any other part of a snake has hit it:
    # its own body, another snake's body, or another head that moved there too.
    squares = Counter(tuple(square) for snake in moving for square in snake["body"])
    for snake in moving:
        head = snake["body"][0]
        if not on_board(head) or squares[tuple(head)] > 1:
            snake["body"] = []
            snake["turns"] = []
            snake["crashes"] += 1
            snake["back_at"] = now + RESPAWN_SECONDS
        elif tuple(head) in food:
            state["food"].remove(head)
            snake["food"] += 1


class Turn(LiveMessage):
    """Which way the player wants their snake to go next. Each tick, the snake
    makes the oldest turn the player has pressed, and then moves a square."""

    type = "turn"
    direction: Literal["up", "down", "left", "right"]

    def apply(self, game, state, player, now):
        snake = state["snakes"][player]
        if not snake["body"]:
            raise Reject("Your snake will be back in a moment.")
        turns = snake["turns"]
        heading = turns[-1] if turns else snake["direction"]
        if self.direction == heading:
            return
        if self.direction == OPPOSITE[heading]:
            raise Reject("A snake can't turn back on itself.")
        if len(turns) == MAX_TURNS_AHEAD:
            raise Reject("You've pressed too many keys at once.")
        turns.append(self.direction)


class Snake(LiveGame):
    """A group of players steer snakes around one board.

    The state holds each player's snake, in player order: its body, listed
    head first and empty while the snake is crashed, the direction it's
    heading, the turns the player has pressed that it hasn't made yet, and
    the snake's food and crashes.
    It also holds the food on the board. Pages send turns, and on each tick
    the game moves every snake a square. The game lasts ``ROUND_SECONDS``
    from its start.
    """

    name = "snake"
    messages = [Turn]
    # A color for each player.
    max_players = len(COLORS)
    # The snakes move a square on each tick.
    tick_rate = 8
    # A turn changes nothing a page shows until the snake makes it, on the
    # next tick, so the sender gets its view with that tick, like everyone
    # else.
    send_views_on_messages = False
    duration = ROUND_SECONDS

    def initial_state(self, players):
        state = {"snakes": [], "food": []}
        for player in players:
            # The snakes start in evenly spaced rows, heading right.
            row = (player + 1) * SIZE // (len(players) + 1)
            state["snakes"].append(
                {
                    "body": [[START_LENGTH - i, row] for i in range(START_LENGTH)],
                    "direction": "right",
                    "turns": [],
                    "food": 0,
                    "crashes": 0,
                    # When a crashed snake comes back, in seconds into the game.
                    "back_at": None,
                }
            )
        for _ in range(FOOD_PER_PLAYER * len(players)):
            add_food(state)
        return state

    def tick(self, state, now):
        move_snakes(state, now)
        # Crashed snakes come back after the others have moved, so every page
        # shows them before they can move or be hit.
        kept_clear = set()
        for snake in state["snakes"]:
            if snake["back_at"] is not None and now >= snake["back_at"]:
                place_snake(snake, state, kept_clear)
        while len(state["food"]) < FOOD_PER_PLAYER * len(state["snakes"]):
            add_food(state)

    def view(self, state, player):
        # Every snake but the turns its player has pressed.
        return {
            "snakes": [
                {key: value for key, value in snake.items() if key != "turns"}
                for snake in state["snakes"]
            ],
            "food": state["food"],
        }

    def outcome(self, state, reason):
        return {
            "food": [snake["food"] for snake in state["snakes"]],
            "crashes": [snake["crashes"] for snake in state["snakes"]],
        }

    def answer(self, outcome, reason, player):
        """The player's own part of the outcome, for their result page: the
        food their snake ate, whether it was the most, and their crashes."""
        food = outcome["food"]
        others = food[:player] + food[player + 1 :]
        return {
            "finished": reason == FINISHED,
            "score": food[player],
            "best": all(food[player] > n for n in others),
            "crashes": outcome["crashes"][player],
        }

    def performance_reward(self, outcome, reason, player):
        return BONUS_PER_FOOD * outcome["food"][player]

    def bot(self, view, player, now):
        """Head for the nearest food, turning only onto a square that's on
        the board and that no snake is on. A bot that has nowhere safe to go
        carries on and crashes."""
        me = view["snakes"][player]
        if not me["body"]:
            return None
        head = me["body"][0]
        taken = {tuple(square) for snake in view["snakes"] for square in snake["body"]}
        # The square behind the head is the snake's own neck, so this also
        # leaves out turning back.
        safe = [
            direction
            for direction in DIRECTIONS
            if on_board(step(head, direction))
            and tuple(step(head, direction)) not in taken
        ]
        if not safe:
            return None
        food = min(view["food"], key=lambda square: distance(head, square))
        # The nearest safe direction to the food, carrying straight on if
        # that's as near as turning.
        best = min(
            safe,
            key=lambda direction: (
                distance(step(head, direction), food),
                direction != me["direction"],
            ),
        )
        if best == me["direction"]:
            return None
        return Turn(direction=best)


def food_text(n):
    return f"{n} piece of food" if n == 1 else f"{n} pieces of food"


def show_result(participant):
    answer = participant.live_games["snake"].answer
    food = answer["score"]
    crashes = answer["crashes"]
    if not answer["finished"]:
        summary = "The game ended early."
    elif answer["best"]:
        summary = "Your snake ate the most!"
    else:
        summary = "Time's up!"
    if crashes == 0:
        crashed = "didn't crash"
    elif crashes == 1:
        crashed = "crashed once"
    else:
        crashed = f"crashed {crashes} times"
    return InfoPage(
        tags.div(
            tags.h2(summary),
            tags.p(
                f"Your snake ate {food_text(food)} and {crashed}. You earned a "
                f"bonus of ${BONUS_PER_FOOD * food:.2f}."
            ),
        ),
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Snake live game demo"
    test_n_bots = GROUP_SIZE
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage(
            tags.div(
                tags.p(
                    "You'll steer a snake around a board with other participants "
                    f"for {ROUND_SECONDS} seconds. Use the arrow keys or W, A, S "
                    "and D to turn. Your snake grows each time it eats, and if it "
                    "hits a wall or a snake, it comes back a moment later."
                ),
                tags.p(
                    f"Each piece of food your snake eats earns a bonus of "
                    f"${BONUS_PER_FOOD:.2f}. First, we'll find the other players."
                ),
            ),
            time_estimate=10,
        ),
        SimpleGrouper(
            group_type="snake",
            initial_group_size=GROUP_SIZE,
            waiting_message="Waiting for other participants to join you",
            # A participant who waits longer than this leaves the experiment.
            max_wait_time=300,
            # The game needs two players. A group of more plays on without
            # a member who is late for it; a player left alone is failed.
            quorum=2,
            below_quorum="fail",
        ),
        PlayLiveGame(
            group_type="snake",
            # The game page comes straight after the group forms, so this
            # only has to allow for a page that is slow to load. A member
            # later than this is failed.
            late_after=60,
            late_action="fail",
            game_class=Snake,
            page=LiveGamePage(
                "snake_live",
                tags.div(
                    tags.h4(id="snake-status"),
                    tags.p(
                        "Time left: ",
                        tags.span(ROUND_SECONDS, id="snake-timer"),
                        id="snake-time",
                    ),
                    tags.canvas(
                        id="snake-board",
                        width=SIZE * SQUARE,
                        height=SIZE * SQUARE,
                        tabindex="0",
                        aria_label="The board your snake moves around",
                    ),
                    tags.ul(id="snake-scores"),
                    id="snake-game",
                ),
                js_page_modules=["/static/snake.js"],
                css_links=["/static/snake.css"],
                js_vars={"snake_rules": RULES},
                time_estimate=60,
            ),
        ),
        PageMaker(show_result, time_estimate=5),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        game = bot.live_games["snake"]
        assert game.end_reason == FINISHED, game.error
        food = game.outcome["food"][game.participant_ids.index(bot.id)]
        assert game.answer["score"] == food
        assert bot.performance_reward == pytest.approx(BONUS_PER_FOOD * food)

"""A live microsociety: a fishing society on a lake that keeps going while its members come and go.

Every member has a boat on a lake with ``N_SPOTS`` fishing spots, and can
move it to another spot at any time; moving takes ``TRAVEL_SECONDS``. Every
``CATCH_SECONDS``, each boat at a spot catches a noisy number of fish around
the spot's hidden average, and everyone sees who caught what, where. So
members can learn where to fish from each other while they play. Each fish
pays ``FISH_VALUE``.

The lake is one live game that runs for as long as the society has members.
A newcomer joins the society, sees where its members have been catching fish
lately and the tips of members who have left, and then sails onto the lake
while the others fish: the ``PlayLiveGame`` has ``join_running_game=True``,
and the game's ``on_add`` gives them a boat. Each member fishes for
``STAY_SECONDS``, and when a newcomer makes the lake more crowded than
``SOCIETY_SIZE``, the longest-serving member retires. The game's ``is_done``
ends each member's game then, so they move on and leave a tip while the
others carry on. The lake closes once nobody is left on it.

The game records each catch with ``record``, so the newcomer's page and the
export read the society's history from ``Fishing.moments``.
"""

import random
from typing import List

from dominate import tags

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages, run_bots_to_completion
from psynet.live_game import (
    LiveGame,
    LiveGameControl,
    LiveMessage,
    PlayLiveGame,
    Reject,
)
from psynet.modular_page import ModularPage, Prompt, TextControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import SimpleGrouper, leave_group
from psynet.timeline import (
    CodeBlock,
    PageMaker,
    Timeline,
    conditional,
    join,
    switch,
)

# The most members fishing at once. A newcomer beyond it makes the
# longest-serving member retire.
SOCIETY_SIZE = 3
STAY_SECONDS = 40
# Average catches of the spots, which members don't see.
SPOT_MEANS = [1, 2, 4, 2, 1, 5, 3, 2]
N_SPOTS = len(SPOT_MEANS)
CATCH_NOISE = 1.5
FISH_VALUE = 0.01
CATCH_SECONDS = 3
TRAVEL_SECONDS = 2
# How long the lake page shows a member's results before moving on.
RESULTS_SECONDS = 8
GROUPING_WAIT = 120
# The catches a newcomer sees before joining.
HISTORY_CATCHES = 10
TIPS_SHOWN = 3
# Members are named by the colour of their boat, and spots by letter.
COLOURS = ["purple", "green", "pink", "grey", "orange"]
SPOT_LETTERS = "ABCDEFGH"

# Why a member's game ended, which is their game's reason.
RETIRED = "retired"
STAYED = "stayed"


class Move(LiveMessage):
    """Move the player's boat to ``spot``."""

    type = "move"
    spot: int

    def apply(self, game, state, player, now):
        if not 1 <= self.spot <= N_SPOTS:
            raise Reject("There's no such spot.")
        boat = state["boats"][player]
        if boat["spot"] == self.spot:
            raise Reject("Your boat is already there.")
        boat["spot"] = self.spot
        boat["arrives_at"] = now + TRAVEL_SECONDS
        state["moves"][player] += 1


class Fishing(LiveGame):
    channel = "fishing"
    messages = [Move]
    min_players = 1
    # Members keep coming while the lake is open, so it closes after this
    # long even if they do.
    timeout = 20 * 60

    def initial_state(self, players):
        # Each player's boat, fish and moves, in player order.
        state = {
            "boats": [],
            "fish": [],
            "moves": [],
            # The latest catch, numbered so a page can tell a new one.
            "latest": {"number": 0, "caught": []},
            "next_catch_at": CATCH_SECONDS,
        }
        for player in players:
            _launch_boat(state, joined_at=0)
        return state

    def on_add(self, state, player, now):
        # A player added before the lake opens starts fishing when it does.
        _launch_boat(state, joined_at=0 if now is None else now)
        fishing = _fishing(state)
        if len(fishing) > SOCIETY_SIZE:
            longest = min(fishing, key=lambda p: (state["boats"][p]["joined_at"], p))
            self._leave(state, longest, RETIRED)

    def next_deadline(self, state):
        return state["next_catch_at"]

    def tick(self, state, now):
        while state["next_catch_at"] <= now:
            at = state["next_catch_at"]
            caught = []
            for player in _fishing(state):
                boat = state["boats"][player]
                if boat["spot"] is None or boat["arrives_at"] > at:
                    continue
                mean = SPOT_MEANS[boat["spot"] - 1]
                fish = max(0, round(random.gauss(mean, CATCH_NOISE)))
                state["fish"][player] += fish
                caught.append({"player": player, "spot": boat["spot"], "fish": fish})
            state["latest"] = {
                "number": state["latest"]["number"] + 1,
                "caught": caught,
            }
            self.record("catch", {"at": at, "caught": caught})
            for player in _fishing(state):
                if state["boats"][player]["joined_at"] + STAY_SECONDS <= at:
                    self._leave(state, player, STAYED)
            state["next_catch_at"] = at + CATCH_SECONDS

    def _leave(self, state, player, why):
        state["boats"][player]["left"] = why
        self.record("left", {"player": player, "why": why})

    def is_done(self, state, player):
        return state["boats"][player]["left"] or False

    def is_over(self, state):
        return not _fishing(state)

    def view(self, state, player):
        boats = state["boats"]
        mine = boats[player]
        shown = [p for p in range(len(boats)) if p == player or not boats[p]["left"]]
        who = {p: "you" if p == player else boats[p]["colour"] for p in shown}
        return {
            "travel_seconds": TRAVEL_SECONDS,
            "boats": [
                {
                    "who": who[p],
                    "spot": boats[p]["spot"],
                    "arrives_at": boats[p]["arrives_at"],
                }
                for p in shown
            ],
            "fish": {who[p]: state["fish"][p] for p in shown},
            "stay_seconds": STAY_SECONDS,
            "leaves_at": mine["joined_at"] + STAY_SECONDS,
            "left": mine["left"],
            "catch_number": state["latest"]["number"],
            "latest": [
                {"who": who[c["player"]], "spot": c["spot"], "fish": c["fish"]}
                for c in state["latest"]["caught"]
                if c["player"] in who
            ],
        }

    def outcome(self, state, reason):
        return {
            "fish": state["fish"],
            "moves": state["moves"],
            "left": [boat["left"] for boat in state["boats"]],
        }

    def answer(self, outcome, reason, player):
        return {
            "fish": outcome["fish"][player],
            "moves": outcome["moves"][player],
            # A member still fishing when the lake closed left with it.
            "left": outcome["left"][player] or reason,
        }

    def performance_reward(self, outcome, reason, player):
        return outcome["fish"][player] * FISH_VALUE

    def bot(self, view, player, now):
        mine = next(boat for boat in view["boats"] if boat["who"] == "you")
        if mine["spot"] is None:
            return Move(spot=1 + player % N_SPOTS)
        if mine["arrives_at"] > now:
            return None
        caught = {c["who"]: c for c in view["latest"]}
        best = max(view["latest"], key=lambda c: c["fish"], default=None)
        own = caught.get("you")
        if (
            best is not None
            and own is not None
            and best["spot"] != mine["spot"]
            and best["fish"] >= own["fish"] + 3
        ):
            return Move(spot=best["spot"])
        return None


def _launch_boat(state, joined_at):
    """Give a new player a boat at the dock, in a colour no other boat on the lake has."""
    taken = {state["boats"][p]["colour"] for p in _fishing(state)}
    colour = next(c for c in COLOURS if c not in taken)
    state["boats"].append(
        {
            "spot": None,
            "arrives_at": None,
            "colour": colour,
            "joined_at": joined_at,
            "left": None,
        }
    )
    state["fish"].append(0)
    state["moves"].append(0)


def _fishing(state):
    """Return the players still on the lake."""
    return [p for p, boat in enumerate(state["boats"]) if not boat["left"]]


def _spot(spot):
    # Each spot's fish and ripples get their own timing, the same on every page, so they don't move in step.
    timing = random.Random(spot)

    def fish():
        duration = timing.uniform(6, 12)
        return tags.span(
            cls="fish-shadow",
            style=(
                f"--swim-duration: {duration:.1f}s; "
                f"--swim-delay: -{timing.uniform(0, duration):.1f}s; "
                f"--swim-radius: {timing.uniform(1.4, 2.6):.1f}rem; "
                f"animation-direction: {timing.choice(['normal', 'reverse'])}"
            ),
        )

    def ripple():
        return tags.span(
            cls="fish-ripple",
            style=f"animation-delay: -{timing.uniform(0, 3.6):.1f}s",
        )

    return tags.button(
        ripple(),
        ripple(),
        fish(),
        fish(),
        tags.span(SPOT_LETTERS[spot - 1], cls="fish-spot-number"),
        tags.div(cls="fish-catches"),
        type="button",
        cls="fish-spot",
        disabled=True,
        aria_label=f"Spot {SPOT_LETTERS[spot - 1]}",
    )


def water():
    """Return the lake's water, with its spots, dock and room for boats."""
    return tags.div(
        tags.div(*[_spot(spot) for spot in range(1, N_SPOTS + 1)], cls="fish-spots"),
        tags.div(cls="fish-dock"),
        tags.div(id="fish-boats", cls="fish-boats"),
        tags.div(id="fish-results", cls="fish-results", hidden=True),
        id="fish-lake",
        cls="fish-lake",
    )


def lake_page():
    return ModularPage(
        "fish",
        Prompt(
            tags.div(
                tags.div(
                    tags.span("The lake", cls="fish-round"),
                    tags.span("Sailing to the lake…", id="fish-status"),
                    tags.div(tags.div(id="fish-time-left"), cls="fish-clock"),
                    tags.span(id="fish-seconds", cls="fish-seconds"),
                    cls="fish-header",
                ),
                water(),
                tags.p(
                    "Boats start at the dock. Click a spot to sail your boat "
                    f"there, which takes {TRAVEL_SECONDS} s. Boats at a spot "
                    f"catch fish every {CATCH_SECONDS} s.",
                    cls="fish-help",
                ),
                tags.div(id="fish-scores", cls="fish-scores"),
                tags.p(id="fish-rejection", cls="fish-rejection"),
                id="fish-game",
            )
        ),
        # The page shows the member's results on the lake before moving on.
        LiveGameControl(show_result_for=RESULTS_SECONDS, player_left_message=None),
        js_page_modules=["/static/fishing.js"],
        css_links=["/static/fishing.css"],
        time_estimate=STAY_SECONDS + RESULTS_SECONDS,
    )


def get_timeline():
    return Timeline(
        InfoPage(
            "You will join a small fishing society on a lake. You fish for "
            f"up to {STAY_SECONDS} seconds. You can move your boat between "
            "spots at any time, and you see where the others fish and what "
            "they catch. Some spots are better than others. Members come and "
            f"go, and each fish you catch pays ${FISH_VALUE:.2f}.",
            time_estimate=15,
        ),
        SimpleGrouper(
            group_type="society",
            initial_group_size=2,
            # Room for a newcomer while a retiring member finishes up.
            max_group_size=SOCIETY_SIZE + 1,
            quorum=1,
            join_existing_groups=True,
            use_admission_points=False,
            max_groups=1,
            below_quorum="continue_without_group",
            max_wait_time=GROUPING_WAIT,
            max_wait_action="continue_without_group",
            waiting_message="Waiting for a society to join…",
        ),
        conditional(
            "in_society",
            in_society,
            join(
                conditional(
                    "newcomer", lake_is_open, PageMaker(history_page, time_estimate=20)
                ),
                PlayLiveGame(
                    group_type="society",
                    game_class=Fishing,
                    page=lake_page(),
                    join_running_game=True,
                    waiting_message="Waiting for the others to reach the lake…",
                ),
                leave_group("society"),
                switch(
                    "leaving",
                    why_left,
                    {
                        RETIRED: leave_a_tip(
                            "A newcomer has taken your place, so you retire from the society."
                        ),
                        STAYED: leave_a_tip("Your time on the lake is up."),
                        "closed": InfoPage("The lake has closed.", time_estimate=5),
                    },
                ),
            ),
            InfoPage("We couldn't find a society for you to join.", time_estimate=5),
        ),
        PageMaker(final_page, time_estimate=5),
    )


def why_left(participant: Participant) -> str:
    """Return why the member left the lake, or ``"closed"`` if it closed while they fished."""
    left = (participant.live_game_answers.get("fishing") or {}).get("left")
    return left if left in (RETIRED, STAYED) else "closed"


def in_society(participant: Participant) -> bool:
    return participant.in_sync_group("society")


def lake_is_open(participant: Participant) -> bool:
    """Return whether the participant's society is fishing on its lake now."""
    society = participant.active_sync_groups["society"]
    return "fishing" in society.running_live_game_ids


def history_page(participant: Participant):
    """Show a newcomer where the society has been catching fish lately and the tips of members who have left."""
    society = participant.active_sync_groups["society"]
    # The lake can close between the check and this page.
    lake_id = society.running_live_game_ids.get("fishing")
    catches = [] if lake_id is None else Fishing.moments(lake_id, "catch")
    spot_fish = [0] * N_SPOTS
    for moment in catches[-HISTORY_CATCHES:]:
        for c in moment.data["caught"]:
            spot_fish[c["spot"] - 1] += c["fish"]
    tips = [
        link.participant.var.tip
        for link in society.participant_links
        if link.participant.var.has("tip")
    ]
    content = tags.div()
    with content:
        tags.p("Welcome to the society. The others are already fishing.")
        if any(spot_fish):
            tags.p("Where the members have been catching fish lately:")
            with tags.ul():
                for letter, fish in sorted(
                    zip(SPOT_LETTERS, spot_fish), key=lambda spot: -spot[1]
                ):
                    if fish:
                        tags.li(f"Spot {letter}: {fish} fish")
        else:
            tags.p(
                "Nobody has caught anything yet, so you'll be among the first "
                "to find the good spots."
            )
        if tips:
            tags.p("Tips from members who have left:")
            with tags.ul():
                for tip in tips[-TIPS_SHOWN:]:
                    tags.li(tip)
    return InfoPage(content, time_estimate=20)


def leave_a_tip(intro: str):
    """Ask a member who is leaving for a tip, and save it."""
    return join(
        ModularPage(
            "tip",
            Prompt(
                tags.div(
                    water(),
                    tags.p(
                        f"{intro} Leave one tip for the members who come after you.",
                        cls="fish-tip-intro",
                    ),
                )
            ),
            TextControl(one_line=True),
            css_links=["/static/fishing.css"],
            time_estimate=30,
        ),
        CodeBlock(save_tip),
    )


def save_tip(participant: Participant):
    if participant.answer.strip():
        participant.var.tip = participant.answer


def final_page(participant: Participant):
    return InfoPage(
        f"Thank you for fishing. Your bonus is ${participant.performance_reward:.2f}.",
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Live microsociety demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per member and one per catch."""
        members = Participant.query.order_by(Participant.id).all()
        lake_ids = sorted({p.live_game_ids.get("fishing") for p in members} - {None})
        return {
            "member": [
                {
                    "participant_id": p.id,
                    "lake_id": p.live_game_ids.get("fishing"),
                    "fish": (p.live_game_answers.get("fishing") or {}).get("fish"),
                    "left": (p.live_game_answers.get("fishing") or {}).get("left"),
                    "tip": p.var.get("tip"),
                }
                for p in members
            ],
            "catch": [
                {
                    "lake_id": lake_id,
                    "time": moment.time,
                    "player": c["player"],
                    "spot": c["spot"],
                    "fish": c["fish"],
                }
                for lake_id in lake_ids
                for moment in Fishing.moments(lake_id, "catch")
                for c in moment.data["caught"]
            ],
        }

    test_n_bots = 4
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        founders, newcomers = bots[:2], bots[2:]
        for bot in founders:
            bot.take_page()
        advance_past_wait_pages(founders)
        assert all(bot.current_page_label == "fish" for bot in founders)

        # Newcomers join the society while the founders fish, read its
        # history, and sail onto the lake without waiting. The second makes
        # the lake too crowded, so the longest-serving founder retires.
        for bot in newcomers:
            bot.take_page()
            assert "The others are already fishing" in bot.current_page_text
            bot.take_page()
            assert bot.current_page_label == "fish"
        run_bots_to_completion(bots, timeout=STAY_SECONDS + 60)

        members = {
            row["participant_id"]: row for row in self.get_basic_data()["member"]
        }
        lefts = [members[bot.id]["left"] for bot in bots]
        assert lefts.count(RETIRED) == 1, lefts
        assert set(lefts) <= {RETIRED, STAYED, "finished"}, lefts
        assert len({members[bot.id]["lake_id"] for bot in bots}) == 1
        for bot in bots:
            reward = bot.with_participant(lambda p: p.performance_reward)
            expected = members[bot.id]["fish"] * FISH_VALUE
            assert abs(reward - expected) < 1e-9, (bot.id, reward, expected)

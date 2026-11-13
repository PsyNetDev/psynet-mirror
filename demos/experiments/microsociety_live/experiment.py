"""A live microsociety: a fishing society that keeps going while its members are replaced.

Each round lasts ``ROUND_SECONDS``. Every member has a boat on a lake with
``N_SPOTS`` fishing spots, and can move it to another spot at any time;
moving takes ``TRAVEL_SECONDS``. Every ``CATCH_SECONDS``, each boat at a spot
catches a noisy number of fish around the spot's hidden average, and
everyone sees who caught what, where. So members can learn where to fish
from each other while they play. Each fish pays ``FISH_VALUE``.

As in the ``microsociety`` demo, the society takes newcomers for as long as
it lasts. A newcomer is admitted at the start of the next round, where they
see the society's recent catches and the tips of members who have left.
When a round had more than ``SOCIETY_SIZE`` members, the longest-serving
member retires at its end, and a member also stops after ``MAX_ROUNDS``
rounds. Before leaving, they leave a tip for future members.

Each round is one cued ``FishingTrial`` per member, whose ``show_trial``
starts a live session for the society, shows the lake, and waits at the
``round_finished`` barrier, whose release records the round and retires a
member if the round had too many.
"""

import random
from typing import List, Optional

from dallinger.realtime import Reject
from dominate import tags

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages, run_bots_to_completion
from psynet.live_session import (
    LiveMessage,
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
)
from psynet.modular_page import ModularPage, Prompt, TextControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, SimpleGrouper, SyncGroupRound, group_seats
from psynet.timeline import (
    CodeBlock,
    Module,
    PageMaker,
    Timeline,
    conditional,
    join,
    switch,
    while_loop,
)
from psynet.trial.main import Trial

GROUP = "society"
SOCIETY_SIZE = 3
MAX_ROUNDS = 4
# Average catches of the spots, which members don't see.
SPOT_MEANS = [1, 2, 4, 2, 1, 5, 3, 2]
N_SPOTS = len(SPOT_MEANS)
CATCH_NOISE = 1.5
FISH_VALUE = 0.01
ROUND_SECONDS = 20
CATCH_SECONDS = 3
TRAVEL_SECONDS = 2
RESULTS_SECONDS = 10
# Covers a newcomer reading the society's history before their first round.
# The game page says when it ends, so this needn't cover the game.
LATE_AFTER = 60
GROUPING_WAIT = 120
TOP_UP_WAIT = 30
NEWCOMER_MAX_WAIT = LATE_AFTER + ROUND_SECONDS + RESULTS_SECONDS
HISTORY_ROUNDS = 3
TIPS_SHOWN = 3
LABELS = "BCDEFG"


class Move(LiveMessage):
    """Move the player's boat to ``spot``."""

    type = "move"
    spot: int

    def apply(self, game, state, player_id, now):
        if not 1 <= self.spot <= len(state["spot_means"]):
            raise Reject("There's no such spot.")
        boat = state["boats"][player_id]
        if boat["spot"] == self.spot:
            raise Reject("Your boat is already there.")
        boat["spot"] = self.spot
        boat["arrives_at"] = now + state["travel_seconds"]
        state["moves"][player_id] += 1


class Fishing(LiveSession):
    channel = "fishing"
    messages = [Move]
    max_duration = ROUND_SECONDS + 120

    def initial_state(self, players, settings):
        return {
            **settings,
            "boats": {p: {"spot": None, "arrives_at": None} for p in players},
            "fish": {p: 0 for p in players},
            "moves": {p: 0 for p in players},
            # Each catch: the session time and what each boat caught where.
            "catches": [],
            "ends_at": None,
            "next_catch_at": None,
            "time_up": False,
        }

    def on_start(self, state, now):
        state["ends_at"] = now + state["seconds"]
        state["next_catch_at"] = now + state["catch_seconds"]

    def next_deadline(self, state):
        if state["ends_at"] is None:
            return None
        return min(state["ends_at"], state["next_catch_at"])

    def tick(self, state, now):
        if state["next_catch_at"] is None:
            return
        while state["next_catch_at"] <= min(now, state["ends_at"]):
            at = state["next_catch_at"]
            caught = []
            for player, boat in state["boats"].items():
                if boat["spot"] is None or boat["arrives_at"] > at:
                    continue
                mean = state["spot_means"][boat["spot"] - 1]
                fish = max(0, round(random.gauss(mean, state["noise"])))
                state["fish"][player] += fish
                caught.append({"player": player, "spot": boat["spot"], "fish": fish})
            state["catches"].append({"at": at, "caught": caught})
            state["next_catch_at"] = at + state["catch_seconds"]
        if now >= state["ends_at"]:
            state["time_up"] = True

    def view(self, state, player_id):
        labels = player_labels(state["boats"], player_id)
        latest = state["catches"][-1] if state["catches"] else None
        return {
            "n_spots": len(state["spot_means"]),
            "seconds": state["seconds"],
            "ends_at": state["ends_at"],
            "boats": [
                {
                    "who": labels[player],
                    "spot": boat["spot"],
                    "arrives_at": boat["arrives_at"],
                }
                for player, boat in state["boats"].items()
            ],
            "fish": {labels[player]: n for player, n in state["fish"].items()},
            "catch_number": len(state["catches"]),
            "latest": [
                {"who": labels[c["player"]], "spot": c["spot"], "fish": c["fish"]}
                for c in (latest["caught"] if latest else [])
            ],
        }

    def is_over(self, state):
        return state["time_up"]

    def outcome(self, state, reason):
        return {
            "fish": state["fish"],
            "moves": state["moves"],
            "catches": state["catches"],
        }

    def bonus(self, outcome, reason, player_id):
        return outcome["fish"][player_id] * FISH_VALUE

    def bot(self, view, player_id, now):
        mine = next(b for b in view["boats"] if b["who"] == "you")
        if mine["spot"] is None:
            return Move(spot=1 + int(player_id) % view["n_spots"])
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


def player_labels(boats, player_id):
    """Label the player "you" and the others "B", "C", and so on, in a fixed order."""
    others = sorted((p for p in boats if p != player_id), key=int)
    return {player_id: "you", **dict(zip(others, LABELS))}


def lake_page(round_number):
    return ModularPage(
        "fish",
        Prompt(
            tags.div(
                tags.div(
                    tags.span(f"Round {round_number + 1}", cls="fish-round"),
                    tags.span("Joining the lake…", id="fish-status"),
                    tags.div(tags.div(id="fish-time-left"), cls="fish-clock"),
                    cls="fish-header",
                ),
                tags.div(id="fish-lake", cls="fish-lake"),
                tags.p(
                    "Click a spot to move your boat there. Moving takes "
                    f"{TRAVEL_SECONDS} s, and boats catch fish every "
                    f"{CATCH_SECONDS} s.",
                    cls="fish-help",
                ),
                tags.div(id="fish-scores", cls="fish-scores"),
                tags.p(id="fish-rejection", cls="fish-rejection"),
                id="fish-game",
            )
        ),
        LiveSessionControl(
            "fishing", player_left_message="A member has left the lake."
        ),
        js_page_modules=["/static/fishing.js"],
        css_links=["/static/fishing.css"],
        time_estimate=ROUND_SECONDS,
    )


def get_timeline():
    return Timeline(
        InfoPage(
            "You will join a small fishing society on a lake. Each round, "
            f"you fish for {ROUND_SECONDS} seconds. You can move your boat "
            "between spots at any time, and you see where the others fish "
            "and what they catch. Some spots are better than others. Members "
            f"come and go: you play up to {MAX_ROUNDS} rounds, and each fish "
            f"you catch pays ${FISH_VALUE:.2f}.",
            time_estimate=15,
        ),
        SimpleGrouper(
            GROUP,
            initial_group_size=SOCIETY_SIZE,
            max_group_size=SOCIETY_SIZE + 1,
            quorum=2,
            join_existing_groups=True,
            use_admission_points=True,
            target_group_size=2,
            below_quorum="continue_without_group",
            max_wait_time=GROUPING_WAIT,
            max_wait_action="continue_without_group",
            top_up_wait=TOP_UP_WAIT,
            waiting_message="Waiting for a society to join…",
        ),
        Module(
            "fishing",
            while_loop(
                "rounds",
                lambda participant: life_stage(participant) == "playing",
                join(
                    GroupBarrier(
                        id_="round_starts",
                        group_type=GROUP,
                        waiting_message="Waiting for the next round to start…",
                        late_after=LATE_AFTER,
                        late_action="leave_group",
                        admission_point=True,
                        newcomer_max_wait=NEWCOMER_MAX_WAIT,
                        newcomer_page=PageMaker(history_page, time_estimate=20),
                    ),
                    conditional("in_society", in_society, FishingTrial.cue()),
                ),
                expected_repetitions=MAX_ROUNDS,
            ),
        ),
        switch(
            "leaving",
            life_stage,
            {
                "retired": leave_a_tip(
                    "A new member has taken your place, so you retire from the society."
                ),
                "played_max_rounds": leave_a_tip(
                    f"You have played your {MAX_ROUNDS} rounds."
                ),
                "group_dissolved": InfoPage(
                    "Too few members stayed, so the society ended for you.",
                    time_estimate=5,
                ),
                "late": InfoPage(
                    "You were away for too long, so you left the society.",
                    time_estimate=5,
                ),
                "removed_by_experimenter": InfoPage(
                    "You were removed from the society.", time_estimate=5
                ),
                "no_group_formed": InfoPage(
                    "We couldn't find a society for you to join.", time_estimate=5
                ),
                "not_admitted": InfoPage(
                    "The society you joined couldn't start a round with you, "
                    "so you didn't play.",
                    time_estimate=5,
                ),
            },
        ),
        PageMaker(final_page, time_estimate=5),
    )


def in_society(participant: Participant) -> bool:
    return participant.in_sync_group(GROUP)


def own_trials(participant: Participant) -> List["FishingTrial"]:
    return (
        FishingTrial.query.filter_by(participant_id=participant.id)
        .order_by(FishingTrial.id)
        .all()
    )


def life_stage(participant: Participant) -> Optional[str]:
    """Return ``"playing"`` while the member keeps playing, otherwise why they stopped."""
    trials = own_trials(participant)
    last = trials[-1] if trials else None
    if last is not None and last.var.get("leaves_as"):
        return last.var.leaves_as
    if GROUP not in participant.active_sync_groups:
        return participant.sync_group_removal_reason(GROUP)
    return "playing"


def history_page(participant: Participant):
    """Show a newcomer where the society fished lately and the tips of members who have left."""
    society = participant.latest_sync_group(GROUP)
    rounds = society.rounds("fishing")
    scored = [r for r in rounds if r.var.has("spot_fish")]
    tips = [t.var.tip for r in rounds for t in r.trials if t.var.has("tip")]
    content = tags.div()
    with content:
        tags.p("Welcome to the society.")
        if scored:
            tags.p("Here is how many fish were caught at each spot lately:")
            with tags.ul():
                for r in scored[-HISTORY_ROUNDS:]:
                    tags.li(f"Round {r.number + 1}: " + _spot_text(r.var.spot_fish))
        if tips:
            tags.p("Tips from members who have left:")
            with tags.ul():
                for tip in tips[-TIPS_SHOWN:]:
                    tags.li(tip)
    return InfoPage(content, time_estimate=20)


def _spot_text(spot_fish: dict) -> str:
    return ", ".join(
        f"spot {spot}: {fish} fish"
        for spot, fish in sorted(spot_fish.items(), key=lambda kv: int(kv[0]))
    )


def _spot_fish(outcome) -> dict:
    """Return the fish caught at each spot in a session's outcome."""
    totals = {}
    for catch in outcome["catches"]:
        for c in catch["caught"]:
            totals[str(c["spot"])] = totals.get(str(c["spot"]), 0) + c["fish"]
    return totals


class FishingTrial(Trial):
    sync_group_type = GROUP
    time_estimate = ROUND_SECONDS + RESULTS_SECONDS

    def show_trial(self, experiment, participant):
        return [
            LiveSessionInitializer(
                id_="fishing",
                group_type=GROUP,
                game_type=Fishing,
                settings={
                    "spot_means": SPOT_MEANS,
                    "noise": CATCH_NOISE,
                    "seconds": ROUND_SECONDS,
                    "catch_seconds": CATCH_SECONDS,
                    "travel_seconds": TRAVEL_SECONDS,
                },
                waiting_message="Waiting for the others to reach the lake…",
            ),
            lake_page(self.sync_group_round),
            GroupBarrier(
                id_="round_finished",
                group_type=GROUP,
                waiting_message="Waiting for the other members…",
                late_after=LATE_AFTER,
                late_action="leave_group",
                on_release=self.score_round,
            ),
        ]

    def fish(self) -> int:
        """Return the fish the member caught this round."""
        if self.answer is None:
            return 0
        return self.answer["fish"].get(str(self.participant_id), 0)

    @classmethod
    def score_round(
        cls, trials: List["FishingTrial"], group_round: SyncGroupRound, group
    ):
        """Record where the round's fish were caught, and retire the longest-serving member if the round had too many."""
        outcome = next((t.answer for t in trials if t.answer is not None), None)
        group_round.var.spot_fish = {} if outcome is None else _spot_fish(outcome)
        retiring = None
        if len(trials) > SOCIETY_SIZE:
            seats = group_seats(group)
            retiring = min(trials, key=lambda t: seats[t.participant_id])
        group_round.var.retired_id = retiring.participant_id if retiring else None
        for trial in trials:
            trial.var.leaves_as = _leaves_as(trial, retiring)
            if trial.var.leaves_as:
                group.remove_participant(trial.participant, reason="finished")

    def gives_feedback(self, experiment, participant):
        return self.sync_group_outcome == "stayed"

    def show_feedback(self, experiment, participant):
        text = f"You caught {self.fish()} fish this round."
        if self.var.leaves_as == "retired":
            text += " A new member has joined, so this was your last round."
        return InfoPage(text, time_estimate=RESULTS_SECONDS)


def _leaves_as(trial, retiring) -> Optional[str]:
    if trial is retiring:
        return "retired"
    if trial.position + 1 >= MAX_ROUNDS:
        return "played_max_rounds"
    return None


def leave_a_tip(intro: str):
    """Ask a member who is leaving in good standing for a tip, and save it."""
    return join(
        ModularPage(
            "tip",
            f"{intro} Leave one tip for the members who come after you.",
            TextControl(one_line=True),
            time_estimate=30,
        ),
        CodeBlock(save_tip),
    )


def save_tip(participant: Participant):
    if participant.answer.strip():
        own_trials(participant)[-1].var.tip = participant.answer


def final_page(participant: Participant):
    fish = sum(t.fish() for t in own_trials(participant))
    return InfoPage(
        f"You caught {fish} fish. Your bonus is ${participant.performance_reward:.2f}.",
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Live microsociety demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per member per round and one per society per round."""
        trials = FishingTrial.query.order_by(FishingTrial.id).all()
        rounds = SyncGroupRound.query.filter_by(module_id="fishing").order_by(
            SyncGroupRound.sync_group_id, SyncGroupRound.number
        )
        return {
            "member_round": [
                {
                    "society_id": t.sync_group_id,
                    "round": t.sync_group_round,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    "tenure": t.position,
                    "outcome": t.sync_group_outcome,
                    "fish": t.fish(),
                    "moves": (t.answer or {})
                    .get("moves", {})
                    .get(str(t.participant_id)),
                    "leaves_as": t.var.get("leaves_as"),
                }
                for t in trials
            ],
            "society_round": [
                {
                    "society_id": r.sync_group_id,
                    "round": r.number,
                    "round_id": r.id,
                    "spot_fish": r.var.get("spot_fish"),
                    "retired_id": r.var.get("retired_id"),
                }
                for r in rounds
            ],
        }

    test_n_bots = 5
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        founders, newcomers = bots[:3], bots[3:]
        for bot in founders:
            bot.take_page()
        advance_past_wait_pages(founders)
        _play(founders)
        assert all("You caught" in bot.current_page_text for bot in founders)

        # A newcomer joins while the founders read their results, reads the
        # society's history at the next round's start, and plays that round,
        # so the longest-serving founder retires.
        newcomers[0].take_page()
        assert newcomers[0].is_waiting
        _start_round(founders, newcomers[0])
        assert "Welcome to the society" in newcomers[0].current_page_text
        assert "Round 1: spot" in newcomers[0].current_page_text
        newcomers[0].take_page()
        advance_past_wait_pages([*founders, newcomers[0]])
        _play([*founders, newcomers[0]])
        (retiree,) = [
            bot for bot in founders if "your last round" in bot.current_page_text
        ]
        retiree.take_page()
        assert retiree.current_page_label == "tip", retiree.current_page_label
        retiree.take_page(response="Follow the others.")
        assert retiree.current_page_text.startswith("You caught ")

        # The next newcomer reads the tip.
        others = [bot for bot in founders if bot is not retiree]
        newcomers[1].take_page()
        _start_round([*others, newcomers[0]], newcomers[1])
        assert "Follow the others." in newcomers[1].current_page_text
        run_bots_to_completion(bots, timeout=MAX_ROUNDS * (ROUND_SECONDS + 30))

        data = self.get_basic_data()
        rounds = data["society_round"]
        assert rounds[1]["retired_id"] == retiree.id, rounds
        for row in data["member_round"]:
            assert row["outcome"] == "stayed", row
        for bot in bots:
            trials = FishingTrial.query.filter_by(participant_id=bot.id).all()
            reward = bot.with_participant(lambda p: p.performance_reward)
            expected = sum(t.fish() for t in trials) * FISH_VALUE
            assert abs(reward - expected) < 1e-9, (bot.id, reward, expected)


def _play(bots):
    """Play a round on the lake, which the game plays for bots, and wait for the round's end."""
    for bot in bots:
        bot.take_page()
    advance_past_wait_pages(bots, timeout=ROUND_SECONDS + 60)


def _start_round(bots, newcomer=None):
    """Take the bots' results pages, then advance them and any ``newcomer`` to the round's start.

    The members then wait at the session's start for the newcomer, who reads
    the society's history first.
    """
    for bot in bots:
        bot.take_page()
    advance_past_wait_pages([*bots, newcomer] if newcomer else bots, stop_at="fishing")

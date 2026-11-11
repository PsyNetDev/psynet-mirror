"""A microsociety: a group of three that keeps going while its members are replaced.

Each round, every member picks one of ``N_SPOTS`` fishing spots and catches
a noisy number of fish around the spot's hidden average, then everyone sees
where the others fished and what they caught. Each fish pays ``FISH_VALUE``.

The society takes newcomers for as long as it lasts
(``join_existing_groups=True``). A newcomer is a pending member
(``admit_newcomers="at_admission_point"``) until the start of the next
round, a ``GroupBarrier`` with ``admission_point=True`` that admits them and shows
them the society's recent catches and tips (``newcomer_page``). When a round
had more than three members because a newcomer joined it, the
longest-serving member retires at its end. A member also stops after
``MAX_ROUNDS`` rounds. Before leaving, a member who retires or reaches the
cap leaves a tip for future members. The question is whether what earlier
members learned survives their departure.

Each round is one cued ``FishingTrial`` per member, after the round-start
barrier, so every member of a round starts it together. Its
``GroupBarrier`` in ``show_trial`` ends the round, and its release scores
it. Members are ranked by when they were admitted, which ``group_seats``
records. ``life_stage`` names every way a membership ends; the loop runs
while it is ``"playing"``, and the end of the timeline shows the page for
the stored stage. See ``README.md`` for the failure cases.
"""

import json
import random
from typing import List, Optional

from dominate import tags

import psynet.experiment
from psynet.bot import (
    BotDriver,
    advance_past_wait_pages,
    make_late_now,
    run_bots_to_completion,
)
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
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
from psynet.utils import serialise_datetime

GROUP = "society"
SOCIETY_SIZE = 3
# A safety limit: while newcomers keep arriving, members retire before it.
MAX_ROUNDS = 2 * SOCIETY_SIZE
# Average catches of the spots, which members don't see.
SPOT_MEANS = [2, 4, 3, 9, 1, 5, 6, 3]
N_SPOTS = len(SPOT_MEANS)
CATCH_NOISE = 2
FISH_VALUE = 0.01
DECISION_SECONDS = 20
RESULTS_SECONDS = 10
# Covers a newcomer reading the society's history before their first round.
LATE_AFTER = 60
GROUPING_WAIT = 120
# How long a lone member waits at the start of a round for a newcomer, before
# the society dissolves.
TOP_UP_WAIT = 30
# How long a newcomer waits for the next round to start before being turned
# away; covers a round played by members who take their full time.
NEWCOMER_MAX_WAIT = LATE_AFTER + DECISION_SECONDS + RESULTS_SECONDS
HISTORY_ROUNDS = 3
TIPS_SHOWN = 3


def get_timeline():
    return Timeline(
        InfoPage(
            f"You will join a small fishing society. Each round, every member "
            f"picks one of {N_SPOTS} fishing spots and catches some fish; some "
            "spots are better than others, and catches vary. Members come and "
            f"go: you play up to {MAX_ROUNDS} rounds, and each fish you catch "
            f"pays ${FISH_VALUE:.2f}.",
            time_estimate=15,
        ),
        SimpleGrouper(
            GROUP,
            initial_group_size=SOCIETY_SIZE,
            # A newcomer makes four until the oldest member retires.
            max_group_size=SOCIETY_SIZE + 1,
            quorum=2,
            join_existing_groups=True,
            admit_newcomers="at_admission_point",
            # Two members play a round without waiting for a third.
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
                    # The society may have dissolved at the barrier.
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
        # "late", "group_dissolved", "removed_by_experimenter", "left_experiment",
        # "no_group_formed" or "not_admitted".
        return participant.sync_group_removal_reason(GROUP)
    return "playing"


def history_page(participant: Participant):
    """Show a newcomer the society's latest rounds and the tips of members who have left."""
    # The newcomer may have left the society while reading this page.
    society = participant.latest_sync_group(GROUP)
    rounds = society.rounds("fishing")
    scored = [r for r in rounds if r.var.has("catches")]
    tips = [t.var.tip for r in rounds for t in r.trials if t.var.has("tip")]
    content = tags.div()
    with content:
        tags.p("Welcome to the society.")
        if scored:
            tags.p("Here is what its members caught lately:")
            with tags.ul():
                for r in scored[-HISTORY_ROUNDS:]:
                    tags.li(
                        f"Round {r.number + 1}: "
                        + _catches_text(r.var.spots, r.var.catches)
                    )
        if tips:
            tags.p("Tips from members who have left:")
            with tags.ul():
                for tip in tips[-TIPS_SHOWN:]:
                    tags.li(tip)
    return InfoPage(content, time_estimate=20)


def _catches_text(spots: dict, catches: dict) -> str:
    """Describe where each member fished and what they caught."""
    return ", ".join(
        _catch_label(spots[pid], catches[pid]) for pid in sorted(spots, key=int)
    )


def _catch_label(spot, catch) -> str:
    if spot is None:
        return "didn't fish"
    return f"spot {spot}: {catch} fish"


def _leaves_as(
    trial: "FishingTrial", retiring: Optional["FishingTrial"]
) -> Optional[str]:
    """Return how a member who stayed in this round leaves the society after it, or ``None`` if they play on."""
    if trial is retiring:
        return "retired"
    if trial.position + 1 >= MAX_ROUNDS:
        return "played_max_rounds"
    return None


def _draw_catch(spot: int) -> int:
    return max(0, round(random.gauss(SPOT_MEANS[spot - 1], CATCH_NOISE)))


class FishingTrial(Trial):
    sync_group_type = GROUP
    time_estimate = 5 + RESULTS_SECONDS

    def show_trial(self, experiment, participant):
        return [
            ModularPage(
                "fish",
                # Ticks appear as the others choose.
                GroupPrompt(
                    f"Round {self.sync_group_round + 1}. Where do you fish?",
                    participant=participant,
                    group=self.sync_group,
                ),
                PushButtonControl(
                    choices=list(range(1, N_SPOTS + 1)),
                    labels=[f"Spot {spot}" for spot in range(1, N_SPOTS + 1)],
                    arrange_vertically=False,
                    # Four to a row.
                    style="width: 22%",
                ),
                time_limit=DECISION_SECONDS,
                time_estimate=5,
            ),
            GroupBarrier(
                id_="round_finished",
                group_type=GROUP,
                waiting_message="Waiting for the other members…",
                late_after=LATE_AFTER,
                late_action="leave_group",
                # Releasing the society closes the round and scores it.
                on_release=self.score_round,
            ),
        ]

    @classmethod
    def score_round(
        cls, trials: List["FishingTrial"], group_round: SyncGroupRound, group
    ):
        """Draw each member's catch, and retire the longest-serving member if the round had too many."""
        for trial in trials:
            trial.var.catch = (
                None if trial.answer is None else _draw_catch(trial.answer)
            )
        # String keys, because var stores JSON.
        group_round.var.spots = {str(t.participant_id): t.answer for t in trials}
        group_round.var.catches = {str(t.participant_id): t.var.catch for t in trials}
        retiring = None
        too_many = len(trials) > SOCIETY_SIZE
        if too_many:
            seats = group_seats(group)
            retiring = min(trials, key=lambda t: seats[t.participant_id])
        group_round.var.retired_id = retiring.participant_id if retiring else None
        for trial in trials:
            trial.var.leaves_as = _leaves_as(trial, retiring)
            if trial.var.leaves_as:
                # They leave now, so the next round doesn't wait for them while
                # they read their results. Their round still counts as "stayed".
                group.remove_participant(trial.participant, reason="finished")

    def score_answer(self, answer, definition):
        """Return the fish the member caught this round."""
        if answer is None:
            return 0
        if self.sync_group_outcome == "stayed":
            return self.var.catch
        if self.sync_group_outcome == "group_dissolved":
            # The society ended before the round was scored, so they fish alone.
            self.var.catch = _draw_catch(answer)
            return self.var.catch
        # They left during the round: "late", "removed_by_experimenter" or "left_experiment".
        return 0

    def compute_performance_reward(self, score):
        return FISH_VALUE * score

    def gives_feedback(self, experiment, participant):
        # A member who left the round sees why at the end of the timeline.
        return self.sync_group_outcome == "stayed"

    def show_feedback(self, experiment, participant):
        if self.answer is None:
            text = "You ran out of time, so you didn't fish this round."
        else:
            text = f"You fished at spot {self.answer} and caught {self.var.catch} fish."
        if self.var.leaves_as == "retired":
            text += " A new member has joined, so this was your last round."
        spots, catches = self.group_round.var.spots, self.group_round.var.catches
        return ModularPage(
            "results",
            GroupPrompt(
                f"{text} Here is what everyone caught:",
                participant=participant,
                group=self.sync_group,
                answers={pid: _catch_label(spots[pid], catches[pid]) for pid in spots},
            ),
            time_estimate=RESULTS_SECONDS,
        )


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
    """Store a non-blank tip on the member's last trial, where newcomers' history pages find it."""
    if participant.answer.strip():
        own_trials(participant)[-1].var.tip = participant.answer


def final_page(participant: Participant):
    fish = round(sum(t.score for t in own_trials(participant)))
    return InfoPage(
        f"You caught {fish} fish. Your bonus is ${participant.performance_reward:.2f}.",
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Microsociety demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per member per round, one per society per round, and one per participant."""
        trials = FishingTrial.query.order_by(FishingTrial.id).all()
        rounds = SyncGroupRound.query.filter_by(module_id="fishing").order_by(
            SyncGroupRound.sync_group_id, SyncGroupRound.number
        )
        players = Participant.query.order_by(Participant.id).all()
        return {
            "member_round": [
                {
                    "society_id": t.sync_group_id,
                    "round": t.sync_group_round,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # How many rounds the member had played before this one.
                    "tenure": t.position,
                    # "stayed" if the member was in the society when the round
                    # was scored; otherwise why they left it during the round.
                    # None while the round is in progress.
                    "outcome": t.sync_group_outcome,
                    # None if the member ran out of time.
                    "spot": t.answer,
                    "timed_out": t.time_limit_reached,
                    "catch": t.var.get("catch"),
                    # "retired" or "played_max_rounds" for a member's last
                    # round, otherwise None.
                    "leaves_as": t.var.get("leaves_as"),
                }
                for t in trials
            ],
            "society_round": [
                {
                    "society_id": r.sync_group_id,
                    "round": r.number,
                    "round_id": r.id,
                    # None until the round is scored.
                    "spots": r.var.get("spots"),
                    "catches": r.var.get("catches"),
                    "retired_id": r.var.get("retired_id"),
                    # Set if the society dissolved during the round.
                    "dissolved_at": serialise_datetime(r.dissolved_at),
                }
                for r in rounds
            ],
            "member": [
                {
                    "participant_id": p.id,
                    "society_id": _society_id(p),
                    # "playing" for a member who is away but not yet removed,
                    # None for one who hasn't been grouped yet.
                    "left_as": life_stage(p),
                    # Including a round they left during.
                    "rounds_started": len(own_trials(p)),
                    "tip": next(
                        (t.var.tip for t in own_trials(p) if t.var.has("tip")), None
                    ),
                }
                for p in players
            ],
        }

    test_n_bots = 7
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        founders, newcomers = bots[:3], bots[3:]
        for bot in founders:
            bot.take_page()
        advance_past_wait_pages(founders)
        _play(founders, [4, 7, 1])

        # A newcomer joins while the founders read their results. The next
        # round's start admits them and shows them the society's history;
        # they play that round, so the longest-serving founder retires.
        newcomers[0].take_page()
        assert newcomers[0].is_waiting
        _start_round(founders, newcomers[0])
        assert "Welcome to the society" in newcomers[0].current_page_text
        assert "Round 1: spot 4" in newcomers[0].current_page_text
        newcomers[0].take_page()
        _play([*founders, newcomers[0]], [4, 4, 6, 4])
        (retiree,) = [
            bot for bot in founders if "your last round" in bot.current_page_text
        ]
        assert "your last round" not in newcomers[0].current_page_text
        assert not _in_society(retiree)
        retiree.take_page()
        assert retiree.current_page_label == "tip", retiree.current_page_label
        retiree.take_page(response="Spot 4 is reliable.")
        assert retiree.current_page_text.startswith("You caught ")

        # The next newcomer reads the tip and joins, so the next
        # longest-serving founder retires: one member leaves per newcomer.
        others = [bot for bot in founders if bot is not retiree]
        newcomers[1].take_page()
        _start_round([*others, newcomers[0]], newcomers[1])
        assert "Spot 4 is reliable." in newcomers[1].current_page_text
        newcomers[1].take_page()
        _play([*others, newcomers[0], newcomers[1]], [7, 4, 4, 4])
        (retiree2,) = [
            bot for bot in others if "your last round" in bot.current_page_text
        ]
        assert not _in_society(retiree2)
        retiree2.take_page()
        retiree2.take_page(response="Spot 7 is poor.")

        # The last founder goes quiet, so the round barrier removes them as
        # late, and they leave no tip.
        (quiet,) = [bot for bot in others if bot is not retiree2]
        society = newcomers[:2]
        _start_round([quiet, *society])
        for bot in society:
            bot.take_page(response=4)
        make_late_now(society, "round_finished")
        quiet.take_page(response=4)
        assert "You were away for too long" in quiet.current_page_text

        # The next newcomer reads both tips, then goes quiet on the history
        # page and is removed as late.
        newcomers[2].take_page()
        _start_round(society, newcomers[2])
        assert "Spot 4 is reliable." in newcomers[2].current_page_text
        assert "Spot 7 is poor." in newcomers[2].current_page_text
        for bot in society:
            bot.take_page(response=4)
        make_late_now(society, "round_finished")
        newcomers[2].take_page()
        assert "You were away for too long" in newcomers[2].current_page_text

        # A newcomer waits for the next round, but the first newcomer goes
        # quiet, so the society is left with one member and dissolves: the
        # other keeps their catch, and the waiting newcomer is turned away.
        _start_round(society)
        newcomers[3].take_page()
        assert newcomers[3].is_waiting
        society[1].take_page(response=4)
        make_late_now([society[1]], "round_finished")
        advance_past_wait_pages([newcomers[3]])
        assert "couldn't start a round with you" in newcomers[3].current_page_text
        society[0].take_page(response=4)
        assert "You were away for too long" in society[0].current_page_text
        run_bots_to_completion(bots)

        # Through JSON, as the dashboard and export read it.
        data = json.loads(json.dumps(self.get_basic_data()))
        rounds = data["society_round"]
        assert [r["retired_id"] for r in rounds[:3]] == [
            None,
            retiree.id,
            retiree2.id,
        ], rounds
        left_rounds = {
            (r["participant_id"], r["outcome"])
            for r in data["member_round"]
            if r["outcome"] != "stayed"
        }
        assert left_rounds == {
            (quiet.id, "late"),
            (newcomers[0].id, "late"),
            (newcomers[1].id, "group_dissolved"),
        }, left_rounds
        left_as = {m["participant_id"]: m["left_as"] for m in data["member"]}
        assert left_as == {
            retiree.id: "retired",
            retiree2.id: "retired",
            quiet.id: "late",
            newcomers[0].id: "late",
            newcomers[1].id: "group_dissolved",
            newcomers[2].id: "late",
            newcomers[3].id: "not_admitted",
        }, left_as
        tips = {m["participant_id"]: m["tip"] for m in data["member"]}
        assert tips[retiree.id] == "Spot 4 is reliable.", tips
        assert tips[quiet.id] is None, tips
        dissolved = [
            r for r in data["member_round"] if r["outcome"] == "group_dissolved"
        ]
        assert dissolved[0]["catch"] is not None, dissolved
        assert rounds[-1]["dissolved_at"] is not None, rounds


def _in_society(bot):
    return bot.with_participant(lambda p: GROUP in p.active_sync_groups)


def _society_id(participant):
    society = participant.latest_sync_group(GROUP)
    return society.id if society else None


def _play(bots, spots):
    for bot, spot in zip(bots, spots):
        bot.take_page(response=spot)
    advance_past_wait_pages(bots)


def _start_round(bots, newcomer=None):
    """Take the bots' results pages, then advance them and any ``newcomer`` past the round's start."""
    for bot in bots:
        bot.take_page()
    advance_past_wait_pages([*bots, newcomer] if newcomer else bots)

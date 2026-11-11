"""A microsociety: a group of three that keeps going while its members are replaced.

Each round, every member picks one of ``N_SPOTS`` fishing spots and catches
a noisy number of fish around the spot's hidden average, then everyone sees
where the others fished and what they caught. Each fish pays ``FISH_VALUE``.

The society takes newcomers for as long as it lasts
(``join_existing_groups=True``). When a newcomer has played a round, the
longest-serving member of that round retires, so the society is back to
three. A member also stops after ``MAX_ROUNDS`` rounds. Before leaving, a
member who retires or reaches the cap leaves a tip for future members, and a
newcomer starts by reading the society's recent catches and tips. The
question is whether what earlier members learned survives their departure.

Each round is one cued ``FishingTrial`` per member. The rounds loop cues
without ``round=``, so a newcomer's cue joins the round in progress, or
starts the next one, which the others then join. Each round ends at a single
``GroupBarrier`` in ``show_trial``, whose release scores the round, so a
newcomer never waits at a barrier the others have passed. Members are
ranked by when they joined, which ``group_seats`` records. ``life_stage``
names every way a membership ends; the loop runs while it is ``"playing"``,
and the end of the timeline shows the page for the stored stage. See
``README.md`` for the failure cases.
"""

import random
from typing import List

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
from psynet.sync import GroupBarrier, SimpleGrouper, group_seats, leave_group
from psynet.timeline import (
    CodeBlock,
    Module,
    PageMaker,
    Timeline,
    conditional,
    switch,
    while_loop,
)
from psynet.trial.main import SyncGroupNode, Trial

GROUP = "society"
SOCIETY_SIZE = 3
MAX_ROUNDS = 4
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
# How long a lone member waits at the end of a round for a newcomer, before
# the society dissolves.
TOP_UP_WAIT = 30
HISTORY_ROUNDS = 3


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
            below_quorum="continue_without_group",
            max_wait_time=GROUPING_WAIT,
            max_wait_action="continue_without_group",
            top_up_wait=TOP_UP_WAIT,
            waiting_message="Waiting for a society to join…",
        ),
        CodeBlock(remember_society),
        conditional(
            "newcomer",
            is_newcomer,
            PageMaker(history_page, time_estimate=20),
        ),
        Module(
            "fishing",
            while_loop(
                "rounds",
                lambda participant: life_stage(participant) == "playing",
                FishingTrial.cue(),
                expected_repetitions=MAX_ROUNDS,
            ),
        ),
        # Stored before leaving the society changes the removal reason.
        CodeBlock(remember_why_they_left),
        leave_group(GROUP),
        switch(
            "leaving",
            lambda participant: participant.var.left_as,
            {
                "retired": PageMaker(tip_page, time_estimate=30),
                "played_max_rounds": PageMaker(tip_page, time_estimate=30),
                "group_dissolved": InfoPage(
                    "Too few members stayed, so the society ended for you.",
                    time_estimate=5,
                ),
                "late": InfoPage(
                    "You were away for too long, so you left the society.",
                    time_estimate=5,
                ),
                "removed": InfoPage(
                    "You were removed from the society.", time_estimate=5
                ),
                "no_group_formed": InfoPage(
                    "We couldn't find a society for you to join.", time_estimate=5
                ),
            },
        ),
        CodeBlock(save_tip),
        PageMaker(final_page, time_estimate=5),
    )


def remember_society(participant: Participant):
    """Store the participant's society ID, or ``None``, for the export."""
    society = participant.active_sync_groups.get(GROUP)
    participant.var.society_id = society.id if society else None


def is_newcomer(participant: Participant) -> bool:
    """Return whether the participant joined a society after it formed."""
    society = participant.active_sync_groups.get(GROUP)
    # Seats count from 0 in the order members joined, so the founders have
    # the first SOCIETY_SIZE.
    return society is not None and group_seats(society)[participant.id] >= SOCIETY_SIZE


def own_trials(participant: Participant) -> List["FishingTrial"]:
    return (
        FishingTrial.query.filter_by(participant_id=participant.id)
        .order_by(FishingTrial.id)
        .all()
    )


def life_stage(participant: Participant) -> str:
    """Return ``"playing"`` while the member keeps playing, otherwise why they stopped."""
    trials = own_trials(participant)
    if trials and trials[-1].var.get("retires"):
        return "retired"
    if len(trials) >= MAX_ROUNDS:
        return "played_max_rounds"
    if GROUP not in participant.active_sync_groups:
        # "late", "group_dissolved", "removed" or "no_group_formed".
        return participant.sync_group_removal_reason(GROUP)
    # A member left alone plays on: the round's barrier waits up to
    # TOP_UP_WAIT for a newcomer, then dissolves the society.
    return "playing"


def remember_why_they_left(participant: Participant):
    participant.var.left_as = life_stage(participant)


def history_page(participant: Participant):
    """Show a newcomer the society's latest rounds and the tips of members who have left."""
    society = participant.active_sync_groups[GROUP]
    rounds = society.rounds("fishing")
    scored = [node for node in rounds if node.var.has("catches")]
    tips = [t.var.tip for node in rounds for t in node.all_trials if t.var.has("tip")]
    content = tags.div()
    with content:
        tags.p("Welcome to the society.")
        if scored:
            tags.p("Here is what its members caught lately:")
            with tags.ul():
                for node in scored[-HISTORY_ROUNDS:]:
                    tags.li(
                        f"Round {node.sync_group_round + 1}: "
                        + _catches_text(node.var.spots, node.var.catches)
                    )
        if tips:
            tags.p("Tips from members who have left:")
            with tags.ul():
                for tip in tips:
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
    def score_round(cls, trials: List["FishingTrial"], node: SyncGroupNode, group):
        """Draw each member's catch, and retire the longest-serving member if a newcomer played."""
        for trial in trials:
            trial.var.catch = (
                None if trial.answer is None else _draw_catch(trial.answer)
            )
        # String keys, because node.var stores JSON.
        node.var.spots = {str(t.participant_id): t.answer for t in trials}
        node.var.catches = {str(t.participant_id): t.var.catch for t in trials}
        retiring = None
        if len(trials) > SOCIETY_SIZE:
            seats = group_seats(group)
            retiring = min(trials, key=lambda t: seats[t.participant_id])
        for trial in trials:
            trial.var.retires = trial is retiring
        node.var.retired_id = retiring.participant_id if retiring else None

    def score_answer(self, answer, definition):
        """Return the fish the member caught; none if they didn't fish or the round wasn't scored."""
        return self.var.get("catch") or 0

    def compute_performance_reward(self, score):
        return FISH_VALUE * score

    def gives_feedback(self, experiment, participant):
        # A member who left the round sees why at the end of the timeline.
        return self.sync_group_outcome == "stayed"

    def show_feedback(self, experiment, participant):
        if self.answer is None:
            you = "You ran out of time, so you didn't fish this round."
        else:
            you = f"You fished at spot {self.answer} and caught {self.var.catch} fish."
        if self.var.retires:
            you += " A new member has joined, so this was your last round."
        spots, catches = self.node.var.spots, self.node.var.catches
        return ModularPage(
            "results",
            GroupPrompt(
                f"{you} Here is what everyone caught:",
                participant=participant,
                group=self.sync_group,
                answers={pid: _catch_label(spots[pid], catches[pid]) for pid in spots},
            ),
            time_estimate=RESULTS_SECONDS,
        )


def tip_page(participant: Participant):
    if participant.var.left_as == "retired":
        intro = "A new member has taken your place, so you retire from the society."
    else:
        intro = f"You have played your {MAX_ROUNDS} rounds."
    return ModularPage(
        "tip",
        f"{intro} Leave one tip for the members who come after you.",
        TextControl(one_line=True),
        time_estimate=30,
    )


def save_tip(participant: Participant):
    """Store the tip on the member's last trial, where newcomers' history pages find it."""
    if participant.var.left_as in ("retired", "played_max_rounds"):
        own_trials(participant)[-1].var.tip = participant.answer


def final_page(participant: Participant):
    fish = sum(t.var.get("catch") or 0 for t in own_trials(participant))
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
        rounds = SyncGroupNode.query.filter_by(module_id="fishing").order_by(
            SyncGroupNode.sync_group_id, SyncGroupNode.sync_group_round
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
                    "outcome": t.sync_group_outcome,
                    # None if the member ran out of time.
                    "spot": t.answer,
                    "timed_out": t.time_limit_reached,
                    "catch": t.var.get("catch"),
                    "retired": t.var.get("retires"),
                }
                for t in trials
            ],
            "society_round": [
                {
                    "society_id": n.sync_group_id,
                    "round": n.sync_group_round,
                    "node_id": n.id,
                    # None until the round is scored.
                    "spots": n.var.get("spots"),
                    "catches": n.var.get("catches"),
                    "retired_id": n.var.get("retired_id"),
                    # Set if the society dissolved during the round.
                    "dissolved_at": n.sync_group_dissolved_at,
                }
                for n in rounds
            ],
            "member": [
                {
                    "participant_id": p.id,
                    "society_id": p.var.get("society_id"),
                    # A stage of life_stage.
                    "left_as": p.var.get("left_as"),
                    "rounds_played": len(own_trials(p)),
                    "tip": next(
                        (t.var.tip for t in own_trials(p) if t.var.has("tip")), None
                    ),
                }
                for p in players
            ],
        }

    test_n_bots = 5
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        founders, (first_newcomer, second_newcomer) = bots[:3], bots[3:]
        for bot in founders:
            bot.take_page()
        advance_past_wait_pages(founders)
        _play(founders, [4, 7, 1])
        _see_results(founders)

        # A newcomer joins the society, reads its history and plays the
        # round in progress, so the longest-serving founder retires.
        first_newcomer.take_page()
        assert "Welcome to the society" in first_newcomer.current_page_text
        assert "Round 1: spot 4" in first_newcomer.current_page_text
        first_newcomer.take_page()
        _play([*founders, first_newcomer], [4, 4, 6, 4])
        (retiree,) = [
            bot for bot in founders if "your last round" in bot.current_page_text
        ]
        assert "your last round" not in first_newcomer.current_page_text
        retiree.take_page()
        assert retiree.current_page_label == "tip", retiree.current_page_label
        retiree.take_page(response="Spot 4 is reliable.")
        assert retiree.current_page_text.startswith("You caught ")

        # A founder goes quiet, so the round barrier removes them as late.
        stayers = [bot for bot in founders if bot is not retiree]
        _see_results([*stayers, first_newcomer])
        quiet = stayers[1]
        society = [stayers[0], first_newcomer]
        for bot in society:
            bot.take_page(response=4)
        make_late_now(society, "round_finished")
        quiet.take_page(response=4)
        assert "You were away for too long" in quiet.current_page_text

        # A second newcomer reads the retiree's tip.
        _see_results(society)
        second_newcomer.take_page()
        assert "Spot 4 is reliable." in second_newcomer.current_page_text
        second_newcomer.take_page()
        society.append(second_newcomer)
        _play(society, [4, 4, 4])
        run_bots_to_completion(bots)

        data = self.get_basic_data()
        rounds = data["society_round"]
        assert [r["retired_id"] for r in rounds[:2]] == [None, retiree.id], rounds
        left_rounds = [
            (r["participant_id"], r["outcome"])
            for r in data["member_round"]
            if r["outcome"] != "stayed"
        ]
        assert left_rounds == [
            (quiet.id, "late"),
            (second_newcomer.id, "group_dissolved"),
        ], left_rounds
        left_as = {m["participant_id"]: m["left_as"] for m in data["member"]}
        assert left_as[retiree.id] == "retired", left_as
        assert left_as[quiet.id] == "late", left_as
        assert left_as[stayers[0].id] == "played_max_rounds", left_as
        # The second newcomer was left alone, and nobody came to join them.
        assert left_as[second_newcomer.id] == "group_dissolved", left_as
        tips = {m["participant_id"]: m["tip"] for m in data["member"]}
        assert tips[retiree.id] == "Spot 4 is reliable.", tips


def _play(bots, spots):
    for bot, spot in zip(bots, spots):
        bot.take_page(response=spot)
    advance_past_wait_pages(bots)


def _see_results(bots):
    for bot in bots:
        bot.take_page()

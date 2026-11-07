"""Ultimatum game with cohorts that are randomly re-paired every round.

Players first wait in a lobby until a cohort of ``COHORT_SIZE`` forms, or until
at least ``MIN_COHORT_SIZE`` have waited ``SHORT_START_SECONDS``. Latecomers can
still join a cohort until its round ``OPEN_UNTIL_ROUND`` starts.

Each round, the :class:`~psynet.sync.Regrouper` pairs up the cohort's players,
avoiding last round's partner, and gives each pair a proposer and a
responder, alternating each player's role. It starts the round as soon as
the whole cohort is ready, or ``ROUND_DEADLINE_SECONDS`` after the first
player is back, without the players who aren't ready yet. With an odd number
of players, one who has played the most rounds sits that round out; a
player left waiting alone waits up to another ``ROUND_DEADLINE_SECONDS``
for the others to finish their round instead. Players leave the cohort when
they finish, so nobody waits for them.
In each pair, the proposer offers part of
``ENDOWMENT`` coins and, at the same time, the responder says the smallest
offer they would accept.

A player who doesn't answer within ``DECISION_SECONDS`` gets nothing that
round, and nor does their partner. A player who closes their page is taken
out of their pair so their partner isn't held up. A player who misses a
round joins the next one, and nobody is failed for being slow. Players
finish after ``N_ROUNDS`` rounds in a pair, or early, with an explanation,
after sitting out ``MAX_SIT_OUTS`` rounds or if their cohort falls apart.
"""

from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, Regrouper, SimpleGrouper
from psynet.timeline import (
    CodeBlock,
    PageMaker,
    Timeline,
    conditional,
    join,
    while_loop,
)

COHORT_SIZE = 4
MIN_COHORT_SIZE = 2
SHORT_START_SECONDS = 60
N_ROUNDS = 2
MAX_SIT_OUTS = 2
OPEN_UNTIL_ROUND = 2
DECISION_SECONDS = 30
# Longer than the decisions take, so a pair that finishes early is re-paired
# with the rest of the cohort rather than without them.
ROUND_DEADLINE_SECONDS = DECISION_SECONDS + 20
ENDOWMENT = 10
WAIT_TIMEOUT = ROUND_DEADLINE_SECONDS + DECISION_SECONDS + 20


def cohort_of(participant):
    return participant.active_sync_groups.get("cohort")


def in_pair(participant):
    return "pair" in participant.active_sync_groups


def lobby_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player to join your group."
    return "Waiting for your group of players to form. Starting in at most {SECONDS} s."


def round_message(seconds_left):
    if seconds_left is None:
        return "Waiting for the other players to finish their round."
    return "The next round starts in at most {SECONDS} s."


def ended_early(participant):
    return pairing.rounds_played(participant) < N_ROUNDS


def ended_early_page(participant):
    if pairing.rounds_sat_out(participant) >= MAX_SIT_OUTS:
        text = (
            f"You sat out {MAX_SIT_OUTS} rounds without a partner, "
            "so the game ended early for you."
        )
    else:
        text = "Not enough players stayed to keep playing, so the game ended early."
    return InfoPage(text, time_estimate=5)


def leave_cohort(participant):
    """Leave the cohort, so cohort members who are still playing don't wait for you."""
    cohort = cohort_of(participant)
    if cohort is not None:
        cohort.remove_participant(participant)


def cohort_accepts_newcomers(group, participant):
    """Let latecomers join until the cohort's round ``OPEN_UNTIL_ROUND`` starts."""
    # Includes players who have left, so the cohort stays closed after they go.
    cohort = [link.participant for link in group.participant_links]
    return all(pairing.rounds_played(p) < OPEN_UNTIL_ROUND for p in cohort)


def keep_playing(participant):
    cohort = cohort_of(participant)
    return (
        cohort is not None
        and len(cohort.active_participants) >= 2
        and pairing.rounds_played(participant) < N_ROUNDS
        and pairing.rounds_sat_out(participant) < MAX_SIT_OUTS
    )


def score_round(participants: List[Participant]):
    """Pay out the round, or note who ran out of time or left."""
    if len(participants) < 2:
        participants[0].var.outcome = "Your partner left, so nobody was paid."
        participants[0].var.decisions = None
        return
    if any(p.var.decision is None for p in participants):
        for participant in participants:
            participant.var.decisions = None
            participant.var.outcome = (
                "You ran out of time, so nobody was paid."
                if participant.var.decision is None
                else "Your partner ran out of time, so nobody was paid."
            )
        return
    roles = {pairing.role(p): p for p in participants}
    offer = roles["proposer"].var.decision
    minimum = roles["responder"].var.decision
    accepted = offer >= minimum
    decisions = {
        roles["proposer"].id: f"I offer {offer}",
        roles["responder"].id: f"I accept {minimum}+",
    }
    for participant in participants:
        participant.var.decisions = decisions
        if not accepted:
            outcome = f"The offer of {offer} coins was rejected, so nobody was paid."
        else:
            coins = (
                ENDOWMENT - offer if pairing.role(participant) == "proposer" else offer
            )
            outcome = f"The offer of {offer} coins was accepted. You earned {coins}."
        participant.var.outcome = outcome


def decision_page(participant):
    role = pairing.role(participant)
    if role == "proposer":
        prompt = f"You are the proposer. How many of {ENDOWMENT} coins do you offer?"
    else:
        prompt = (
            f"You are the responder. Your partner is splitting {ENDOWMENT} coins. "
            "What is the smallest offer you would accept?"
        )
    return ModularPage(
        role,
        # A tick appears once the partner has decided. Partners are anonymous,
        # so that nobody recognises a partner from an earlier round.
        GroupPrompt(prompt, participant=participant, group_type="pair", anonymous=True),
        PushButtonControl(choices=list(range(ENDOWMENT + 1))),
        save_answer="decision",
        time_limit=DECISION_SECONDS,
        time_estimate=10,
    )


def forming_cohort(participant):
    """Replace the welcome page while the player waits for a cohort."""
    return "We're putting together a group of players for you. Each round, you play with one other player from it."


def pairing_up(participant):
    """Replace the last results page while the cohort pairs up for the next round."""
    return "Getting the next round ready."


def waiting_for_partner(participant):
    """Replace the decision buttons with the player's choice while their partner decides."""
    if participant.var.decision is None:
        text = "You ran out of time, so nobody will be paid this round."
    elif pairing.role(participant) == "proposer":
        text = f"You offer {participant.var.decision} coins."
    else:
        text = f"You accept at least {participant.var.decision} coins."
    # No ticks: the partner arriving releases the pair at once.
    return GroupPrompt(
        text,
        participant=participant,
        group_type="pair",
        anonymous=True,
        show_progress=False,
    )


AWAY_TEXT = "You were away for too long, so you got no coins this round."


def show_outcome(participant):
    if not in_pair(participant):
        return InfoPage(AWAY_TEXT, time_estimate=5)
    if participant.var.decisions is None:
        return InfoPage(participant.var.outcome, time_estimate=5)
    return ModularPage(
        "outcome",
        GroupPrompt(
            participant.var.outcome,
            participant=participant,
            group_type="pair",
            answers=participant.var.decisions,
            anonymous=True,
        ),
        time_estimate=5,
    )


def not_playing(participant):
    if pairing.sat_out(participant):
        text = "You sit out this round. It doesn't count towards your rounds."
    else:
        # Removed from this round's pair before reaching the decision page.
        text = AWAY_TEXT
    return InfoPage(text, time_estimate=5)


pairing = Regrouper(
    "pair",
    within="cohort",
    group_size=2,
    roles=["proposer", "responder"],
    deadline=ROUND_DEADLINE_SECONDS,
    release_left_over=True,
    content=round_message,
    waiting_screen=pairing_up,
)


def play_round():
    return join(
        pairing,
        conditional(
            "paired",
            in_pair,
            join(
                PageMaker(decision_page, time_estimate=10),
                GroupBarrier(
                    id_="round_finished",
                    group_type="pair",
                    content="Waiting for your partner…",
                    waiting_screen=waiting_for_partner,
                    # A player is taken out 30 s after the round starts (long
                    # enough for a background tab to notice), but not while their
                    # answer to the timed decision page may still be on its way.
                    timeout_between_barriers_time=30,
                    timeout_between_barriers_action="kick",
                    on_release=score_round,
                ),
                PageMaker(show_outcome, time_estimate=5),
            ),
            # Without a cohort the game is over; the ended-early page explains why.
            conditional(
                "in_cohort",
                lambda participant: cohort_of(participant) is not None,
                PageMaker(not_playing, time_estimate=5),
            ),
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Ultimatum game with re-pairing demo"

    timeline = Timeline(
        InfoPage(
            "You will play several rounds of a game with other players in your group.",
            time_estimate=5,
        ),
        SimpleGrouper(
            "cohort",
            initial_group_size=COHORT_SIZE,
            min_group_size=MIN_COHORT_SIZE,
            start_short_after=SHORT_START_SECONDS,
            join_existing_groups=True,
            join_criterion=cohort_accepts_newcomers,
            fail_participants_below_min_size=False,
            content=lobby_message,
            waiting_screen=forming_cohort,
            max_wait_time=300,
        ),
        while_loop(
            "rounds",
            keep_playing,
            play_round(),
            expected_repetitions=N_ROUNDS,
        ),
        CodeBlock(leave_cohort),
        conditional(
            "ended_early",
            ended_early,
            PageMaker(ended_early_page, time_estimate=5),
        ),
    )

    test_n_bots = 4
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)

        # Round 1: the whole cohort is ready, so it starts at once. Latecomers
        # can still join while it is being played.
        assert _cohort_accepts_newcomers(bots[0])
        _play(bots)
        assert all("The offer of" in bot.current_page_text for bot in bots)

        # Round 2: one player lingers on their results, so the round starts at
        # the deadline without them, and one of the other three sits out.
        others = bots[:3]
        for bot in others:
            bot.take_page()
        advance_past_wait_pages(others, timeout=WAIT_TIMEOUT)
        assert not _cohort_accepts_newcomers(bots[0])
        sitting_out = [b for b in others if "sit out" in b.current_page_text]
        assert len(sitting_out) == 1
        _play([b for b in others if b not in sitting_out])

        # The pair has played its two rounds. The lingerer wasn't failed, and
        # the sit-out didn't count, so those two play a final round together.
        # The cohort stays closed to latecomers after the pair has left it.
        for bot in bots:
            bot.take_page()
        last_pair = [sitting_out[0], bots[3]]
        advance_past_wait_pages(last_pair, timeout=WAIT_TIMEOUT)
        assert not _cohort_accepts_newcomers(last_pair[0])
        _play(last_pair)
        assert all("The offer of" in bot.current_page_text for bot in last_pair)
        for bot in last_pair:
            bot.take_page()
        for bot in bots:
            bot.refresh_status()
            assert "That's the end" in bot.current_page_text


def _play(bots):
    for bot in bots:
        response = 5 if bot.current_page_label == "proposer" else 3
        bot.take_page(response=response)
    advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)


def _cohort_accepts_newcomers(bot):
    return cohort_accepts_newcomers(cohort_of(Participant.query.get(bot.id)), None)

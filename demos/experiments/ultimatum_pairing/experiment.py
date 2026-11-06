"""Ultimatum game with teams that are randomly re-paired every round.

Players first wait in a lobby until a team of ``TEAM_SIZE`` forms, or until
at least ``MIN_TEAM_SIZE`` have waited ``SHORT_START_SECONDS``. Latecomers can
still join a team until it is near the end of the game.

Each round, the :class:`~psynet.sync.Regrouper` pairs up the team's players.
It starts the round as soon as the whole team is ready, or
``ROUND_DEADLINE_SECONDS`` after the previous round started, without the
players who aren't ready yet. An odd player out sits that round out; a
player left waiting alone waits up to another ``ROUND_DEADLINE_SECONDS``
for the others to finish their round instead. Players leave the team when
they finish, so nobody waits for them.
In each pair, the proposer offers part of
``ENDOWMENT`` coins and, at the same time, the responder says the smallest
offer they would accept.

A player who doesn't answer in time is taken out of their pair so their
partner isn't held up. A player who misses a round joins the next one, and
nobody is failed for being slow. Players finish after ``N_ROUNDS`` rounds in
a pair, or early, with an explanation, after sitting out ``MAX_SIT_OUTS``
rounds or if their team falls apart.
"""

import random
import time
from typing import List

import psynet.experiment
from psynet.bot import BotDriver
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

TEAM_SIZE = 4
MIN_TEAM_SIZE = 2
SHORT_START_SECONDS = 60
N_ROUNDS = 2
MAX_SIT_OUTS = 2
LAST_ROUND_FOR_NEWCOMERS = 1
DECISION_SECONDS = 30
# Longer than the decisions take, so a pair that finishes early is re-paired
# with the rest of the team rather than without them.
ROUND_DEADLINE_SECONDS = DECISION_SECONDS + 20
ENDOWMENT = 10


def team_of(participant):
    return participant.active_sync_groups.get("team")


def in_pair(participant):
    return "pair" in participant.active_sync_groups


def lobby_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player to join your team."
    return "Waiting for your team to form. Starting in at most {SECONDS} s."


def round_message(seconds_left):
    if seconds_left is None:
        return "Waiting for the other players to finish their round."
    return "The next round starts in at most {SECONDS} s."


def ended_early(participant):
    return participant.var.get("rounds_played", 0) < N_ROUNDS


def ended_early_page(participant):
    if participant.var.get("rounds_sat_out", 0) >= MAX_SIT_OUTS:
        text = (
            f"You sat out {MAX_SIT_OUTS} rounds without a partner, "
            "so the game ended early for you."
        )
    else:
        text = "Not enough players stayed to keep playing, so the game ended early."
    return InfoPage(text, time_estimate=5)


def leave_team(participant):
    """Leave the team, so teammates who are still playing don't wait for you."""
    team = team_of(participant)
    if team is not None:
        team.remove_participant(participant)


def team_accepts_newcomers(group, participant):
    """Let latecomers join a team only while enough rounds are left."""
    return group.var.get("round", 0) < LAST_ROUND_FOR_NEWCOMERS


def keep_playing(participant):
    team = team_of(participant)
    return (
        team is not None
        and len(team.active_participants) >= 2
        and participant.var.get("rounds_played", 0) < N_ROUNDS
        and participant.var.get("rounds_sat_out", 0) < MAX_SIT_OUTS
    )


def count_round_played(participant):
    participant.var.rounds_played = participant.var.get("rounds_played", 0) + 1


def count_sit_out(participant):
    participant.var.rounds_sat_out = participant.var.get("rounds_sat_out", 0) + 1


def pair_new_partners(members, within_group, regrouper):
    """Pair members at random, avoiding last round's partner when possible."""
    best = None
    for _ in range(20):
        shuffled = random.sample(members, len(members))
        pairs = [shuffled[i : i + 2] for i in range(0, len(shuffled) - 1, 2)]
        repeats = sum(a.var.get("partner", None) == b.id for a, b in pairs)
        if best is None or repeats < best[0]:
            best = (repeats, pairs)
        if repeats == 0:
            break
    return best[1]


def start_round(within_group, groups, left_over, regrouper):
    """Note that the team has started a round and give each pair its roles."""
    within_group.var.round = within_group.var.get("round", 0) + 1
    for pair in groups:
        proposer, responder = pair.participants
        proposer.var.role, responder.var.role = "proposer", "responder"
        proposer.var.partner, responder.var.partner = responder.id, proposer.id


def score_round(participants: List[Participant]):
    """Pay out the round, or note that the partner ran out of time."""
    if len(participants) < 2:
        participants[
            0
        ].var.outcome = "Your partner ran out of time, so nobody was paid."
        participants[0].var.decisions = None
        return
    roles = {p.var.role: p for p in participants}
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
            coins = ENDOWMENT - offer if participant.var.role == "proposer" else offer
            outcome = f"The offer of {offer} coins was accepted. You earned {coins}."
        participant.var.outcome = outcome


def decision_page(participant):
    if participant.var.role == "proposer":
        prompt = f"You are the proposer. How many of {ENDOWMENT} coins do you offer?"
    else:
        prompt = (
            f"You are the responder. Your partner is splitting {ENDOWMENT} coins. "
            "What is the smallest offer you would accept?"
        )
    # The page is rebuilt on submit, when a player who ran out of time has
    # already left the pair.
    pair = participant.active_sync_groups.get("pair")
    if pair is not None:
        # A tick appears once the partner has decided. Partners are anonymous,
        # so that nobody recognises a partner from an earlier round.
        prompt = GroupPrompt(
            prompt, group=pair, participant=participant, anonymous=True
        )
    return ModularPage(
        participant.var.role,
        prompt,
        PushButtonControl(choices=list(range(ENDOWMENT + 1))),
        save_answer="decision",
        time_estimate=10,
    )


def show_outcome(participant):
    if not in_pair(participant):
        return InfoPage(
            "You ran out of time, so you got no coins this round.", time_estimate=5
        )
    if participant.var.decisions is None:
        return InfoPage(participant.var.outcome, time_estimate=5)
    return ModularPage(
        "outcome",
        GroupPrompt(
            participant.var.outcome,
            group=participant.active_sync_groups["pair"],
            participant=participant,
            answers=participant.var.decisions,
            anonymous=True,
        ),
        time_estimate=5,
    )


def play_round():
    return join(
        Regrouper(
            "pair",
            within="team",
            group_size=2,
            deadline=ROUND_DEADLINE_SECONDS,
            form_groups=pair_new_partners,
            release_left_over=True,
            on_release=start_round,
            content=round_message,
        ),
        conditional(
            "paired",
            in_pair,
            join(
                CodeBlock(count_round_played),
                PageMaker(decision_page, time_estimate=10),
                GroupBarrier(
                    id_="round_finished",
                    group_type="pair",
                    content="Waiting for your partner…",
                    timeout_between_barriers_time=DECISION_SECONDS,
                    timeout_between_barriers_action="kick",
                    skip_if_not_in_group=True,
                    on_release=score_round,
                ),
                PageMaker(show_outcome, time_estimate=5),
            ),
            join(
                CodeBlock(count_sit_out),
                InfoPage(
                    "You sit out this round. It doesn't count towards your rounds.",
                    time_estimate=5,
                ),
            ),
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Ultimatum game with re-pairing demo"

    timeline = Timeline(
        InfoPage(
            "You will play several rounds of a game with other players in your team.",
            time_estimate=5,
        ),
        SimpleGrouper(
            "team",
            initial_group_size=TEAM_SIZE,
            min_group_size=MIN_TEAM_SIZE,
            start_short_after=SHORT_START_SECONDS,
            join_existing_groups=True,
            join_criterion=team_accepts_newcomers,
            fail_participants_below_min_size=False,
            content=lobby_message,
            max_wait_time=300,
        ),
        while_loop(
            "rounds",
            keep_playing,
            play_round(),
            expected_repetitions=N_ROUNDS,
        ),
        CodeBlock(leave_team),
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
        _wait_while_held(bots)

        # Round 1: the whole team is ready, so it starts at once.
        _play(bots)
        assert all("The offer of" in bot.current_page_text for bot in bots)

        # Round 2: one player lingers on their results, so the round starts at
        # the deadline without them, and one of the other three sits out.
        others = bots[:3]
        for bot in others:
            bot.take_page()
        _wait_while_held(others)
        sitting_out = [b for b in others if "sit out" in b.current_page_text]
        assert len(sitting_out) == 1
        _play([b for b in others if b not in sitting_out])

        # The pair has played its two rounds. The lingerer wasn't failed, and
        # the sit-out didn't count, so those two play a final round together.
        for bot in bots:
            bot.take_page()
        last_pair = [sitting_out[0], bots[3]]
        _wait_while_held(last_pair)
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
    _wait_while_held(bots)


def _wait_while_held(bots, timeout=ROUND_DEADLINE_SECONDS + DECISION_SECONDS + 10):
    """Poll until no bot is on a waiting screen, as a browser would."""
    deadline = time.monotonic() + timeout
    while True:
        held = []
        for bot in bots:
            bot.refresh_status()
            if getattr(bot.get_current_page(), "is_timeline_hold", False):
                held.append(bot)
                bot.take_page()
        if not held:
            return
        if time.monotonic() > deadline:
            raise RuntimeError(f"Bots {[b.id for b in held]} are still waiting.")
        time.sleep(0.5)

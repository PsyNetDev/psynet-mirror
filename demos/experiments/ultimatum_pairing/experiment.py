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
from psynet.sync import (
    GroupBarrier,
    Regrouper,
    SimpleGrouper,
    SyncGroup,
    group_rounds,
    participant_rounds,
)
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
    return participant.in_sync_group("pair")


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
        cohort.remove_participant(participant, reason="finished")


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


def score_round(
    group: SyncGroup, participants: List[Participant], left: List[Participant]
):
    """Record the pair's offer and its result, and each player's decision and coins."""
    roles = {pairing.role(p): p for p in participants}
    proposer, responder = roles.get("proposer"), roles.get("responder")
    offer = proposer.var.decision if proposer else None
    minimum = responder.var.decision if responder else None
    if len(participants) < 2:
        away = any(p.sync_group_removal_reason("pair") == "late" for p in left)
        result = "partner_away" if away else "partner_left"
    elif offer is None or minimum is None:
        result = "timed_out"
    else:
        result = "accepted" if offer >= minimum else "rejected"
    group.record_round(
        proposer_id=proposer.id if proposer else None,
        responder_id=responder.id if responder else None,
        offer=offer,
        minimum=minimum,
        result=result,
    )
    if result == "accepted":
        coins = {"proposer": ENDOWMENT - offer, "responder": offer}
    else:
        coins = {"proposer": 0, "responder": 0}
    for role, participant in roles.items():
        participant.record_round(decision=participant.var.decision, coins=coins[role])


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
        GroupPrompt(
            prompt, participant=participant, group_type="pair", names="anonymous"
        ),
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
        names="anonymous",
        show_progress=False,
    )


AWAY_TEXT = "You were away for too long, so you got no coins this round."


UNPAID_TEXTS = {
    "partner_away": "Your partner was away for too long, so nobody was paid.",
    "partner_left": "Your partner left, so nobody was paid.",
    "timed_out": "Your partner ran out of time, so nobody was paid.",
}


def show_outcome(participant):
    if not in_pair(participant):
        return InfoPage(AWAY_TEXT, time_estimate=5)
    # The round the player just played: the next one can't start for them
    # until they leave this page.
    pair = group_rounds("round_finished", participant)[-1]
    offer, result = pair["offer"], pair["result"]
    if result == "timed_out" and participant.var.decision is None:
        return InfoPage("You ran out of time, so nobody was paid.", time_estimate=5)
    if result in UNPAID_TEXTS:
        return InfoPage(UNPAID_TEXTS[result], time_estimate=5)
    if result == "rejected":
        text = f"The offer of {offer} coins was rejected, so nobody was paid."
    else:
        coins = participant_rounds("round_finished", participant)[-1]["coins"]
        text = f"The offer of {offer} coins was accepted. You earned {coins}."
    return ModularPage(
        "outcome",
        GroupPrompt(
            text,
            participant=participant,
            group_type="pair",
            answers={
                pair["proposer_id"]: f"I offer {offer}",
                pair["responder_id"]: f"I accept {pair['minimum']}+",
            },
            names="anonymous",
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
    roles=["proposer", "responder"],
    deadline=ROUND_DEADLINE_SECONDS,
    left_over="sit_out",
    waiting_message=round_message,
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
                    waiting_message="Waiting for your partner…",
                    waiting_screen=waiting_for_partner,
                    # A player is taken out 30 s after the round starts (long
                    # enough for a background tab to notice), but not while their
                    # answer to the timed decision page may still be on its way.
                    late_after=30,
                    late_action="leave_group",
                    on_release=score_round,
                    record_rounds=True,
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
            quorum=MIN_COHORT_SIZE,
            start_short_after=SHORT_START_SECONDS,
            join_existing_groups=True,
            join_criterion=cohort_accepts_newcomers,
            waiting_message=lobby_message,
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

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round and one per pair per round, as recorded at the end of each round."""
        return {
            "player_round": participant_rounds("round_finished"),
            "group_round": group_rounds("round_finished"),
        }

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
            assert bot.current_notice is None

        # Two pairs in round 1, then one pair in each of rounds 2 and 3, each
        # with one proposer (5) and one responder (3). Round 2 also has a row
        # for the player who sat it out; the lingerer missed it.
        data = self.get_basic_data()
        pairs = data["group_round"]
        assert [(p["round"], p["offer"], p["minimum"], p["result"]) for p in pairs] == [
            (round_, 5, 3, "accepted") for round_ in [1, 1, 2, 3]
        ], pairs
        rows = data["player_round"]
        assert [row["round"] for row in rows] == [1] * 4 + [2] * 3 + [3] * 2, rows
        played = [row for row in rows if row["outcome"] == "played"]
        assert [row["participant_id"] for row in rows if row not in played] == [
            sitting_out[0].id
        ], rows
        assert all(
            row["decision"] == {"proposer": 5, "responder": 3}[row["role"]]
            for row in played
        )
        # Each player's row links to their pair's round; the sit-out's to none.
        pair_of = {p["round_id"]: p for p in pairs}
        assert all(
            row["participant_id"] in pair_of[row["round_id"]]["member_ids"]
            for row in played
        )
        assert [row["round_id"] for row in rows if row not in played] == [None]


def _play(bots):
    for bot in bots:
        response = 5 if bot.current_page_label == "proposer" else 3
        bot.take_page(response=response)
    advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)


def _cohort_accepts_newcomers(bot):
    return cohort_accepts_newcomers(cohort_of(Participant.query.get(bot.id)), None)

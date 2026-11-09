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

Each player's round is one cued ``OfferTrial``. Because the trial class has
``sync_group_type = "pair"``, the two trials of a pair share a node: the
pair's offer and result go in ``trial.node.var`` and each player's coins in
``trial.var``, and ``get_basic_data`` reads both back.

A player who doesn't answer within ``DECISION_SECONDS`` gets nothing that
round, and nor does their partner. A player who closes their page is taken
out of their pair and cohort, so nobody waits for them. A player who misses a
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
from psynet.sync import GroupBarrier, Regrouper, SimpleGrouper, only_in_group
from psynet.timeline import (
    CodeBlock,
    Module,
    PageMaker,
    Timeline,
    conditional,
    join,
    while_loop,
)
from psynet.trial.main import SyncGroupNode, Trial

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


def get_timeline():
    return Timeline(
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
            # Here the cohort keeps accepting top-ups (join_criterion only turns
            # newcomers away), so it is never dissolved. In a cohort without
            # top-ups, removing a late player would dissolve it below its
            # quorum, and the default "fail" would fail the players on time.
            below_quorum="continue_without_group",
        ),
        Module(
            "game",
            while_loop(
                "rounds",
                keep_playing,
                join(
                    pairing,
                    only_in_group(
                        "pair",
                        OfferTrial.cue({"endowment": ENDOWMENT}),
                        # Without a cohort the game is over and the ended-early
                        # page explains why, but a player removed for being
                        # away, who left the cohort too, is told about the round.
                        otherwise=conditional(
                            "explain_round",
                            lambda participant: (
                                cohort_of(participant) is not None
                                or participant.sync_group_removal_reason("pair")
                                == "late"
                            ),
                            PageMaker(not_playing, time_estimate=5),
                        ),
                    ),
                ),
                expected_repetitions=N_ROUNDS,
            ),
        ),
        CodeBlock(leave_cohort),
        conditional(
            "ended_early",
            ended_early,
            PageMaker(ended_early_page, time_estimate=5),
        ),
    )


def cohort_of(participant):
    return participant.active_sync_groups.get("cohort")


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
    elif participant.sync_group_removal_reason("cohort") == "late":
        text = "You were away for too long, so the game ended early for you."
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
    elif participant.current_trial.sync_group_role == "proposer":
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


def not_playing(participant):
    if pairing.sat_out(participant):
        text = (
            "You sit out this round without a partner. If you sit out "
            f"{MAX_SIT_OUTS} rounds, the game ends early for you."
        )
    else:
        # Removed from this round's pair for being away too long.
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

UNPAID_TEXTS = {
    "partner_away": "Your partner was away for too long, so nobody was paid.",
    "partner_left": "Your partner left, so nobody was paid.",
    "timed_out": "Your partner ran out of time, so nobody was paid.",
}


class OfferTrial(Trial):
    sync_group_type = "pair"
    time_estimate = 15

    def show_trial(self, experiment, participant):
        return join(
            self.decision_page(participant),
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
                on_release=self.score_pair,
            ),
        )

    def decision_page(self, participant):
        role = self.sync_group_role
        endowment = self.definition["endowment"]
        if role == "proposer":
            prompt = (
                f"You are the proposer. How many of {endowment} coins do you offer?"
            )
        else:
            prompt = (
                f"You are the responder. Your partner is splitting {endowment} coins. "
                "What is the smallest offer you would accept?"
            )
        return ModularPage(
            role,
            # A tick appears once the partner has decided. Partners are anonymous,
            # so that nobody recognises a partner from an earlier round.
            GroupPrompt(
                prompt, participant=participant, group_type="pair", names="anonymous"
            ),
            PushButtonControl(
                choices=list(range(endowment + 1)), arrange_vertically=False
            ),
            save_answer="decision",
            time_limit=DECISION_SECONDS,
            time_estimate=10,
        )

    @classmethod
    def score_pair(
        cls, trials: List["OfferTrial"], node: SyncGroupNode, left: List[Participant]
    ):
        """Save the pair's offer and result on the node, and each player's coins on their trial.

        The trials' answers are only saved once the trials end, after this
        barrier, so the decisions are read from ``participant.var``.
        """
        by_role = {trial.sync_group_role: trial for trial in trials}
        decisions = {role: t.participant.var.decision for role, t in by_role.items()}
        offer, minimum = decisions.get("proposer"), decisions.get("responder")
        if len(trials) < 2:
            away = [p for p in left if p.sync_group_removal_reason("pair") == "late"]
            # An away partner has probably closed their page, so they leave the
            # cohort too, and the rest of it doesn't wait for them.
            for partner in away:
                cohort = cohort_of(partner)
                if cohort is not None:
                    cohort.remove_participant(partner, reason="late")
            result = "partner_away" if away else "partner_left"
        elif offer is None or minimum is None:
            result = "timed_out"
        else:
            result = "accepted" if offer >= minimum else "rejected"
        node.var.players = {role: t.participant_id for role, t in by_role.items()}
        node.var.offer = offer
        node.var.minimum = minimum
        node.var.result = result
        coins = (
            {"proposer": ENDOWMENT - offer, "responder": offer}
            if result == "accepted"
            else {}
        )
        for role, trial in by_role.items():
            trial.var.coins = coins.get(role, 0)

    def show_feedback(self, experiment, participant):
        result, offer = self.node.var.result, self.node.var.offer
        if result == "timed_out" and self.answer is None:
            return InfoPage("You ran out of time, so nobody was paid.", time_estimate=5)
        if result in UNPAID_TEXTS:
            return InfoPage(UNPAID_TEXTS[result], time_estimate=5)
        if result == "rejected":
            text = f"The offer of {offer} coins was rejected, so nobody was paid."
        else:
            text = (
                f"The offer of {offer} coins was accepted. You earned {self.var.coins}."
            )
        players = self.node.var.players
        return ModularPage(
            "outcome",
            GroupPrompt(
                text,
                participant=participant,
                group_type="pair",
                answers={
                    players["proposer"]: f"I offer {offer}",
                    players["responder"]: f"I accept {self.node.var.minimum}+",
                },
                names="anonymous",
            ),
            time_estimate=5,
        )


def _play(bots):
    for bot in bots:
        response = 5 if bot.current_page_label == "proposer" else 3
        bot.take_page(response=response)
    advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)


def _cohort_accepts_newcomers(bot):
    return cohort_accepts_newcomers(cohort_of(Participant.query.get(bot.id)), None)


class Exp(psynet.experiment.Experiment):
    label = "Ultimatum game with re-pairing demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per pair, from the trials, one per pair, from the nodes, and one per player."""
        trials = OfferTrial.query.order_by(OfferTrial.id).all()
        pairs = SyncGroupNode.query.filter_by(module_id="game").order_by(
            SyncGroupNode.id
        )
        players = Participant.query.order_by(Participant.id).all()
        return {
            "player_pair": [
                {
                    "pair_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    "role": t.sync_group_role,
                    # None if the player was away and never sent a decision.
                    "decision": t.answer,
                    "coins": t.var.get("coins"),
                }
                for t in trials
            ],
            "pair": [
                {
                    "pair_id": n.sync_group_id,
                    "node_id": n.id,
                    "proposer_id": n.var.get("players", {}).get("proposer"),
                    "responder_id": n.var.get("players", {}).get("responder"),
                    "offer": n.var.get("offer"),
                    "minimum": n.var.get("minimum"),
                    "result": n.var.get("result"),
                }
                for n in pairs
            ],
            "player": [
                {
                    "participant_id": p.id,
                    "rounds_played": pairing.rounds_played(p),
                    "rounds_sat_out": pairing.rounds_sat_out(p),
                }
                for p in players
            ],
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
        # One of the pair closes their page. Once late, they leave the pair and
        # the cohort, so the rest of the cohort doesn't wait for them.
        stayer, leaver = [b for b in others if b not in sitting_out]
        _play([stayer])
        assert "Your partner was away" in stayer.current_page_text
        assert leaver.with_participant(lambda p: cohort_of(p) is None)
        # The leaver comes back later. Rounds count the pairs a player joined,
        # so this pair was their second round and the game didn't end early.
        for text in [AWAY_TEXT, "That's the end"]:
            leaver.take_page()
            assert text in leaver.current_page_text

        # The stayer has been in two pairs. The lingerer wasn't failed, and
        # the sit-out didn't count, so those two play a final round together.
        # The cohort stays closed to latecomers after the stayer has left it.
        for bot in [stayer, *sitting_out, bots[3]]:
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

        # Two pairs in round 1, then one pair in each of rounds 2 and 3. The
        # pairs that both played have one proposer (5) and one responder (3).
        data = self.get_basic_data()
        away = [p["pair_id"] for p in data["pair"] if p["result"] == "partner_away"]
        assert len(away) == 1, data["pair"]
        pairs = [p for p in data["pair"] if p["pair_id"] not in away]
        assert [(p["offer"], p["minimum"], p["result"]) for p in pairs] == [
            (5, 3, "accepted")
        ] * 3, pairs
        rows = [r for r in data["player_pair"] if r["pair_id"] not in away]
        assert len(rows) == 6
        assert all(
            (row["decision"], row["coins"])
            == {"proposer": (5, 5), "responder": (3, 5)}[row["role"]]
            for row in rows
        ), rows
        sat_out = {p["participant_id"]: p["rounds_sat_out"] for p in data["player"]}
        assert sat_out == {bot.id: int(bot in sitting_out) for bot in bots}

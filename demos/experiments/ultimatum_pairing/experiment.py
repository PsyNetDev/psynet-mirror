"""Ultimatum game with cohorts that are randomly re-paired every round.

Players first wait in a lobby until a cohort of ``COHORT_SIZE`` forms, or until
at least ``MIN_COHORT_SIZE`` have waited ``SHORT_START_SECONDS``. Latecomers can
still join a cohort during its first ``OPEN_FOR_ROUNDS`` rounds.

Each round, a :class:`~psynet.sync.Regrouper` (``PairingRegrouper``, in
``pairing.py``) pairs up the cohort's players, avoiding last round's partner,
and gives each pair a proposer and a responder, alternating each player's role. It starts the round as soon as
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
``sync_group_type = PAIR``, the two trials of a pair share a round: the
pair's offer and result go in ``trial.group_round.var`` and each player's coins in
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
from psynet.bot import BotDriver, advance_past_wait_pages, regroup_now
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import (
    GroupBarrier,
    SimpleGrouper,
    SyncGroupRound,
    leave_group,
)
from psynet.timeline import (
    Module,
    Timeline,
    join,
    switch,
    while_loop,
)
from psynet.trial.main import Trial

from .pairing import PAIR, PairingRegrouper, last_partner_id, last_role

COHORT = "cohort"
COHORT_SIZE = 4
MIN_COHORT_SIZE = 2
SHORT_START_SECONDS = 60
N_ROUNDS = 2
MAX_SIT_OUTS = 2
OPEN_FOR_ROUNDS = 1
DECISION_SECONDS = 30
# Longer than the decisions take, so a pair that finishes early is re-paired
# with the rest of the cohort rather than without them.
ROUND_DEADLINE_SECONDS = DECISION_SECONDS + 20
ENDOWMENT = 10


def get_timeline():
    return Timeline(
        InfoPage(
            "You will play several rounds of a game with other players in your group.",
            time_estimate=5,
        ),
        SimpleGrouper(
            COHORT,
            initial_group_size=COHORT_SIZE,
            quorum=MIN_COHORT_SIZE,
            start_short_after=SHORT_START_SECONDS,
            join_existing_groups=True,
            # A latecomer joins at the next round's pairing, which admits
            # them, and isn't counted or waited for until then.
            admit_newcomers="at_admission_point",
            target_group_size=MIN_COHORT_SIZE,
            waiting_message=lobby_message,
            waiting_screen=forming_cohort,
            max_wait_time=300,
            # Once top-ups stop, a cohort that falls below its quorum is
            # dissolved; this ends the game for the players left instead of
            # failing them.
            below_quorum="continue_without_group",
        ),
        Module(
            "game",
            while_loop(
                "rounds",
                keep_playing,
                join(
                    pairing,
                    switch(
                        "round",
                        round_status,
                        {
                            "paired": OfferTrial.cue({"endowment": ENDOWMENT}),
                            "sat_out": InfoPage(SIT_OUT_TEXT, time_estimate=5),
                            # The game is over; the ended-early page explains why.
                            "no_cohort": [],
                        },
                    ),
                ),
                expected_repetitions=N_ROUNDS,
            ),
        ),
        leave_group(COHORT),
        switch(
            "game_over",
            game_over_reason,
            {
                "played_all_rounds": [],
                # Their round's results page has already told them.
                "late": [],
                "sat_out_too_often": InfoPage(
                    f"You sat out {MAX_SIT_OUTS} rounds without a partner, "
                    "so the game ended early for you.",
                    time_estimate=5,
                ),
                "removed_by_experimenter": InfoPage(
                    "You were removed from the game.", time_estimate=5
                ),
                "not_admitted": InfoPage(
                    "Your group's game closed to new players before the next "
                    "round, so there is no game for you.",
                    time_estimate=5,
                ),
                "too_few_players": InfoPage(
                    "Not enough players stayed to keep playing, "
                    "so the game ended early.",
                    time_estimate=5,
                ),
            },
        ),
    )


def in_pair(participant):
    return participant.in_sync_group(PAIR)


def round_status(participant):
    """Return whether the regrouper paired the player, sat them out, or left them with no cohort."""
    if in_pair(participant):
        return "paired"
    if pairing.sat_out(participant):
        return "sat_out"
    return "no_cohort"


def cohort_of(participant):
    return participant.active_sync_groups.get(COHORT)


def lobby_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player to join your group."
    return "Waiting for your group of players to form. Starting in at most {SECONDS} s."


def round_message(seconds_left):
    if seconds_left is None:
        return "Waiting for the other players to finish their round."
    return "The next round starts in at most {SECONDS} s."


def game_over_reason(participant):
    """Return why the player's game is over, or ``None`` while they keep playing."""
    # The pairs the regrouper has put the player in, including one they were
    # removed from; rounds they sat out don't count.
    if pairing.rounds_played(participant) >= N_ROUNDS:
        return "played_all_rounds"
    if pairing.rounds_sat_out(participant) >= MAX_SIT_OUTS:
        return "sat_out_too_often"
    # Being late takes a player out of their pair and their cohort; the
    # experimenter can remove them from the cohort on the dashboard; and a
    # latecomer is turned away if the cohort closes before pairing them.
    reason = participant.sync_group_removal_reason(COHORT)
    if reason in ("late", "removed_by_experimenter", "not_admitted"):
        return reason
    cohort = cohort_of(participant)
    if cohort is None or cohort.n_active_participants < 2:
        return "too_few_players"
    return None


def keep_playing(participant):
    return game_over_reason(participant) is None


def forming_cohort(participant):
    """Replace the welcome page while the player waits for a cohort."""
    return "We're putting together a group of players for you. Each round, you play with one other player from it."


def pairing_up(participant):
    """Replace the last results page while the cohort pairs up for the next round."""
    return "Getting the next round ready."


def waiting_for_partner(participant, trial):
    """Replace the decision buttons with the player's choice while their partner decides."""
    if trial.answer is None:
        text = "You ran out of time, so nobody will be paid this round."
    elif trial.sync_group_role == "proposer":
        text = f"You offer {trial.answer} coins."
    else:
        text = f"You accept at least {trial.answer} coins."
    # No ticks: the partner arriving releases the pair at once.
    return GroupPrompt(
        text,
        participant=participant,
        group=trial.sync_group,
        names="anonymous",
        show_progress=False,
    )


SIT_OUT_TEXT = (
    "You sit out this round without a partner. If you sit out "
    f"{MAX_SIT_OUTS} rounds, the game ends early for you."
)


pairing = PairingRegrouper(
    PAIR,
    within=COHORT,
    roles=["proposer", "responder"],
    deadline=ROUND_DEADLINE_SECONDS,
    left_over="sit_out",
    stop_top_ups_after_rounds=OPEN_FOR_ROUNDS,
    waiting_message=round_message,
    waiting_screen=pairing_up,
)

OUTCOME_TEXTS = {
    "away": (
        "You were away for too long, so you got no coins this round, "
        "and the game is over for you."
    ),
    "removed_by_experimenter": "You were removed from your pair, so you got no coins this round.",
    "own_time_out": "You ran out of time, so nobody was paid.",
    "partner_away": "Your partner was away for too long, so nobody was paid.",
    "partner_left": "Your partner left, so nobody was paid.",
    "timed_out": "Your partner ran out of time, so nobody was paid.",
    "rejected": "The offer of {offer} coins was rejected, so nobody was paid.",
    "accepted": "The offer of {offer} coins was accepted. You earned {coins}.",
}


class OfferTrial(Trial):
    sync_group_type = PAIR
    time_estimate = 15

    def show_trial(self, experiment, participant):
        return join(
            self.decision_page(participant),
            GroupBarrier(
                id_="round_finished",
                group_type=PAIR,
                waiting_message="Waiting for your partner…",
                waiting_screen=waiting_for_partner,
                # A player is taken out 30 s after the round starts (long
                # enough for a background tab to notice), but not while their
                # answer to the timed decision page may still be on its way.
                # They have probably closed their page, so they leave the
                # cohort too, and the next split doesn't wait for them.
                late_after=30,
                late_action="leave_group",
                also_leave=[COHORT],
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
                prompt,
                participant=participant,
                group=self.sync_group,
                names="anonymous",
            ),
            PushButtonControl(
                choices=list(range(endowment + 1)), arrange_vertically=False
            ),
            time_limit=DECISION_SECONDS,
            time_estimate=10,
        )

    @classmethod
    def score_pair(
        cls,
        trials: List["OfferTrial"],
        group_round: SyncGroupRound,
        left: List[Participant],
    ):
        """Save the pair's players, offer and result on the round, and each player's coins on their trial."""
        by_role = {trial.sync_group_role: trial for trial in trials}
        decisions = {role: t.answer for role, t in by_role.items()}
        offer, minimum = decisions.get("proposer"), decisions.get("responder")
        if len(trials) < 2:
            away = any(p.sync_group_removal_reason(PAIR) == "late" for p in left)
            result = "partner_away" if away else "partner_left"
        elif offer is None or minimum is None:
            result = "timed_out"
        else:
            result = "accepted" if offer >= minimum else "rejected"
        # From all the round's trials, so a player removed for being away is kept.
        players = {t.sync_group_role: t.participant_id for t in group_round.trials}
        pair = group_round.var
        pair.proposer_id = players.get("proposer")
        pair.responder_id = players.get("responder")
        pair.offer = offer
        pair.minimum = minimum
        pair.result = result
        coins = (
            {
                "proposer": group_round.definition["endowment"] - offer,
                "responder": offer,
            }
            if result == "accepted"
            else {}
        )
        for role, trial in by_role.items():
            trial.var.coins = coins.get(role, 0)

    def outcome(self):
        """Return the key in ``OUTCOME_TEXTS`` that describes the round for this player."""
        if self.sync_group_outcome == "late":
            return "away"
        # From the dashboard; the round may not have been scored yet.
        if self.sync_group_outcome == "removed_by_experimenter":
            return "removed_by_experimenter"
        if self.group_round.var.result == "timed_out" and self.answer is None:
            return "own_time_out"
        return self.group_round.var.result

    def show_feedback(self, experiment, participant):
        outcome = self.outcome()
        pair = self.group_round.var
        text = OUTCOME_TEXTS[outcome].format(
            offer=pair.get("offer"), coins=self.var.get("coins")
        )
        if outcome not in ("accepted", "rejected"):
            return InfoPage(text, time_estimate=5)
        return ModularPage(
            "outcome",
            GroupPrompt(
                text,
                participant=participant,
                group=self.sync_group,
                answers={
                    pair.proposer_id: f"I offer {pair.offer}",
                    pair.responder_id: f"I accept {pair.minimum}+",
                },
                names="anonymous",
            ),
            time_estimate=5,
        )


WAIT_TIMEOUT = ROUND_DEADLINE_SECONDS + DECISION_SECONDS + 20


def _play(bots):
    for bot in bots:
        response = 5 if bot.current_page_label == "proposer" else 3
        bot.take_page(response=response)
    advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)


def _cohort_accepts_newcomers(bot):
    return bot.with_participant(lambda p: cohort_of(p).accepts_top_ups)


class Exp(psynet.experiment.Experiment):
    label = "Ultimatum game with re-pairing demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round from the trials, one per pair from the rounds, and one per player."""
        trials = OfferTrial.query.order_by(OfferTrial.id).all()
        pairs = SyncGroupRound.query.filter_by(module_id="game").order_by(
            SyncGroupRound.id
        )
        players = Participant.query.order_by(Participant.id).all()
        return {
            "player_round": [
                {
                    "pair_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # The player's own round; pairs change every round.
                    "round": t.position,
                    "role": t.sync_group_role,
                    # False while the trial runs or if the player left it; the
                    # decision is then the answer so far.
                    "complete": t.complete,
                    # "stayed" if the player was in the group when the round
                    # was scored; otherwise "late" if they were taken out
                    # before that for being away, or "removed_by_experimenter" if the
                    # experimenter removed them on the dashboard.
                    "outcome": t.sync_group_outcome,
                    # None if the player was away and never sent a decision.
                    "decision": t.answer,
                    "coins": t.var.get("coins"),
                }
                for t in trials
            ],
            "pair": [
                {
                    "pair_id": r.sync_group_id,
                    "round_id": r.id,
                    "proposer_id": r.var.get("proposer_id"),
                    "responder_id": r.var.get("responder_id"),
                    "offer": r.var.get("offer"),
                    "minimum": r.var.get("minimum"),
                    "result": r.var.get("result"),
                }
                for r in pairs
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
        first_partner = {bot.id: bot.with_participant(last_partner_id) for bot in bots}
        first_role = {bot.id: bot.with_participant(last_role) for bot in bots}

        # Round 2: one player lingers on their results, so the round starts at
        # the deadline without them, and one of the other three sits out.
        # regroup_now brings the deadline forward, so the test doesn't wait.
        others = bots[:3]
        for bot in others:
            bot.take_page()
        regroup_now(others, pairing)
        assert not _cohort_accepts_newcomers(bots[0])
        sitting_out = [b for b in others if "sit out" in b.current_page_text]
        assert len(sitting_out) == 1
        # One of the pair closes their page. Once late, they leave the pair and
        # the cohort, so the rest of the cohort doesn't wait for them.
        stayer, leaver = [b for b in others if b not in sitting_out]
        # Any two of the three could pair, so nobody meets last round's partner.
        assert first_partner[stayer.id] != leaver.id
        # Players who held different roles last round both switch.
        if first_role[stayer.id] != first_role[leaver.id]:
            for bot in (stayer, leaver):
                assert bot.with_participant(last_role) != first_role[bot.id]
        _play([stayer])
        assert "Your partner was away" in stayer.current_page_text
        assert leaver.with_participant(lambda p: cohort_of(p) is None)
        # The leaver comes back later. Rounds count the pairs a player joined,
        # so this pair was their second round and the game didn't end early.
        for text in [OUTCOME_TEXTS["away"], "That's the end"]:
            leaver.take_page()
            assert text in leaver.current_page_text, leaver.current_page_text

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
        away_rows = [r for r in data["player_round"] if r["pair_id"] in away]
        assert sorted(r["outcome"] for r in away_rows) == ["late", "stayed"]
        rows = [r for r in data["player_round"] if r["pair_id"] not in away]
        assert len(rows) == 6
        assert all(row["outcome"] == "stayed" for row in rows), rows
        assert all(
            (row["decision"], row["coins"])
            == {"proposer": (5, 5), "responder": (3, 5)}[row["role"]]
            for row in rows
        ), rows
        sat_out = {p["participant_id"]: p["rounds_sat_out"] for p in data["player"]}
        assert sat_out == {bot.id: int(bot in sitting_out) for bot in bots}

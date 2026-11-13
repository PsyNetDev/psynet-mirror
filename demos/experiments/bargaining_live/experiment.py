"""Live bargaining in pairs that are re-paired every round.

Players wait in a lobby until a cohort of ``COHORT_SIZE`` forms. Each round,
a :class:`~psynet.sync.Regrouper` pairs up the cohort's players, and each
pair bargains live over ``ENDOWMENT`` coins for up to ``BARGAIN_SECONDS``
seconds. Either player can propose a split at any time, and change it, and
either can accept their partner's current proposal. Accepting ends the round
with a deal; if the time runs out first, nobody is paid.

Each player's round is one cued ``BargainTrial``. The trial class has
``sync_group_type = PAIR``, so the two trials of a pair share the trial's
definition, which the trial passes to the game as its settings. The game
page's answer is the session's outcome, which the results page reads.

This is the live counterpart of the ``ultimatum_pairing`` demo, which uses
the same cohort and pairing set-up for a one-shot offer.
"""

from dallinger.realtime import Reject
from dominate import tags

import psynet.experiment
from psynet.bot import Bot
from psynet.live_session import (
    LiveGame,
    LiveGameBarrier,
    LiveMessage,
    LiveSessionControl,
    live_session_result,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import Regrouper, SimpleGrouper, leave_group
from psynet.timeline import Module, Timeline, join, switch, while_loop
from psynet.trial.main import Trial

COHORT = "cohort"
PAIR = "pair"
COHORT_SIZE = 4
N_ROUNDS = 2
ENDOWMENT = 10
BARGAIN_SECONDS = 60
COIN_VALUE = 0.05
# Bots open with a proposal that gives their partner this many coins, and
# accept any proposal that gives them at least as many.
BOT_GIVES = 4


def partner_of(state, player_id):
    """Return the other player's id, or ``None`` if the player plays alone."""
    others = [p for p in state["offers"] if p != player_id]
    return others[0] if others else None


class Propose(LiveMessage):
    """Propose a split: the player keeps ``keep`` coins and the partner gets the rest."""

    type = "propose"
    keep: int

    def apply(self, game, state, player_id, now):
        if not 0 <= self.keep <= state["endowment"]:
            raise Reject(f"Keep between 0 and {state['endowment']} coins.")
        state["offers"][player_id] = self.keep
        state["n_proposals"] += 1


class Accept(LiveMessage):
    """Accept the partner's proposal. ``keep`` is what the partner keeps in
    the proposal the player saw, so a proposal that changed in the meantime
    isn't accepted by mistake."""

    type = "accept"
    keep: int

    def apply(self, game, state, player_id, now):
        partner = partner_of(state, player_id)
        if partner is None or state["offers"][partner] != self.keep:
            raise Reject("Your partner has just changed their proposal.")
        state["deal"] = {partner: self.keep, player_id: state["endowment"] - self.keep}
        state["deal_at"] = now - state["live_session"]["started_at"]


class Bargain(LiveGame):
    channel = "bargain"
    messages = [Propose, Accept]
    max_duration = BARGAIN_SECONDS + 120

    def initial_state(self, players, settings):
        return {
            "endowment": settings["endowment"],
            "seconds": settings["seconds"],
            "offers": {player: None for player in players},
            "n_proposals": 0,
            "deal": None,
            "deal_at": None,
            "ends_at": None,
            "timed_out": False,
        }

    def on_start(self, state, now):
        state["ends_at"] = now + state["seconds"]

    def next_deadline(self, state):
        return state["ends_at"]

    def tick(self, state, now):
        if state["ends_at"] is not None and now >= state["ends_at"]:
            state["timed_out"] = True

    def view(self, state, player_id):
        partner = partner_of(state, player_id)
        return {
            "endowment": state["endowment"],
            "seconds": state["seconds"],
            "ends_at": state["ends_at"],
            "mine": state["offers"][player_id],
            "theirs": None if partner is None else state["offers"][partner],
            "deal": None if state["deal"] is None else state["deal"][player_id],
        }

    def is_over(self, state):
        return (
            state["deal"] is not None
            or state["timed_out"]
            or partner_of(state, next(iter(state["offers"]))) is None
        )

    def outcome(self, state, reason):
        return {
            "deal": state["deal"],
            "deal_at": state["deal_at"],
            "n_proposals": state["n_proposals"],
        }

    def performance_reward(self, outcome, reason, player_id):
        return (outcome["deal"] or {}).get(player_id, 0) * COIN_VALUE

    def bot(self, view, player_id, now):
        if view["deal"] is not None:
            return None
        theirs = view["theirs"]
        if theirs is not None and view["endowment"] - theirs >= BOT_GIVES:
            return Accept(keep=theirs)
        players = view["live_session"]["players"]
        if view["mine"] is None and player_id == min(players, key=int):
            return Propose(keep=view["endowment"] - BOT_GIVES)
        return None


def bargaining_page():
    return ModularPage(
        "bargain",
        Prompt(
            tags.div(
                tags.div(
                    tags.span("Joining the game…", id="bargain-status"),
                    tags.div(tags.div(id="bargain-time-left"), cls="bargain-clock"),
                    cls="bargain-header",
                ),
                tags.div(
                    tags.span(
                        tags.span(cls="bargain-coin bargain-coin-you"), "Your coins"
                    ),
                    tags.span(
                        tags.span(cls="bargain-coin bargain-coin-partner"),
                        "Your partner's coins",
                    ),
                    cls="bargain-key",
                ),
                tags.div(
                    tags.section(
                        tags.h3("Your proposal"),
                        tags.div(id="bargain-mine-coins", cls="bargain-coins"),
                        tags.label(
                            "You keep ",
                            tags.strong(ENDOWMENT // 2, id="bargain-keep-value"),
                            f" of {ENDOWMENT} coins",
                            fr="bargain-keep",
                        ),
                        tags.input_(
                            type="range",
                            id="bargain-keep",
                            min=0,
                            max=ENDOWMENT,
                            value=ENDOWMENT // 2,
                        ),
                        tags.button(
                            "Propose",
                            type="button",
                            id="bargain-propose",
                            cls="btn btn-primary",
                        ),
                        tags.p(id="bargain-mine", cls="bargain-note"),
                        cls="bargain-card",
                    ),
                    tags.section(
                        tags.h3("Your partner's proposal"),
                        tags.div(id="bargain-theirs-coins", cls="bargain-coins"),
                        tags.p(id="bargain-theirs", cls="bargain-note"),
                        tags.button(
                            "Accept",
                            type="button",
                            id="bargain-accept",
                            cls="btn btn-success",
                        ),
                        id="bargain-theirs-card",
                        cls="bargain-card",
                    ),
                    cls="bargain-cards",
                ),
                tags.div(id="bargain-deal", cls="bargain-deal", hidden=True),
                tags.p(id="bargain-rejection", cls="bargain-rejection"),
                id="bargain-game",
            )
        ),
        LiveSessionControl("bargain", player_left_message="Your partner has left."),
        js_page_modules=["/static/bargaining.js"],
        css_links=["/static/bargaining.css"],
        time_estimate=BARGAIN_SECONDS,
    )


class BargainTrial(Trial):
    sync_group_type = PAIR
    time_estimate = BARGAIN_SECONDS + 10

    def show_trial(self, experiment, participant):
        return join(
            LiveGameBarrier(
                id_="bargain",
                group_type=PAIR,
                game_type=Bargain,
                settings=self.definition,
                max_wait_time=30,
                max_wait_action="leave_group",
            ),
            bargaining_page(),
        )

    def coins(self):
        """Return the coins the player got from this round's deal."""
        deal = (self.answer or {}).get("deal") or {}
        return deal.get(str(self.participant_id), 0)

    def show_feedback(self, experiment, participant):
        outcome = self.answer
        if outcome is None:
            text = "Your partner didn't arrive, so there was no game this round."
        elif outcome["deal"] is None:
            text = "You didn't reach a deal in time, so nobody was paid."
        else:
            mine = self.coins()
            text = (
                f"You made a deal: you get {mine} coins and your partner "
                f"gets {ENDOWMENT - mine}."
            )
        return InfoPage(text, time_estimate=5)


pairing = Regrouper(PAIR, within=COHORT, group_size=2, left_over="sit_out", deadline=30)


def cohort_of(participant):
    return participant.active_sync_groups.get(COHORT)


def keep_playing(participant):
    cohort = cohort_of(participant)
    return (
        pairing.rounds_played(participant) < N_ROUNDS
        and cohort is not None
        and cohort.n_active_participants >= 2
    )


def round_status(participant):
    if participant.in_sync_group(PAIR):
        return "paired"
    if pairing.sat_out(participant):
        return "sat_out"
    return "no_cohort"


def get_timeline():
    return Timeline(
        InfoPage(
            "You will bargain live with other players, a different one each round.",
            time_estimate=5,
        ),
        SimpleGrouper(
            COHORT,
            initial_group_size=COHORT_SIZE,
            max_wait_time=300,
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
                            "paired": BargainTrial.cue(
                                {"endowment": ENDOWMENT, "seconds": BARGAIN_SECONDS}
                            ),
                            "sat_out": InfoPage(
                                "You sit out this round without a partner.",
                                time_estimate=5,
                            ),
                            "no_cohort": [],
                        },
                    ),
                ),
                expected_repetitions=N_ROUNDS,
            ),
        ),
        leave_group(COHORT),
        InfoPage("That's the end of the game.", time_estimate=5),
    )


class Exp(psynet.experiment.Experiment):
    label = "Live bargaining demo"

    timeline = get_timeline()

    test_n_bots = COHORT_SIZE
    test_mode = "parallel"

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round."""
        trials = BargainTrial.query.order_by(BargainTrial.id).all()
        return {
            "player_round": [
                {
                    "pair_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    "round": t.position,
                    "deal": (t.answer or {}).get("deal") is not None,
                    "coins": t.coins(),
                    "deal_at": (t.answer or {}).get("deal_at"),
                    "n_proposals": (t.answer or {}).get("n_proposals"),
                }
                for t in trials
            ]
        }

    def test_check_bot(self, bot: Bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = BargainTrial.query.filter_by(participant_id=bot.id).all()
        assert len(trials) == N_ROUNDS
        for trial in trials:
            assert trial.answer["deal"] is not None, trial.answer
            assert sorted(trial.answer["deal"].values()) == [
                BOT_GIVES,
                ENDOWMENT - BOT_GIVES,
            ]
            session_id = trial.group_round.live_session_id
            assert live_session_result(session_id).outcome == trial.answer
        expected = sum(t.coins() for t in trials) * COIN_VALUE
        assert abs(bot.performance_reward - expected) < 1e-9

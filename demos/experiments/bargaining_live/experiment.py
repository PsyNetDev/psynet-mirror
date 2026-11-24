"""Live bargaining in pairs that are re-paired every round.

Players wait in a lobby until a cohort of ``COHORT_SIZE`` forms. Each round,
a :class:`~psynet.sync.Regrouper` pairs up the cohort's players, and each
pair bargains live over a stake of coins, chosen at random from ``STAKES``,
for up to ``BARGAIN_SECONDS`` seconds. Either player can propose a split at
any time, and change it, and either can accept their partner's current
proposal. Accepting ends the round with a deal; if the time runs out first,
nobody is paid. The game's ``end_reason`` says how the round ended, so the
feedback and the export can tell a deal, a time-out and a partner who left
apart.

Each player's round is one cued ``BargainTrial``. The trial class has
``sync_group_type = "pair"``, so the two trials of a pair share the trial's
definition, with the pair's stake, which the trial passes to the game as its
settings. The trial's answer holds the player's coins; how the pair bargained
is kept in the round's ``live_game_outcome``.

This is the live counterpart of the ``ultimatum_pairing`` demo, which uses
the same cohort and pairing set-up for a one-shot offer.
"""

import random

import pytest
from dominate import tags

import psynet.experiment
from psynet.bot import Bot
from psynet.live_game import (
    PLAYERS_LEFT,
    LiveGame,
    LiveGamePage,
    LiveMessage,
    PlayLiveGame,
    Reject,
)
from psynet.page import InfoPage
from psynet.sync import Regrouper, SimpleGrouper, SyncGroupRound, leave_group
from psynet.timeline import Module, PageMaker, Timeline, join, switch, while_loop
from psynet.trial.main import Trial

COHORT_SIZE = 4
N_ROUNDS = 2
# The coins a pair bargains over, chosen at random for each pair.
STAKES = [10, 20]
BARGAIN_SECONDS = 60
# Seconds a player can keep their new partner waiting, first for the game
# and then for opening its page.
LATE_AFTER = 30
# How long the game page shows the deal before the feedback page.
RESULT_SECONDS = 5
# Longer than a round takes, even one whose partner arrives just in time,
# with the game's start, its result and the feedback page, so a pair that
# makes a quick deal waits for the other pair to come back rather than being
# paired with each other again.
ROUND_DEADLINE_SECONDS = LATE_AFTER + BARGAIN_SECONDS + RESULT_SECONDS + 25
COIN_VALUE = 0.05
# Bots open with a proposal that gives their partner this many coins, and
# accept any proposal that gives them at least as many.
BOT_GIVES = 4
# The game's own end reasons. PsyNet's, such as "finished" when the time runs
# out and PLAYERS_LEFT, come first.
DEAL = "deal"
NO_SHOW = "no_show"


class Propose(LiveMessage):
    """Propose a split: the player keeps ``keep`` coins and the partner gets the rest."""

    type = "propose"
    keep: int

    def apply(self, game, state, player, now):
        if not 0 <= self.keep <= state["stake"]:
            raise Reject(f"Keep between 0 and {state['stake']} coins.")
        state["offers"][player] = self.keep
        state["n_proposals"] += 1


class Accept(LiveMessage):
    """Accept the partner's proposal. ``keep`` is what the partner keeps in
    the proposal the player saw, so a proposal that changed in the meantime
    isn't accepted by mistake."""

    type = "accept"
    keep: int

    def apply(self, game, state, player, now):
        partner = 1 - player
        if state["offers"][partner] != self.keep:
            raise Reject("Your partner has just changed their proposal.")
        # Each player's coins, in player order: the partner keeps what
        # they proposed, and the player gets the rest.
        deal = [0, 0]
        deal[partner] = self.keep
        deal[player] = state["stake"] - self.keep
        state["deal"] = deal
        state["deal_at"] = now


class Bargain(LiveGame):
    name = "bargaining"
    messages = [Propose, Accept]
    min_players = max_players = 2
    duration = BARGAIN_SECONDS
    # A player who hasn't opened the game by then, for example because they
    # closed their page as the pair formed, isn't coming, so the game starts
    # and ends at once, without a deal.
    ready_timeout = LATE_AFTER
    # A player away from the game for this long has left it, which ends it.
    away_timeout = LATE_AFTER

    def initial_state(self, players, settings):
        return {
            "stake": settings["stake"],
            # What each player keeps in their current proposal.
            "offers": [None, None],
            "n_proposals": 0,
            "deal": None,
            "deal_at": None,
            # The players who hadn't opened the game when it started.
            "no_shows": [],
        }

    def on_start(self, state):
        state["no_shows"] = self._absent(state, "no_show")

    def view(self, state, player):
        # Read again, as in outcome, for the final view of a game that
        # nobody opened. The page shows it only once the game has ended.
        return {
            "stake": state["stake"],
            "mine": state["offers"][player],
            "theirs": state["offers"][1 - player],
            "deal": None if state["deal"] is None else state["deal"][player],
            # Who didn't arrive, if anyone: "you" or "partner".
            "no_show": _you_or_partner(player, self._absent(state, "no_show")),
            # Who left the game for good, which ended it, if anyone. A player
            # whose page was only briefly away, as for a reload, hasn't.
            "left": _you_or_partner(player, self._absent(state, "left_game")),
        }

    def _absent(self, state, reason):
        """Return the players who didn't play the game for ``reason``."""
        return [
            player
            for player, absence in enumerate(self.absences(state))
            if absence == reason
        ]

    def is_over(self, state):
        return state["deal"] is not None or bool(state["no_shows"])

    def end_reason(self, state):
        return DEAL if state["deal"] is not None else NO_SHOW

    def outcome(self, state, reason):
        return {
            "deal": state["deal"],
            "deal_at": state["deal_at"],
            "n_proposals": state["n_proposals"],
            # Read again here, since a game that nobody opened ends without
            # starting.
            "no_shows": self._absent(state, "no_show"),
        }

    def answer(self, outcome, reason, player):
        deal = outcome["deal"]
        return {
            "deal": deal is not None,
            "coins": 0 if deal is None else deal[player],
            "arrived": player not in outcome["no_shows"],
            "partner_arrived": 1 - player not in outcome["no_shows"],
        }

    def performance_reward(self, outcome, reason, player):
        return self.answer(outcome, reason, player)["coins"] * COIN_VALUE

    def bot(self, view, player, now):
        if view["deal"] is not None:
            return None
        theirs = view["theirs"]
        if theirs is not None and view["stake"] - theirs >= BOT_GIVES:
            return Accept(keep=theirs)
        # Player 0 opens.
        if view["mine"] is None and player == 0:
            return Propose(keep=view["stake"] - BOT_GIVES)
        return None


def _player_round_row(trial):
    """Return a player's row of the export for one round. The game's columns
    come from the player's answer in the game's record, which PsyNet works
    out for a player who closed their page too, and are None if the player
    had no game, because their partner didn't reach it."""
    game = trial.live_game
    result = game.answer or dict.fromkeys(
        ["deal", "coins", "arrived", "partner_arrived"]
    )
    return {
        "pair_id": trial.sync_group_id,
        "participant_id": trial.participant_id,
        "trial_id": trial.id,
        "round": trial.position,
        # How the game ended: DEAL, NO_SHOW, or PsyNet's PLAYERS_LEFT,
        # "finished" when the time ran out or "not_joined" when neither
        # player opened it. None without a game.
        "end_reason": game.end_reason,
        # For a game that a player didn't open in time, arrived and
        # partner_arrived say who didn't.
        **result,
    }


def _you_or_partner(player, players):
    """Return ``"you"`` if ``player`` is one of ``players``, ``"partner"``
    if only their partner is, or None."""
    return "you" if player in players else "partner" if players else None


def coins_text(n):
    """Return ``n`` coins as text, such as "1 coin" or "3 coins"."""
    return f"{n} coin" if n == 1 else f"{n} coins"


def choose_stake():
    """Return the definition of a pair's round, with the coins they bargain over."""
    return {"stake": random.choice(STAKES)}


def bargaining_page(stake):
    return LiveGamePage(
        "bargain",
        tags.div(
            tags.div(
                tags.span(id="bargain-status"),
                tags.div(tags.div(id="bargain-time-left"), cls="bargain-clock"),
                cls="bargain-header",
            ),
            tags.div(
                tags.span(tags.span(cls="bargain-coin bargain-coin-you"), "Your coins"),
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
                        tags.strong(stake // 2, id="bargain-keep-value"),
                        f" of {stake} coins",
                        fr="bargain-keep",
                    ),
                    tags.input_(
                        type="range",
                        id="bargain-keep",
                        min=0,
                        max=stake,
                        value=stake // 2,
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
                        disabled=True,
                    ),
                    id="bargain-theirs-card",
                    cls="bargain-card",
                ),
                cls="bargain-cards",
            ),
            tags.div(id="bargain-deal", cls="bargain-deal", hidden=True),
            tags.p(id="bargain-rejection", cls="bargain-rejection"),
            id="bargain-game",
        ),
        show_result_for=RESULT_SECONDS,
        player_left_message="Your partner has left.",
        no_game_message="Your partner didn't arrive.",
        waiting_status="Waiting for your partner to open the game",
        module="/static/bargaining.js",
        css_links=["/static/bargaining.css"],
        time_estimate=BARGAIN_SECONDS,
    )


class BargainTrial(Trial):
    sync_group_type = "pair"
    live_game_class = Bargain
    time_estimate = BARGAIN_SECONDS + 10

    def show_trial(self, experiment, participant):
        return PlayLiveGame(
            group_type="pair",
            game_class=Bargain,
            page=bargaining_page(self.definition["stake"]),
            settings=self.definition,
            # A partner who hasn't arrived LATE_AFTER seconds after the pair
            # formed has probably closed their page, so they are failed,
            # which takes them out of the cohort too, and the next pairing
            # doesn't wait for them. The player waiting goes on to the game
            # page without a game.
            late_after=LATE_AFTER,
            late_action="fail",
            # So is a partner who reached the game but never opened it, or
            # left it for good, once the game's result is saved.
            absent_action="fail",
        )

    def coins(self):
        """Return the coins the player got from this round's deal."""
        return (self.answer or {}).get("coins", 0)

    def show_feedback(self, experiment, participant):
        # A player who didn't arrive, or left the game, has been failed, so
        # only their partner sees this page.
        reason = self.live_game.end_reason
        if self.answer is None or not self.answer["partner_arrived"]:
            text = "Your partner didn't arrive, so there was no game this round."
        elif reason == DEAL:
            mine = self.coins()
            text = (
                f"You made a deal: you get {coins_text(mine)} and your partner "
                f"gets {self.definition['stake'] - mine}."
            )
        elif reason == PLAYERS_LEFT:
            text = "Your partner left the game, so there was no deal."
        else:
            text = "You didn't reach a deal in time, so nobody was paid."
        return InfoPage(text, time_estimate=5)


pairing = Regrouper(
    group_type="pair",
    within="cohort",
    group_size=2,
    left_over="sit_out",
    deadline=ROUND_DEADLINE_SECONDS,
)


def cohort_of(participant):
    return participant.active_sync_groups.get("cohort")


def keep_playing(participant):
    cohort = cohort_of(participant)
    return (
        pairing.rounds_played(participant) < N_ROUNDS
        and cohort is not None
        and cohort.n_active_participants >= 2
    )


def round_status(participant):
    if participant.in_sync_group("pair"):
        return "paired"
    if pairing.sat_out(participant):
        return "sat_out"
    return "no_cohort"


def end_of_game(participant):
    """Return the last page, with the player's bonus."""
    return InfoPage(
        "That's the end of the game. Your bonus is "
        f"${participant.performance_reward:.2f}.",
        time_estimate=5,
    )


def get_timeline():
    return Timeline(
        InfoPage(
            "You will bargain live with other players, paired at random each round.",
            time_estimate=5,
        ),
        SimpleGrouper(
            group_type="cohort",
            initial_group_size=COHORT_SIZE,
            quorum=2,
            max_wait_time=300,
            # Players leave the cohort as they finish, so failing those left
            # below the quorum could fail the last players still playing.
            # Instead, keep_playing ends the rounds for them.
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
                            "paired": BargainTrial.cue(choose_stake),
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
        leave_group("cohort"),
        PageMaker(end_of_game, time_estimate=5),
    )


def _pair_row(group_round):
    """Return a pair's row of the export, with None for the game's columns
    if the pair had no game, because a player didn't reach it."""
    outcome = group_round.live_game_outcome
    return {
        "pair_id": group_round.sync_group_id,
        "stake": group_round.definition["stake"],
        "deal_at": None if outcome is None else outcome["deal_at"],
        "n_proposals": None if outcome is None else outcome["n_proposals"],
        # The players who didn't open the game in time, which then ended
        # at once, so 0 for a pair that bargained.
        "n_no_shows": None if outcome is None else len(outcome["no_shows"]),
    }


class Exp(psynet.experiment.Experiment):
    label = "Live bargaining demo"

    timeline = get_timeline()

    test_n_bots = COHORT_SIZE
    test_mode = "parallel"

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round and one per pair."""
        trials = BargainTrial.query.order_by(BargainTrial.id).all()
        pairs = SyncGroupRound.query.filter_by(module_id="game").order_by(
            SyncGroupRound.id
        )
        return {
            "player_round": [_player_round_row(t) for t in trials],
            "pair": [_pair_row(r) for r in pairs],
        }

    def test_check_bot(self, bot: Bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = BargainTrial.query.filter_by(participant_id=bot.id).all()
        assert len(trials) == N_ROUNDS
        for trial in trials:
            assert trial.answer["deal"], trial.answer
            stake = trial.definition["stake"]
            assert stake in STAKES
            assert trial.coins() in (BOT_GIVES, stake - BOT_GIVES)
            # The game's reward is recorded on the trial it was played in.
            assert trial.performance_reward == pytest.approx(trial.coins() * COIN_VALUE)
            outcome = trial.live_game.outcome
            assert sorted(outcome["deal"]) == [BOT_GIVES, stake - BOT_GIVES]
            assert trial.live_game.end_reason == DEAL
        expected = sum(t.coins() for t in trials) * COIN_VALUE
        assert bot.performance_reward == pytest.approx(expected)
        for pair in self.get_basic_data()["pair"]:
            assert pair["stake"] in STAKES and pair["deal_at"] is not None, pair

"""Live public goods game in groups of three that carries on when members leave.

In each of ``N_ROUNDS`` rounds, every member has ``ENDOWMENT`` tokens and
chooses how many to put in the group pot. Unlike the ``public_goods`` demo,
the choice is live: each member sees the others' contributions as they
change, and can change their own until the round's ``ROUND_SECONDS`` are up.
Then the pot is multiplied by ``MULTIPLIER`` and shared between the members,
and each token a member earns pays ``TOKEN_VALUE``.

Each round is one cued ``ContributionTrial`` per player, whose ``show_trial``
starts a live game for the team and shows the game page. The trial's answer
holds what the player put in and earned; the results page reads the team's
pot from the trial's ``live_game``. The export reads each player's round
from the trial's ``live_game.answer``, which PsyNet works out from the
game's outcome for a player who closed their page too.
"""

from typing import List

import pytest
from dominate import tags

import psynet.experiment
from psynet.bot import (
    Bot,
    BotDriver,
    advance_past_wait_pages,
    make_late_now,
    run_bots_to_completion,
)
from psynet.live_game import (
    LiveGame,
    LiveGamePage,
    LiveMessage,
    PlayLiveGame,
    Reject,
)
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Module, PageMaker, Timeline, conditional, for_loop
from psynet.trial.main import Trial

N_ROUNDS = 3
ENDOWMENT = 10
MULTIPLIER = 1.5
TOKEN_VALUE = 0.02
ROUND_SECONDS = 20
RESULTS_SECONDS = 10
# A member who hasn't reached the next round this long after the previous
# round's game ended is failed. The game page says when it
# ends, so this only has to cover reading the results.
LATE_AFTER = 15
GROUPING_WAIT = 20

#: What the game page needs to show the pot. The game page passes it to
#: static/public-goods.js.
RULES = {"endowment": ENDOWMENT, "multiplier": MULTIPLIER}


class Contribute(LiveMessage):
    """Set how many tokens the player puts in the pot."""

    type = "contribute"
    tokens: int

    def apply(self, game, state, player, now):
        if not 0 <= self.tokens <= ENDOWMENT:
            raise Reject(f"Put in between 0 and {ENDOWMENT} tokens.")
        state["contributions"][player] = self.tokens


class PublicGoods(LiveGame):
    name = "public_goods"
    messages = [Contribute]
    duration = ROUND_SECONDS

    def initial_state(self, players):
        # Each player's contribution, in player order.
        return {"contributions": [0 for player in players]}

    def view(self, state, player):
        # Contributions are public, so every player sees them all.
        return {"contributions": state["contributions"]}

    def outcome(self, state, reason):
        contributions = state["contributions"]
        pot = sum(contributions)
        share = MULTIPLIER * pot / len(contributions)
        return {
            "contributions": contributions,
            "pot": pot,
            "share": share,
            "payoffs": [ENDOWMENT - tokens + share for tokens in contributions],
        }

    def answer(self, outcome, reason, player):
        return {
            "contributed": outcome["contributions"][player],
            "earned": outcome["payoffs"][player],
        }

    def performance_reward(self, outcome, reason, player):
        return outcome["payoffs"][player] * TOKEN_VALUE

    def bot(self, view, player, now):
        tokens = bot_contribution(player)
        if view["contributions"][player] == tokens:
            return None
        return Contribute(tokens=tokens)


def bot_contribution(player):
    return player % 3 * 5


def contribution_page(round_number):
    return LiveGamePage(
        "contribution",
        tags.div(
            tags.div(
                tags.span(f"Round {round_number + 1} of {N_ROUNDS}", cls="pg-round"),
                tags.span(id="pg-status"),
                tags.div(tags.div(id="pg-time-left"), cls="pg-clock"),
                cls="pg-header",
            ),
            tags.p(
                f"Drag the slider to choose how many of your {ENDOWMENT} "
                "tokens to put in the group pot. You can change your mind "
                "until the time is up.",
                id="pg-instructions",
            ),
            tags.div(id="pg-rows", cls="pg-rows"),
            tags.input_(
                type="range",
                id="pg-tokens",
                min=0,
                max=ENDOWMENT,
                value=0,
                aria_label="Your contribution",
            ),
            tags.div(
                tags.div(id="pg-pot", cls="pg-pot"),
                tags.p(id="pg-earn", cls="pg-earn"),
                cls="pg-summary",
            ),
            tags.p(id="pg-rejection", cls="pg-rejection"),
            id="pg-game",
        ),
        player_left_message="A player has left the game.",
        js_page_modules=["/static/public-goods.js"],
        js_vars={"public_goods_rules": RULES},
        css_links=["/static/public-goods.css"],
        time_estimate=ROUND_SECONDS,
    )


class ContributionTrial(Trial):
    sync_group_type = "team"
    live_game_class = PublicGoods
    time_estimate = ROUND_SECONDS + RESULTS_SECONDS

    def show_trial(self, experiment, participant):
        return PlayLiveGame(
            group_type="team",
            game_class=PublicGoods,
            page=contribution_page(self.sync_group_round),
            waiting_message="Waiting for the other players…",
            # A player who closes their page is failed, and the others carry
            # on without them.
            late_after=LATE_AFTER,
            late_action="fail",
        )

    def show_feedback(self, experiment, participant):
        answer = self.answer
        if answer is None:
            # The experimenter removed the player from their team during the
            # round, before its game started.
            return InfoPage("Your group couldn't start this round.", time_estimate=5)
        team = self.live_game.outcome
        return InfoPage(
            f"The group put {team['pot']} tokens in the pot, which was "
            f"multiplied and shared between {len(team['contributions'])} "
            f"players: {team['share']:g} tokens each. You put in "
            f"{answer['contributed']}, so you earned {answer['earned']:g} tokens "
            "this round.",
            time_estimate=RESULTS_SECONDS,
        )


def removed_from_team(participant):
    """Return whether the experimenter has removed the player from their team on the dashboard.

    Nothing else leaves a player without a team and still playing: a late
    player is failed, and so is the last player of a team that ends.
    """
    return not participant.in_sync_group("team")


def bonus_text(participant):
    return f"Your bonus is ${participant.performance_reward:.2f}."


def game_over(participant):
    return InfoPage(f"The game is over. {bonus_text(participant)}", time_estimate=5)


def removed_page(participant):
    return InfoPage(
        f"You were removed from the game. {bonus_text(participant)}",
        time_estimate=5,
    )


def get_timeline():
    return Timeline(
        InfoPage(
            f"You will play {N_ROUNDS} rounds of a game with two other players. "
            f"Each round you get {ENDOWMENT} tokens and choose how many to put in "
            f"a group pot, seeing the others' choices as they make them. The pot "
            f"is multiplied by {MULTIPLIER} and shared equally between the "
            f"players. Each token you earn pays ${TOKEN_VALUE:.2f}.",
            time_estimate=15,
        ),
        SimpleGrouper(
            group_type="team",
            initial_group_size=3,
            quorum=2,
            # Two players carry on without a third; a player left alone is
            # failed, as is one for whom no group forms (max_wait_action
            # defaults to "fail").
            below_quorum="fail",
            max_wait_time=GROUPING_WAIT,
            waiting_message="Waiting for two other players to join…",
        ),
        Module(
            "game",
            for_loop(
                label="rounds",
                iterate_over=range(N_ROUNDS),
                logic=lambda i: ContributionTrial.cue(round=i),
                time_estimate_per_iteration=ContributionTrial.time_estimate,
                # Checked before each round.
                stop_if=removed_from_team,
            ),
        ),
        conditional(
            "game_over",
            removed_from_team,
            PageMaker(removed_page, time_estimate=5),
            PageMaker(game_over, time_estimate=5),
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Live public goods game demo"

    timeline = get_timeline()

    test_n_bots = 3
    test_mode = "serial"

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round."""
        trials = ContributionTrial.query.order_by(ContributionTrial.id).all()
        rows = []
        for t in trials:
            team = (t.group_round and t.group_round.live_game_outcome) or {}
            answer = (t.live_game and t.live_game.answer) or {}
            rows.append(
                {
                    "team_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # Counted from 0, as in the other demos' exports.
                    "round": t.sync_group_round,
                    "contributed": answer.get("contributed"),
                    # What the team put in the pot, before it was multiplied.
                    "pot": team.get("pot"),
                    # Each player's part of the multiplied pot.
                    "share": team.get("share"),
                    "earned": answer.get("earned"),
                }
            )
        return {"player_round": rows}

    def test_serial_run_bots(self, bots: List[BotDriver]):
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots)
        # Each game page moves on once its round's game ends.
        for bot in bots:
            bot.take_page()
        assert all("The group put 15 tokens" in b.current_page_text for b in bots)

        # bots[2] goes quiet on its results page, so the next round's
        # barrier fails them as late, and the other two carry on.
        for bot in bots[:2]:
            bot.take_page()
        bots[2].allow_failure()
        make_late_now(bots, "public_goods")
        assert bots[2].failed
        run_bots_to_completion(bots[:2], timeout=N_ROUNDS * (ROUND_SECONDS + 30))

        rows = self.get_basic_data()["player_round"]

        def pots(bot):
            return [
                (r["round"], r["pot"]) for r in rows if r["participant_id"] == bot.id
            ]

        # Two players put in 0 and 5 tokens after the third was failed.
        assert pots(bots[0]) == [(0, 15), (1, 5), (2, 5)], rows
        assert pots(bots[2]) == [(0, 15)], rows

    def test_check_bot(self, bot: Bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = ContributionTrial.query.filter_by(participant_id=bot.id).all()
        if not bot.failed:
            assert len(trials) == N_ROUNDS, [t.answer for t in trials]
        for trial in trials:
            game = trial.live_game
            player = game.player
            assert trial.answer["contributed"] == bot_contribution(player)
            outcome = game.outcome
            contributions = outcome["contributions"]
            assert contributions == [
                bot_contribution(player) for player in range(len(contributions))
            ]
            assert outcome["pot"] == sum(contributions)
            # The game's reward is recorded on the trial it was played in.
            reward = trial.answer["earned"] * TOKEN_VALUE
            assert trial.performance_reward == pytest.approx(reward)
        expected = sum(t.answer["earned"] * TOKEN_VALUE for t in trials)
        assert bot.performance_reward == pytest.approx(expected)
        rows = [
            row
            for row in self.get_basic_data()["player_round"]
            if row["participant_id"] == bot.id
        ]
        assert [
            (row["round"], row["contributed"], row["pot"], row["earned"])
            for row in rows
        ] == [
            (i, t.answer["contributed"], t.live_game.outcome["pot"], t.answer["earned"])
            for i, t in enumerate(sorted(trials, key=lambda t: t.id))
        ]

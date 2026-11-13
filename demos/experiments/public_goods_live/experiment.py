"""Live public goods game in groups of three that carries on when members leave.

In each of ``N_ROUNDS`` rounds, every member has ``ENDOWMENT`` tokens and
chooses how many to put in the group pot. Unlike the ``public_goods`` demo,
the choice is live: each member sees the others' contributions as they
change, and can change their own until the round's ``ROUND_SECONDS`` are up.
Then the pot is multiplied by ``MULTIPLIER`` and shared between the members,
and each token a member earns pays ``TOKEN_VALUE``.

Each round is one cued ``ContributionTrial`` per player, whose ``show_trial``
starts a live session for the team and shows the game page. The game page's
answer is the session's outcome, which the results page reads.
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
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Module, PageMaker, Timeline, conditional, for_loop, join
from psynet.trial.main import Trial

GROUP = "team"
N_ROUNDS = 3
ENDOWMENT = 10
MULTIPLIER = 1.5
TOKEN_VALUE = 0.02
ROUND_SECONDS = 20
RESULTS_SECONDS = 10
# A member who hasn't reached the next round this long after the previous
# round's game ended is taken out of the team. The game page says when it
# ends, so this only has to cover reading the results.
LATE_AFTER = 15
GROUPING_WAIT = 20


class Contribute(LiveMessage):
    """Set how many tokens the player puts in the pot."""

    type = "contribute"
    tokens: int

    def apply(self, game, state, player_id, now):
        if not 0 <= self.tokens <= state["endowment"]:
            raise Reject(f"Put in between 0 and {state['endowment']} tokens.")
        state["contributions"][player_id] = self.tokens
        state["changes"][player_id] += 1


class PublicGoods(LiveGame):
    channel = "public_goods"
    messages = [Contribute]
    duration = ROUND_SECONDS

    def initial_state(self, players, settings):
        return {
            "endowment": settings["endowment"],
            "multiplier": settings["multiplier"],
            "contributions": {player: 0 for player in players},
            "changes": {player: 0 for player in players},
        }

    def view(self, state, player_id):
        return {
            "endowment": state["endowment"],
            "multiplier": state["multiplier"],
            "mine": state["contributions"][player_id],
            "changed": state["changes"][player_id] > 0,
            # The other players in the order they joined.
            "others": [
                state["contributions"][player]
                for player in state["live_session"]["players"]
                if player != player_id
            ],
        }

    def outcome(self, state, reason):
        contributions = state["contributions"]
        pot = sum(contributions.values())
        share = state["multiplier"] * pot / len(contributions)
        return {
            "contributions": contributions,
            "pot": pot,
            "share": share,
            "payoffs": {
                player: state["endowment"] - tokens + share
                for player, tokens in contributions.items()
            },
        }

    def answer(self, outcome, reason, player_id):
        return {
            "contributed": outcome["contributions"][player_id],
            "earned": outcome["payoffs"][player_id],
            "pot": outcome["pot"],
            "share": outcome["share"],
            "team_size": len(outcome["contributions"]),
        }

    def record_round(self, group_round, outcome, reason):
        group_round.var.pot = outcome["pot"]
        group_round.var.contributions = outcome["contributions"]

    def performance_reward(self, outcome, reason, player_id):
        return outcome["payoffs"][player_id] * TOKEN_VALUE

    def bot(self, view, player_id, now):
        if view["changed"]:
            return None
        return Contribute(tokens=bot_contribution(player_id))


def bot_contribution(player_id):
    return int(player_id) % 3 * 5


def contribution_page(round_number):
    return ModularPage(
        "contribution",
        Prompt(
            tags.div(
                tags.div(
                    tags.span(
                        f"Round {round_number + 1} of {N_ROUNDS}", cls="pg-round"
                    ),
                    tags.span("Joining the game…", id="pg-status"),
                    tags.div(tags.div(id="pg-time-left"), cls="pg-clock"),
                    cls="pg-header",
                ),
                tags.p(
                    f"Drag the slider to choose how many of your {ENDOWMENT} "
                    "tokens to put in the group pot. You can change your mind "
                    "until the time is up."
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
            )
        ),
        LiveSessionControl(
            "public_goods", player_left_message="A player has left the game."
        ),
        js_page_modules=["/static/public-goods.js"],
        css_links=["/static/public-goods.css"],
        time_estimate=ROUND_SECONDS,
    )


class ContributionTrial(Trial):
    sync_group_type = GROUP
    time_estimate = ROUND_SECONDS + RESULTS_SECONDS

    def show_trial(self, experiment, participant):
        return join(
            LiveGameBarrier(
                id_="public_goods",
                group_type=GROUP,
                game_type=PublicGoods,
                settings={"endowment": ENDOWMENT, "multiplier": MULTIPLIER},
                waiting_message="Waiting for the other players…",
                late_after=LATE_AFTER,
                late_action="leave_group",
            ),
            contribution_page(self.sync_group_round),
        )

    def show_feedback(self, experiment, participant):
        answer = self.answer
        if answer is None:
            return InfoPage("Your group couldn't start this round.", time_estimate=5)
        return InfoPage(
            f"The group put {answer['pot']} tokens in the pot, which was "
            f"multiplied and shared between {answer['team_size']} "
            f"players: {answer['share']:g} tokens each. You put in "
            f"{answer['contributed']}, so you earned {answer['earned']:g} tokens "
            "this round.",
            time_estimate=RESULTS_SECONDS,
        )


def left_team(participant):
    return not participant.in_sync_group(GROUP)


def bonus_text(participant):
    return f"Your bonus is ${participant.performance_reward:.2f}."


def game_over(participant):
    return InfoPage(f"The game is over. {bonus_text(participant)}", time_estimate=5)


ENDED_EARLY_TEXTS = {
    "no_group_formed": "We couldn't find two other players for you.",
    "late": "You were away for too long, so the game ended early for you.",
    "group_dissolved": "Too few players stayed, so the game ended early.",
    "removed_by_experimenter": "You were removed from the game.",
}


def game_ended_early(participant):
    text = ENDED_EARLY_TEXTS[participant.sync_group_removal_reason(GROUP)]
    return InfoPage(f"{text} {bonus_text(participant)}", time_estimate=5)


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
            GROUP,
            initial_group_size=3,
            quorum=2,
            below_quorum="continue_without_group",
            max_wait_time=GROUPING_WAIT,
            max_wait_action="continue_without_group",
            waiting_message="Waiting for two other players to join…",
        ),
        Module(
            "game",
            for_loop(
                label="rounds",
                iterate_over=range(N_ROUNDS),
                logic=lambda i: ContributionTrial.cue(round=i),
                time_estimate_per_iteration=ContributionTrial.time_estimate,
                stop_if=left_team,
            ),
        ),
        conditional(
            "game_over",
            left_team,
            PageMaker(game_ended_early, time_estimate=5),
            PageMaker(game_over, time_estimate=5),
        ),
    )


class Exp(psynet.experiment.Experiment):
    label = "Live public goods game demo"

    timeline = get_timeline()

    test_n_bots = 3
    test_mode = "parallel"

    def test_check_bot(self, bot: Bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = ContributionTrial.query.filter_by(participant_id=bot.id).all()
        assert len(trials) == N_ROUNDS, (
            bot.id,
            bot.sync_group_removal_reason(GROUP),
            [t.answer for t in trials],
        )
        for trial in trials:
            assert trial.answer["contributed"] == bot_contribution(str(bot.id))
            contributions = trial.group_round.var.contributions
            assert contributions == {
                player: bot_contribution(player) for player in contributions
            }
            assert trial.group_round.var.pot == sum(contributions.values())
        expected = sum(t.answer["earned"] * TOKEN_VALUE for t in trials)
        assert abs(bot.performance_reward - expected) < 1e-9

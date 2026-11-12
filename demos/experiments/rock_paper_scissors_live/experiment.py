"""Rock, paper, scissors as a live session.

Pairs of participants play two games of rock, paper, scissors, each of five
rounds on one page. Each round's result appears for both players as soon as
they have both chosen.

Each game is one cued ``RockPaperScissorsTrial`` per player. The trial starts
the pair's session and shows the game page, the game's outcome is the trial's
answer, and the trial's feedback page shows the final score from it. Each
round won pays a bonus, which is larger in the second game: the amount comes
from the trial's definition, which the trial passes to the game as the
session's settings.
"""

import random
from typing import Literal

import pytest
from dallinger.realtime import Reject
from dominate import tags

import psynet.experiment
from psynet.live_session import (
    LiveMessage,
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
    live_session_id,
    live_session_result,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Module, Timeline, for_loop, join
from psynet.trial.main import Trial

GROUP = "pair"

N_ROUNDS = 5
ACTIONS = ["rock", "paper", "scissors"]
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
# What a round won pays, in dollars, in each of the pair's games.
BONUSES_PER_WIN = [0.05, 0.10]
# How long a player waits for their partner to start a game, in seconds.
PARTNER_WAIT_SECONDS = 60


def round_result(mine, theirs):
    if mine == theirs:
        return "draw"
    return "win" if BEATS[mine] == theirs else "loss"


def partner_of(player_id, players):
    (partner,) = [player for player in players if player != player_id]
    return partner


class Choose(LiveMessage):
    """A player's action in one round."""

    type = "choose"
    round: int
    action: Literal["rock", "paper", "scissors"]

    def apply(self, game, state, player_id, now):
        # The round number stops a click on a page that hasn't caught up yet,
        # such as one in another tab, from counting for the next round.
        if self.round != len(state["rounds"]) + 1:
            raise Reject("That round is over.")
        if state["choices"][player_id] is not None:
            raise Reject("You've already chosen this round.")
        choices = state["choices"]
        choices[player_id] = self.action
        if None not in choices.values():
            partner = partner_of(player_id, choices)
            result = round_result(choices[player_id], choices[partner])
            if result == "win":
                state["wins"][player_id] += 1
            elif result == "loss":
                state["wins"][partner] += 1
            state["rounds"].append(choices)
            state["choices"] = {player: None for player in choices}


class RockPaperScissors(LiveSession):
    """Five rounds of rock, paper, scissors between two players.

    The state holds each player's choice in the current round, ``None`` until
    they choose, the choices of every round played so far, the number of
    rounds each player has won, and what a round won pays, which comes from
    the session's settings. A player's view says whether their partner has
    chosen in the current round, and shows the partner's choice only once the
    round is over.
    """

    channel = "rock_paper_scissors_live"
    messages = [Choose]
    # A limit on the whole game, counted from when the pair left the
    # initializer. Five rounds take a minute or two, so a game ends within five
    # minutes even if a player leaves it.
    max_duration = 300

    def initial_state(self, players, settings):
        return {
            "choices": {player: None for player in players},
            "rounds": [],
            "wins": {player: 0 for player in players},
            "bonus_per_win": settings["bonus_per_win"],
        }

    def view(self, state, player_id):
        partner = partner_of(player_id, state["choices"])
        results = [
            {
                "mine": choices[player_id],
                "theirs": choices[partner],
                "result": round_result(choices[player_id], choices[partner]),
            }
            for choices in state["rounds"]
        ]
        return {
            "round": len(state["rounds"]) + 1,
            "n_rounds": N_ROUNDS,
            "chosen": state["choices"][player_id] is not None,
            "partner_chosen": state["choices"][partner] is not None,
            "results": results,
            "wins": state["wins"][player_id],
            "partner_wins": state["wins"][partner],
        }

    def is_over(self, state):
        return len(state["rounds"]) == N_ROUNDS

    def outcome(self, state, reason):
        return {
            "reason": reason,
            "rounds": state["rounds"],
            "wins": state["wins"],
            "bonus_per_win": state["bonus_per_win"],
        }

    def bonus(self, outcome, reason, player_id):
        return outcome["bonus_per_win"] * outcome["wins"][player_id]

    def bot(self, view, player_id, now):
        if view["chosen"]:
            return None
        return Choose(round=view["round"], action=random.choice(ACTIONS))


def show_result(participant, outcome):
    if outcome is None:
        return InfoPage("Your group couldn't play the game.", time_estimate=5)
    if not outcome["rounds"]:
        return InfoPage(
            "The game ended before any rounds were played.", time_estimate=5
        )
    player_id = str(participant.id)
    partner = partner_of(player_id, outcome["wins"])
    wins = outcome["wins"][player_id]
    partner_wins = outcome["wins"][partner]
    if outcome["reason"] != "finished":
        summary = "The game ended early."
    elif wins > partner_wins:
        summary = "You won the game!"
    elif wins < partner_wins:
        summary = "Your partner won the game."
    else:
        summary = "The game was a draw."
    return InfoPage(
        tags.div(
            tags.h2(summary),
            tags.p(
                f"You won {wins} of the {len(outcome['rounds'])} rounds played, "
                f"and your partner won {partner_wins}."
            ),
            tags.p(
                f"Your bonus for this game is ${outcome['bonus_per_win'] * wins:.2f}."
            ),
        ),
        time_estimate=5,
    )


class RockPaperScissorsTrial(Trial):
    """One game between the two participants of a pair. The trial's definition
    says what a round won pays, and the trial's answer is the game's outcome."""

    sync_group_type = GROUP
    # A participant whose pair has ended still gets a trial, whose game page
    # has no session.
    sync_group_optional = True
    time_estimate = 65

    def show_trial(self, experiment, participant):
        return join(
            # Starting the session closes the pair's round, as releasing any
            # group barrier in a cued trial does.
            LiveSessionInitializer(
                id_="rock_paper_scissors",
                group_type=GROUP,
                game_type=RockPaperScissors,
                settings=self.definition,
                # A player whose partner doesn't arrive leaves the pair, and
                # goes on to the game page without a session.
                max_wait_time=PARTNER_WAIT_SECONDS,
                max_wait_action="leave_group",
            ),
            ModularPage(
                "rock_paper_scissors",
                Prompt(
                    tags.div(
                        tags.p(
                            f"Game {self.position + 1} of {len(BONUSES_PER_WIN)}. "
                            "Each round you win pays a bonus of "
                            f"${self.definition['bonus_per_win']:.2f}.",
                            id="rps-stakes",
                        ),
                        tags.p(id="rps-last"),
                        tags.h4(id="rps-status"),
                        tags.p(id="rps-partner"),
                        tags.div(
                            [
                                tags.button(
                                    action.capitalize(),
                                    type="button",
                                    cls="btn btn-primary btn-lg rps-action",
                                    data_action=action,
                                    disabled=True,
                                )
                                for action in ACTIONS
                            ],
                            id="rps-actions",
                        ),
                        tags.p(id="rps-rejection"),
                        tags.p(id="rps-score"),
                        tags.ol(id="rps-results"),
                        id="rps-game",
                    )
                ),
                LiveSessionControl(
                    "rock_paper_scissors",
                    player_left_message=(
                        "Your partner has left. The game will end in a few "
                        "minutes unless they come back."
                    ),
                ),
                js_page_modules=["/static/rock-paper-scissors.js"],
                css_links=["/static/rock-paper-scissors.css"],
                time_estimate=60,
            ),
        )

    def show_feedback(self, experiment, participant):
        return show_result(participant, self.answer)


class Exp(psynet.experiment.Experiment):
    label = "Rock, paper, scissors live session demo"
    test_n_bots = 2
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage(
            f"You'll play {len(BONUSES_PER_WIN)} games of rock, paper, scissors "
            f"against another participant. Each game has {N_ROUNDS} rounds, "
            "and you earn a bonus for each round you win. First, we'll find "
            "you a partner.",
            time_estimate=5,
        ),
        SimpleGrouper(
            group_type=GROUP,
            initial_group_size=2,
            waiting_message="Waiting for another participant to join you",
            # A participant who waits longer than this leaves the experiment.
            max_wait_time=300,
            # A participant whose partner leaves the pair goes on without it.
            below_quorum="continue_without_group",
        ),
        Module(
            "games",
            for_loop(
                label="games",
                iterate_over=range(len(BONUSES_PER_WIN)),
                # The pair stays together, so the loop value is the round,
                # and both players' trials get the round's definition.
                logic=lambda game: RockPaperScissorsTrial.cue(
                    {"bonus_per_win": BONUSES_PER_WIN[game]}, round=game
                ),
                time_estimate_per_iteration=RockPaperScissorsTrial.time_estimate,
            ),
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = sorted(bot.alive_trials, key=lambda trial: trial.id)
        assert [trial.definition["bonus_per_win"] for trial in trials] == (
            BONUSES_PER_WIN
        )
        # The bot's latest session is its second game.
        result = live_session_result(live_session_id(bot, "rock_paper_scissors"))
        assert result.status == "ended", result.error
        assert result.end_reason == "finished"
        assert trials[-1].answer == result.outcome
        me = str(bot.id)
        reward = 0
        for trial in trials:
            outcome = trial.answer
            rounds = outcome["rounds"]
            assert len(rounds) == N_ROUNDS
            partner = partner_of(me, rounds[0])
            wins = sum(
                round_result(choices[me], choices[partner]) == "win"
                for choices in rounds
            )
            assert outcome["wins"][me] == wins
            # Each game pays what its trial's definition says.
            assert outcome["bonus_per_win"] == trial.definition["bonus_per_win"]
            reward += outcome["bonus_per_win"] * wins
        assert bot.performance_reward == pytest.approx(reward)

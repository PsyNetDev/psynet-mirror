"""Rock, paper, scissors as a live game.

Pairs of participants play two games of rock, paper, scissors, of five and
then three throws, each game on one page. Each throw's result appears for both
players as soon as they have both chosen.

Each game is one cued ``RockPaperScissorsTrial`` per player. The trial's
definition says how many throws the game has and what a throw won pays. The
trial starts the pair's game, with the number of throws as its settings,
and shows the game page. The game's ``answer`` gives each player their own
part of the outcome, which is the trial's answer: the trial scores it as the
throws the player won and pays the reward for them, and its feedback page
shows the final score. The whole pair's outcome is on the trial's
``group_round``.

A player whose partner leaves plays no more games; see ``README.md``.
"""

import random
from typing import Literal, get_args

import pytest
from dominate import tags

import psynet.experiment
from psynet.live_game import (
    LiveGame,
    LiveGameControl,
    LiveMessage,
    PlayLiveGame,
    Reject,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Module, PageMaker, Timeline, conditional, for_loop
from psynet.trial.main import Trial

Action = Literal["rock", "paper", "scissors"]
ACTIONS = list(get_args(Action))
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
# Each of the pair's games: how many throws it has, and what a throw won pays,
# in dollars.
GAMES = [
    {"throws": 5, "reward_per_win": 0.05},
    {"throws": 3, "reward_per_win": 0.10},
]
# Seconds a player has to read a game's result before the page moves on.
RESULT_SECONDS = 30
# Seconds a partner can keep the other waiting for the next game, besides the
# result page, whose time limit the wait allows for.
LATE_AFTER = 20


def result_for(player, choices):
    """Return how a throw went for ``player``, 0 or 1, from both players'
    choices: ``"win"``, ``"loss"`` or ``"draw"``."""
    mine, theirs = choices[player], choices[1 - player]
    if mine == theirs:
        return "draw"
    return "win" if BEATS[mine] == theirs else "loss"


def throws_seen_by(player, throws):
    """The throws played so far, as ``player`` sees them: their choice, their
    partner's, and the result for them."""
    return [
        {
            "mine": choices[player],
            "theirs": choices[1 - player],
            "result": result_for(player, choices),
        }
        for choices in throws
    ]


def count(results, result):
    """Return how many of ``results``, from ``throws_seen_by``, have
    ``result``, such as ``"win"``."""
    return sum(played["result"] == result for played in results)


class Choose(LiveMessage):
    """A player's action in one throw."""

    type = "choose"
    throw: int
    action: Action

    def apply(self, game, state, player, now):
        # The throw number stops a click on a page that hasn't caught up yet,
        # such as one in another tab, from counting for the next throw.
        if self.throw != len(state["throws"]) + 1:
            raise Reject("That isn't the current throw.")
        if state["choices"][player] is not None:
            raise Reject("You've already chosen this throw.")
        state["choices"][player] = self.action
        if None not in state["choices"]:
            state["throws"].append(state["choices"])
            state["choices"] = [None, None]


class RockPaperScissors(LiveGame):
    """A game of rock, paper, scissors between two players, 0 and 1.

    The state holds the number of throws, from the game's settings, each
    player's choice in the current throw, ``None`` until they choose, and
    both players' choices in each throw played so far. A player's view says
    whether their partner has chosen in the current throw, and shows the
    partner's choice only once the throw is over.
    """

    name = "rock_paper_scissors"
    messages = [Choose]
    min_players = max_players = 2
    # A player whose partner closes the page for good isn't left waiting:
    # the game ends 30 seconds later, which allows for a reload.
    away_timeout = 30
    # A game takes a minute or two, so this ends it within five minutes even
    # if both players stop choosing.
    timeout = 300

    def initial_state(self, players, settings):
        return {
            "n_throws": settings["throws"],
            "choices": [None, None],
            "throws": [],
        }

    def view(self, state, player):
        results = throws_seen_by(player, state["throws"])
        return {
            "throw": len(state["throws"]) + 1,
            "n_throws": state["n_throws"],
            "chosen": state["choices"][player] is not None,
            "partner_chosen": state["choices"][1 - player] is not None,
            "results": results,
            "wins": count(results, "win"),
            "partner_wins": count(results, "loss"),
        }

    def is_over(self, state):
        return len(state["throws"]) == state["n_throws"]

    def outcome(self, state, reason):
        return {"throws": state["throws"]}

    def answer(self, outcome, reason, player):
        """The player's own part of the outcome: their throws, each with both
        choices and the result for them, the throws each player won, and
        whether the game was played to the end."""
        results = throws_seen_by(player, outcome["throws"])
        return {
            "finished": reason == "finished",
            "throws": results,
            "wins": count(results, "win"),
            "partner_wins": count(results, "loss"),
        }

    def bot(self, view, player, now):
        if view["chosen"]:
            return None
        return Choose(throw=view["throw"], action=random.choice(ACTIONS))


def show_result(answer, reward):
    """The feedback page for a game whose answer for the player is
    ``answer``, for which they were paid ``reward``."""
    if not answer["throws"]:
        return InfoPage(
            "The game ended before any throws were played.",
            time_estimate=5,
            time_limit=RESULT_SECONDS,
        )
    wins = answer["wins"]
    partner_wins = answer["partner_wins"]
    if not answer["finished"]:
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
                f"You won {wins} of the {len(answer['throws'])} throws played, "
                f"and your partner won {partner_wins}."
            ),
            tags.p(f"Your bonus for this game is ${reward:.2f}."),
        ),
        time_estimate=5,
        time_limit=RESULT_SECONDS,
    )


class RockPaperScissorsTrial(Trial):
    """One game between the two participants of a pair. The trial's definition
    says which of the pair's games it is, how many throws it has and what a
    throw won pays, and the trial's answer is the player's part of the game's
    outcome."""

    sync_group_type = "pair"
    time_estimate = 65

    def show_trial(self, experiment, participant):
        game = self.definition
        # PlayLiveGame waits for the pair, starts their game and shows the
        # game page. Starting the game closes the pair's round, as releasing
        # any group barrier in a cued trial does.
        return PlayLiveGame(
            group_type="pair",
            game_class=RockPaperScissors,
            settings={"throws": game["throws"]},
            # A partner who hasn't arrived LATE_AFTER seconds after their
            # result page ran out leaves the pair, and the player waiting goes
            # on to the game page without a game.
            late_after=LATE_AFTER,
            late_action="leave_group",
            page=ModularPage(
                "rock_paper_scissors",
                Prompt(
                    tags.div(
                        tags.p(
                            f"Game {game['number']} of {len(GAMES)}, of "
                            f"{game['throws']} throws. Each throw you win pays "
                            f"a bonus of ${game['reward_per_win']:.2f}.",
                            id="rps-stakes",
                        ),
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
                        # PsyNet hides it on a page without a game.
                        data_live_game=True,
                    )
                ),
                LiveGameControl(
                    player_left_message=(
                        "Your partner has left the game. If they don't come back "
                        f"within {RockPaperScissors.away_timeout} seconds, it will end."
                    ),
                    no_game_message=("This game can't be played without your partner."),
                    waiting_status="Waiting for your partner to open the game",
                ),
                js_page_modules=["/static/rock-paper-scissors.js"],
                css_links=["/static/rock-paper-scissors.css"],
                time_estimate=60,
            ),
        )

    def score_answer(self, answer, definition):
        """Return the number of throws the player won."""
        if answer is None:
            # The pair didn't start a game.
            return 0
        return answer["wins"]

    def compute_performance_reward(self, score):
        return score * self.definition["reward_per_win"]

    def gives_feedback(self, experiment, participant):
        return self.answer is not None

    def show_feedback(self, experiment, participant):
        return show_result(self.answer, self.performance_reward)


def left_pair(participant):
    return not participant.in_sync_group("pair")


# Why a participant isn't in a pair, as sync_group_removal_reason returns it.
NO_PARTNER_TEXTS = {
    "late": "You didn't come back in time for the next game.",
    "group_dissolved": "Your partner has left, so there are no more games.",
    "removed_by_experimenter": "You were removed from the game.",
}


def no_more_games(participant):
    text = NO_PARTNER_TEXTS[participant.sync_group_removal_reason("pair")]
    return InfoPage(
        f"{text} Your bonus is ${participant.performance_reward:.2f}.",
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Rock, paper, scissors live game demo"
    test_n_bots = 2
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage(
            f"You'll play {len(GAMES)} games of rock, paper, scissors against "
            "another participant, and you earn a bonus for each throw you "
            "win. First, we'll find you a partner.",
            time_estimate=5,
        ),
        SimpleGrouper(
            group_type="pair",
            initial_group_size=2,
            waiting_message="Waiting for another participant to join you",
            # A participant who waits longer than this without a partner
            # fails, and goes to the end of the experiment.
            max_wait_time=300,
            # A participant whose partner leaves the pair goes on without it.
            below_quorum="continue_without_group",
        ),
        Module(
            "games",
            for_loop(
                label="games",
                iterate_over=range(len(GAMES)),
                # The pair stays together, so the loop value is the round,
                # and both players' trials get the round's definition.
                logic=lambda game: RockPaperScissorsTrial.cue(
                    {"number": game + 1, **GAMES[game]}, round=game
                ),
                time_estimate_per_iteration=RockPaperScissorsTrial.time_estimate,
                # Checked before each game: a participant who is no longer in
                # a pair plays no more of them.
                stop_if=left_pair,
            ),
        ),
        conditional(
            "no_more_games",
            left_pair,
            PageMaker(no_more_games, time_estimate=5),
        ),
    )

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        trials = sorted(bot.alive_trials, key=lambda trial: trial.id)
        assert [trial.definition for trial in trials] == [
            {"number": 1, "throws": 5, "reward_per_win": 0.05},
            {"number": 2, "throws": 3, "reward_per_win": 0.10},
        ]
        # The bot's latest game is its second.
        game = bot.live_games["rock_paper_scissors"]
        assert game.finished, game.error
        assert trials[-1].live_game == game
        reward = 0
        for trial in trials:
            throws = trial.answer["throws"]
            # Each game has the number of throws its trial's definition says.
            assert len(throws) == trial.definition["throws"]
            wins = sum(played["result"] == "win" for played in throws)
            assert trial.score == trial.answer["wins"] == wins
            # The trial pays what its definition says for each throw won.
            trial_reward = wins * trial.definition["reward_per_win"]
            assert trial.performance_reward == pytest.approx(trial_reward)
            reward += trial_reward
        assert bot.performance_reward == pytest.approx(reward)

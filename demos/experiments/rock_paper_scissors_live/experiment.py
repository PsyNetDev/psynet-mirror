"""Rock, paper, scissors as a live session.

Pairs of participants play two games of rock, paper, scissors, of five and
then three rounds, each game on one page. Each round's result appears for both
players as soon as they have both chosen.

Each game is one cued ``RockPaperScissorsTrial`` per player. The trial's
definition says how many rounds the game has and what a round won pays. The
trial starts the pair's session, with the number of rounds as its settings,
and shows the game page. The game's ``answer`` gives each player their own
part of the outcome, which is the trial's answer: the trial scores it as the
rounds the player won and pays the reward for them, and its feedback page
shows the final score. The whole pair's outcome is on the trial's
``group_round``.

A player whose partner leaves plays no more games; see ``README.md``.
"""

import random
from typing import Literal, get_args

import pytest
from dallinger.realtime import Reject
from dominate import tags

import psynet.experiment
from psynet.live_game import (
    LiveGame,
    LiveGameControl,
    LiveMessage,
    PlayLiveGame,
    live_game_id,
    live_game_result,
)
from psynet.modular_page import ModularPage, Prompt
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import Module, PageMaker, Timeline, conditional, for_loop
from psynet.trial.main import Trial

Action = Literal["rock", "paper", "scissors"]
ACTIONS = list(get_args(Action))
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
# Each of the pair's games: how many rounds it has, and what a round won pays,
# in dollars.
GAMES = [
    {"rounds": 5, "reward_per_win": 0.05},
    {"rounds": 3, "reward_per_win": 0.10},
]
# How long a player waits for their partner to start a game, in seconds. The
# partner may still be reading the last game's result, so it allows for that.
PARTNER_WAIT_SECONDS = 300


def round_result(mine, theirs):
    if mine == theirs:
        return "draw"
    return "win" if BEATS[mine] == theirs else "loss"


def partner_of(player_id, players):
    (partner,) = [player for player in players if player != player_id]
    return partner


def rounds_as_seen_by(player_id, rounds):
    """The rounds played so far, as the player sees them: their choice, their
    partner's, and the result for them."""
    if not rounds:
        return []
    partner = partner_of(player_id, rounds[0])
    return [
        {
            "mine": choices[player_id],
            "theirs": choices[partner],
            "result": round_result(choices[player_id], choices[partner]),
        }
        for choices in rounds
    ]


class Choose(LiveMessage):
    """A player's action in one round."""

    type = "choose"
    round: int
    action: Action

    def apply(self, game, state, player_id, now):
        # The round number stops a click on a page that hasn't caught up yet,
        # such as one in another tab, from counting for the next round.
        if self.round != len(state["rounds"]) + 1:
            raise Reject("That isn't the current round.")
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


class RockPaperScissors(LiveGame):
    """A game of rock, paper, scissors between two players.

    The state holds the number of rounds in the game, which comes from the
    session's settings, each player's choice in the current round, ``None``
    until they choose, the choices of every round played so far, and the
    number of rounds each player has won. A player's view says whether their
    partner has chosen in the current round, and shows the partner's choice
    only once the round is over.
    """

    channel = "rock_paper_scissors_live"
    messages = [Choose]
    # A limit on the whole game, counted from when the pair finished
    # waiting for each other. A game takes a minute or two, so it ends within five
    # minutes even if a player leaves it.
    max_duration = 300

    def initial_state(self, players, settings):
        return {
            "n_rounds": settings["rounds"],
            "choices": {player: None for player in players},
            "rounds": [],
            "wins": {player: 0 for player in players},
        }

    def view(self, state, player_id):
        partner = partner_of(player_id, state["choices"])
        return {
            "round": len(state["rounds"]) + 1,
            "n_rounds": state["n_rounds"],
            "chosen": state["choices"][player_id] is not None,
            "partner_chosen": state["choices"][partner] is not None,
            "results": rounds_as_seen_by(player_id, state["rounds"]),
            "wins": state["wins"][player_id],
            "partner_wins": state["wins"][partner],
        }

    def is_over(self, state):
        return len(state["rounds"]) == state["n_rounds"]

    def outcome(self, state, reason):
        return {
            "reason": reason,
            "rounds": state["rounds"],
            "wins": state["wins"],
        }

    def answer(self, outcome, reason, player_id):
        """The player's own part of the outcome: their rounds, each with both
        choices and the result for them, and the rounds each player won."""
        partner = partner_of(player_id, outcome["wins"])
        return {
            "reason": reason,
            "rounds": rounds_as_seen_by(player_id, outcome["rounds"]),
            "wins": outcome["wins"][player_id],
            "partner_wins": outcome["wins"][partner],
        }

    def bot(self, view, player_id, now):
        if view["chosen"]:
            return None
        return Choose(round=view["round"], action=random.choice(ACTIONS))


def show_result(answer, reward):
    """The feedback page for a game whose answer for the player is
    ``answer``, for which they were paid ``reward``."""
    if not answer["rounds"]:
        return InfoPage(
            "The game ended before any rounds were played.", time_estimate=5
        )
    wins = answer["wins"]
    partner_wins = answer["partner_wins"]
    if answer["reason"] != "finished":
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
                f"You won {wins} of the {len(answer['rounds'])} rounds played, "
                f"and your partner won {partner_wins}."
            ),
            tags.p(f"Your bonus for this game is ${reward:.2f}."),
        ),
        time_estimate=5,
    )


class RockPaperScissorsTrial(Trial):
    """One game between the two participants of a pair. The trial's definition
    says which of the pair's games it is, how many rounds it has and what a
    round won pays, and the trial's answer is the player's part of the game's
    outcome."""

    sync_group_type = "pair"
    time_estimate = 65

    def show_trial(self, experiment, participant):
        game = self.definition
        # PlayLiveGame waits for the pair, starts their session and shows the
        # game page. Starting the session closes the pair's round, as
        # releasing any group barrier in a cued trial does.
        return PlayLiveGame(
            id_="rock_paper_scissors",
            group_type="pair",
            game_class=RockPaperScissors,
            settings={"rounds": game["rounds"]},
            # A player whose partner doesn't arrive leaves the pair, and goes
            # on to the game page without a session.
            max_wait_time=PARTNER_WAIT_SECONDS,
            max_wait_action="leave_group",
            page=ModularPage(
                "rock_paper_scissors",
                Prompt(
                    tags.div(
                        tags.p(
                            f"Game {game['number']} of {len(GAMES)}, of "
                            f"{game['rounds']} rounds. Each round you win pays "
                            f"a bonus of ${game['reward_per_win']:.2f}.",
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
                LiveGameControl(
                    player_left_message=(
                        "Your partner has left the game. If they don't come "
                        "back, it will end in a few minutes."
                    ),
                    no_game_message=("This game can't be played without your partner."),
                ),
                js_page_modules=["/static/rock-paper-scissors.js"],
                css_links=["/static/rock-paper-scissors.css"],
                time_estimate=60,
            ),
        )

    def score_answer(self, answer, definition):
        """Return the number of rounds the player won."""
        if answer is None:
            # The game page had no session, so no game was played.
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
    "waited_too_long": "Your partner didn't come back for the next game.",
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
    label = "Rock, paper, scissors live session demo"
    test_n_bots = 2
    test_mode = "parallel"

    timeline = Timeline(
        InfoPage(
            f"You'll play {len(GAMES)} games of rock, paper, scissors against "
            "another participant, and you earn a bonus for each round you "
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
            {"number": 1, "rounds": 5, "reward_per_win": 0.05},
            {"number": 2, "rounds": 3, "reward_per_win": 0.10},
        ]
        # The bot's latest session is its second game.
        result = live_game_result(live_game_id(bot, "rock_paper_scissors"))
        assert result.status == "ended", result.error
        assert result.end_reason == "finished"
        assert trials[-1].group_round.live_game_outcome == result.outcome
        reward = 0
        for trial in trials:
            rounds = trial.answer["rounds"]
            # Each game has the number of rounds its trial's definition says.
            assert len(rounds) == trial.definition["rounds"]
            wins = sum(played["result"] == "win" for played in rounds)
            assert trial.score == trial.answer["wins"] == wins
            # The trial pays what its definition says for each round won.
            trial_reward = wins * trial.definition["reward_per_win"]
            assert trial.performance_reward == pytest.approx(trial_reward)
            reward += trial_reward
        assert bot.performance_reward == pytest.approx(reward)

"""Repeated public goods game in groups of three that carries on when members leave.

In each of ``N_ROUNDS`` rounds, every member privately puts some of their
``ENDOWMENT`` tokens in the group pot. The pot is multiplied by ``MULTIPLIER``
and shared between the members who played the round, and everyone sees the
group's contributions and what they earned, paid as a bonus of
``TOKEN_VALUE`` per token.

Each round is one ``ContributionTrial`` per player, cued with the loop value
as ``round=``. The team's trials in a round share a ``SyncGroupRound``,
which holds the team's pot; each trial holds the player's contribution and pays their
payoff, according to its ``sync_group_outcome``. See ``README.md`` for what
happens when players run out of time or leave.
"""

from typing import List

import psynet.experiment
from psynet.bot import (
    BotDriver,
    advance_past_wait_pages,
    make_late_now,
    run_bots_to_completion,
)
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, SimpleGrouper, SyncGroupRound
from psynet.timeline import Module, PageMaker, Timeline, conditional, for_loop, join
from psynet.trial.main import Trial
from psynet.utils import serialise_datetime

GROUP = "team"
N_ROUNDS = 3
ENDOWMENT = 10
MULTIPLIER = 1.5
TOKEN_VALUE = 0.02
# The time a player is expected to spend reading a round's results.
RESULTS_SECONDS = 10
# Short so that the bot test runs quickly; with real participants, allow about
# 30, 60 and 300 seconds. LATE_AFTER also covers reading the previous round's
# results, which has no time limit.
DECISION_SECONDS = 10
LATE_AFTER = 15
GROUPING_WAIT = 20


def get_timeline():
    return Timeline(
        InfoPage(
            f"You will play {N_ROUNDS} rounds of a game with two other players. "
            f"Each round you get {ENDOWMENT} tokens and choose how many to put in "
            f"a group pot. The pot is multiplied by {MULTIPLIER} and shared equally "
            f"between the players. Each token you earn pays ${TOKEN_VALUE:.2f}.",
            time_estimate=15,
        ),
        SimpleGrouper(
            GROUP,
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


def removed_from_team(participant):
    """Return whether the experimenter has removed the player from their team on the dashboard.

    Nothing else leaves a player without a team and still playing: a late
    player is failed, and so is the last player of a team that ends.
    """
    return not participant.in_sync_group(GROUP)


class ContributionTrial(Trial):
    sync_group_type = GROUP
    time_estimate = DECISION_SECONDS + RESULTS_SECONDS

    def show_trial(self, experiment, participant):
        return join(
            self.contribution_page(participant),
            GroupBarrier(
                id_="round_finished",
                group_type=GROUP,
                waiting_message="Waiting for the other players…",
                waiting_screen=your_contribution,
                # A player who closes their page is failed, and the others
                # carry on without them.
                late_after=LATE_AFTER,
                late_action="fail",
                # Releasing the team closes the round and scores it.
                on_release=self.score_round,
            ),
        )

    def contribution_page(self, participant):
        return ModularPage(
            "contribution",
            # Ticks appear as the others decide. The loop's stop_if means the
            # trial always has a group, so sync_group_round is set.
            GroupPrompt(
                f"Round {self.sync_group_round + 1} of {N_ROUNDS}. How many of "
                f"your {ENDOWMENT} tokens do you put in the group pot?",
                participant=participant,
                group=self.sync_group,
            ),
            PushButtonControl(
                choices=list(range(ENDOWMENT + 1)), arrange_vertically=False
            ),
            time_limit=DECISION_SECONDS,
            time_estimate=DECISION_SECONDS,
        )

    @classmethod
    def score_round(
        cls,
        trials: List["ContributionTrial"],
        group_round: SyncGroupRound,
        left: list,
    ):
        """Share the multiplied pot between the members who played the round."""
        # A player who ran out of time has an answer of None and puts in
        # nothing.
        group_round.var.contributions = {t.participant_id: t.answer for t in trials}
        pot = sum(t.answer or 0 for t in trials)
        multiplied_pot = MULTIPLIER * pot
        share = multiplied_pot / len(trials)
        group_round.var.pot = pot
        group_round.var.multiplied_pot = multiplied_pot
        group_round.var.share = share
        # Members who left since the previous round was scored, including
        # one who left while reading its results.
        group_round.var.n_left = len(left)
        for trial in trials:
            trial.var.payoff = ENDOWMENT - (trial.answer or 0) + share

    def score_answer(self, answer, definition):
        """Return the tokens the player earned in the round."""
        if self.sync_group_outcome == "stayed":
            return self.var.payoff
        # "removed_by_experimenter". A failed player, for example one who was
        # late or the last of a team that ended, is never scored: their trial
        # doesn't finish.
        return 0

    def compute_performance_reward(self, score):
        return TOKEN_VALUE * score

    def gives_feedback(self, experiment, participant):
        return self.sync_group_outcome == "stayed"

    def show_feedback(self, experiment, participant):
        team = self.group_round.var
        # A group of three with a quorum of two dissolves when a second player
        # leaves, cancelling the round, so a scored round has n_left <= 1.
        left = "One player has left the group. " if team.n_left else ""
        if self.time_limit_reached:
            you = "You ran out of time and put in nothing"
        else:
            you = f"You put in {self.answer}"
        return ModularPage(
            "results",
            GroupPrompt(
                f"{left}The group put {team.pot} tokens in the pot, which became "
                f"{team.multiplied_pot:g} and was shared between "
                f"{len(team.contributions)} players: {team.share:g} tokens "
                f"each. {you}, so you earned {self.var.payoff:g} tokens this round.",
                participant=participant,
                group=self.sync_group,
                answers={
                    id_: f"{tokens or 0} tokens"
                    for id_, tokens in team.contributions.items()
                },
            ),
            time_estimate=RESULTS_SECONDS,
        )


def your_contribution(participant, trial):
    """Show the player's contribution in place of the buttons while others decide."""
    if trial.time_limit_reached:
        text = "You ran out of time, so you put in nothing."
    else:
        text = f"You put in {trial.answer} tokens."
    # Ticks appear as the others decide.
    return GroupPrompt(text, participant=participant, group=trial.sync_group)


def game_over(participant):
    return InfoPage(f"The game is over. {bonus_text(participant)}", time_estimate=5)


def removed_page(participant):
    return InfoPage(
        f"You were removed from the game. {bonus_text(participant)}",
        time_estimate=5,
    )


def bonus_text(participant):
    return f"Your bonus is ${participant.performance_reward:.2f}."


class Exp(psynet.experiment.Experiment):
    label = "Public goods game demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round and one per team per round.

        Player rows come from the trials and team rows from the rounds. Every
        trial gets a row, including one whose player left or whose round was
        cancelled; ``outcome`` says how the round ended for the player.
        """
        trials = ContributionTrial.query.order_by(
            ContributionTrial.sync_group_round, ContributionTrial.id
        )
        teams = SyncGroupRound.query.filter_by(module_id="game").order_by(
            SyncGroupRound.number, SyncGroupRound.id
        )
        return {
            "player_round": [
                {
                    "round": t.sync_group_round,
                    "team_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # False while the trial runs or if the player was failed
                    # during it, for example for being late, returning the
                    # study or being the last player of the team.
                    "complete": t.complete,
                    # "stayed" if the round was scored; otherwise why the
                    # player left: "late", "removed_by_experimenter", "left_experiment" or, for the
                    # last player of a cancelled round, "group_dissolved".
                    "outcome": t.sync_group_outcome,
                    # None if the player ran out of time or never answered.
                    "contribution": t.answer,
                    # Whether the player ran out of time; None if they
                    # never answered.
                    "timed_out": t.time_limit_reached,
                    # None if the player was failed during the round, for
                    # example for being late or returning the study.
                    "payoff": t.score,
                    "bonus": t.performance_reward,
                }
                for t in trials
            ],
            "team_round": [
                {
                    "round": r.number,
                    "team_id": r.sync_group_id,
                    "round_id": r.id,
                    # When the group dissolved and the round was cancelled,
                    # as an ISO timestamp, or None. Basic data must be JSON.
                    "dissolved_at": serialise_datetime(r.dissolved_at),
                    # The rest are None until the round is scored, so in a
                    # cancelled round. A player who ran out of time has a
                    # contribution of None.
                    "contributions": r.var.get("contributions"),
                    "pot": r.var.get("pot"),
                    "multiplied_pot": r.var.get("multiplied_pot"),
                    "share": r.var.get("share"),
                    # Players who left since the previous round was scored.
                    "n_left": r.var.get("n_left"),
                }
                for r in teams
            ],
        }

    test_n_bots = 3
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots)
        # A pot of 18 becomes 27: 9 tokens each.
        _play(bots, [2, 6, 10])
        text = bots[0].current_page_text
        assert "so you earned 17 tokens" in text, text
        text = bots[2].current_page_text
        assert "so you earned 9 tokens" in text, text

        _see_results(bots)
        bots[0].take_page(response=4)
        bots[1].take_page(response=8)
        # bots[2] goes quiet, so the barrier fails them as late and the
        # other two carry on. A pot of 12 becomes 18: 9 tokens each.
        bots[2].allow_failure()
        make_late_now(bots, "round_finished")
        assert bots[2].failed
        text = bots[0].current_page_text
        assert text.startswith("One player has left the group."), text
        assert "so you earned 15 tokens" in text, text

        _see_results(bots[:2])
        bots[0].take_page(response=6)
        bots[1].run_out_of_time()
        advance_past_wait_pages(bots[:2])
        # A pot of 6 becomes 9: 4.5 tokens each.
        text = bots[1].current_page_text
        assert "You ran out of time and put in nothing, so you earned 14.5" in text
        _see_results(bots[:2])
        # 17 + 15 + 8.5 tokens.
        text = bots[0].current_page_text
        assert text == "The game is over. Your bonus is $0.81.", text
        run_bots_to_completion(bots)

        data = self.get_basic_data()
        teams = data["team_round"]
        assert [(t["pot"], t["dissolved_at"], t["n_left"]) for t in teams] == [
            (18, None, 0),
            (12, None, 1),
            (6, None, 0),
        ], teams
        assert teams[2]["contributions"] == {
            bots[0].id: 6,
            bots[1].id: None,
        }, teams
        rows = data["player_round"]
        outcomes = [(r["participant_id"], r["round"], r["outcome"]) for r in rows]
        assert [o for o in outcomes if o[2] != "stayed"] == [(bots[2].id, 1, "late")], (
            outcomes
        )
        timed_out = [(r["participant_id"], r["round"]) for r in rows if r["timed_out"]]
        assert timed_out == [(bots[1].id, 2)], timed_out
        for bot in bots:
            # A trial failed with its player has no bonus.
            paid = sum(r["bonus"] or 0 for r in rows if r["participant_id"] == bot.id)
            reward = bot.with_participant(lambda p: p.performance_reward)
            assert abs(paid - reward) < 1e-9, (bot.id, paid, reward)


def _play(bots, contributions):
    for bot, tokens in zip(bots, contributions):
        bot.take_page(response=tokens)
    advance_past_wait_pages(bots)


def _see_results(bots):
    for bot in bots:
        bot.take_page()

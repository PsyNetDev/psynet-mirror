"""Repeated public goods game in groups of three that carries on when members leave.

In each of ``N_ROUNDS`` rounds, every member privately puts some of their
``ENDOWMENT`` tokens in the group pot. The pot is multiplied by ``MULTIPLIER``
and shared between the members who played the round, and everyone sees the
group's contributions and what they earned, paid as a bonus of
``TOKEN_VALUE`` per token.

Each round is one ``ContributionTrial`` per player, cued with the loop value
as ``round=``. The team's trials in a round share a node, which holds the
team's pot; each trial holds the player's contribution and pays their
payoff, according to its ``sync_group_outcome``. See ``README.md`` for what
happens when players run out of time or leave.
"""

from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages, run_bots_to_completion
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Module, PageMaker, Timeline, conditional, for_loop, join
from psynet.trial.main import SyncGroupNode, Trial

GROUP = "team"
N_ROUNDS = 3
ENDOWMENT = 10
MULTIPLIER = 1.5
TOKEN_VALUE = 0.02
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
                # Checked before each round. A started trial runs to its end,
                # so the last player is still paid for the round in which the
                # group dissolves.
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


def left_team(participant):
    return not participant.in_sync_group(GROUP)


class ContributionTrial(Trial):
    sync_group_type = GROUP
    time_estimate = DECISION_SECONDS + 10

    def show_trial(self, experiment, participant):
        return join(
            self.contribution_page(participant),
            GroupBarrier(
                id_="round_finished",
                group_type=GROUP,
                waiting_message="Waiting for the other players…",
                waiting_screen=your_contribution,
                late_after=LATE_AFTER,
                late_action="leave_group",
                # Releasing the team closes the round and scores it.
                on_release=self.score_round,
            ),
        )

    def contribution_page(self, participant):
        return ModularPage(
            "contribution",
            # Ticks appear as the others decide. The loop's stop_if=left_team
            # means the trial always has a group, so sync_group_round is set.
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
        cls, trials: List["ContributionTrial"], node: SyncGroupNode, left: list
    ):
        """Share the multiplied pot between the members who played the round."""
        # String keys, because node.var stores JSON. A player who ran out of
        # time has an answer of None and puts in nothing.
        node.var.contributions = {str(t.participant_id): t.answer for t in trials}
        pot = sum(t.answer or 0 for t in trials)
        multiplied_pot = MULTIPLIER * pot
        share = multiplied_pot / len(trials)
        node.var.pot = pot
        node.var.multiplied_pot = multiplied_pot
        node.var.share = share
        # Members who left since the previous round was scored, including
        # one who left while reading its results.
        node.var.n_left = len(left)
        for trial in trials:
            trial.var.payoff = ENDOWMENT - (trial.answer or 0) + share

    def score_answer(self, answer, definition):
        """Return the tokens the player earned in the round."""
        outcome = self.sync_group_outcome
        if outcome == "stayed":
            return self.var.payoff
        if outcome == "group_dissolved":
            # The last player keeps their tokens for the cancelled round,
            # whether or not they were already waiting at the barrier.
            return ENDOWMENT
        if outcome == "late":
            return 0
        # Removed from the dashboard ("removed"). A player who returns the
        # study ("left_experiment") is never scored: their trial doesn't finish.
        return 0

    def compute_performance_reward(self, score):
        return TOKEN_VALUE * score

    def gives_feedback(self, experiment, participant):
        return self.sync_group_outcome == "stayed"

    def show_feedback(self, experiment, participant):
        node = self.node
        # A group of three plays on with two, so at most one player leaves.
        left = "One player has left the group. " if node.var.n_left else ""
        if self.time_limit_reached:
            you = "You ran out of time and put in nothing"
        else:
            you = f"You put in {self.answer}"
        return ModularPage(
            "results",
            GroupPrompt(
                f"{left}The group put {node.var.pot} tokens in the pot, which became "
                f"{node.var.multiplied_pot:g} and was shared between "
                f"{len(node.var.contributions)} players: {node.var.share:g} tokens "
                f"each. {you}, so you earned {self.var.payoff:g} tokens this round.",
                participant=participant,
                group=self.sync_group,
                answers={
                    id_: f"{tokens or 0} tokens"
                    for id_, tokens in node.var.contributions.items()
                },
            ),
            time_estimate=10,
        )


def your_contribution(participant, trial):
    """Replace the contribution buttons with the player's contribution while the others decide."""
    if trial.time_limit_reached:
        text = "You ran out of time, so you put in nothing."
    else:
        text = f"You put in {trial.answer} tokens."
    # Ticks appear as the others decide.
    return GroupPrompt(text, participant=participant, group=trial.sync_group)


def game_over(participant):
    return InfoPage(f"The game is over. {bonus_text(participant)}", time_estimate=5)


def game_ended_early(participant):
    reason = participant.sync_group_removal_reason(GROUP)
    if reason == "no_group_formed":
        return InfoPage("Without a group, there is no game to play.", time_estimate=5)
    if reason == "late":
        text = "You were away for too long, so the game went on without you."
    elif reason == "group_dissolved":
        text = "Too few players remained, so the game ended early."
    else:
        # Removed from the dashboard, which records no reason.
        text = "The game ended early for you."
    return InfoPage(f"{text} {bonus_text(participant)}", time_estimate=5)


def bonus_text(participant):
    return f"Your bonus is ${participant.performance_reward:.2f}."


class Exp(psynet.experiment.Experiment):
    label = "Public goods game demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round, from the trials, and one per team per round, from the nodes.

        Every trial gets a row, including one whose player left or whose
        round was cancelled; ``outcome`` says how the round ended for the
        player.
        """
        trials = ContributionTrial.query.order_by(
            ContributionTrial.sync_group_round, ContributionTrial.id
        )
        teams = SyncGroupNode.query.filter_by(module_id="game").order_by(
            SyncGroupNode.sync_group_round, SyncGroupNode.id
        )
        return {
            "player_round": [
                {
                    "round": t.sync_group_round,
                    "team_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # False while the trial runs or if the player returned
                    # the study during it.
                    "complete": t.complete,
                    # "stayed" if the round was scored; otherwise why the
                    # player left: "late", "left_experiment" or, for the
                    # last player of a cancelled round, "group_dissolved".
                    "outcome": t.sync_group_outcome,
                    # None if the player ran out of time or never answered.
                    "contribution": t.answer,
                    # Whether the player ran out of time; None if they
                    # never answered.
                    "timed_out": t.time_limit_reached,
                    # None if the player returned the study during the round.
                    "payoff": t.score,
                    "bonus": t.performance_reward,
                }
                for t in trials
            ],
            "team_round": [
                {
                    "round": n.sync_group_round,
                    "team_id": n.sync_group_id,
                    "node_id": n.id,
                    # When the group dissolved and the round was cancelled,
                    # or None.
                    "dissolved_at": n.sync_group_dissolved_at,
                    # The rest are None until the round is scored, so in a
                    # cancelled round. A player who ran out of time has a
                    # contribution of None.
                    "contributions": n.var.get("contributions"),
                    "pot": n.var.get("pot"),
                    "multiplied_pot": n.var.get("multiplied_pot"),
                    "share": n.var.get("share"),
                    # Players who left since the previous round was scored.
                    "n_left": n.var.get("n_left"),
                }
                for n in teams
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

        _see_results(bots)
        bots[0].take_page(response=4)
        bots[1].take_page(response=8)
        bots[2].run_out_of_time()
        advance_past_wait_pages(bots)
        # A pot of 12 becomes 18: 6 tokens each.
        text = bots[2].current_page_text
        assert "You ran out of time and put in nothing, so you earned 16" in text, text

        _see_results(bots)
        _play(bots, [0, 5, 7])
        _see_results(bots)
        text = bots[0].current_page_text  # 17 + 12 + 16 tokens
        assert text == "The game is over. Your bonus is $0.90.", text
        run_bots_to_completion(bots)

        data = self.get_basic_data()
        teams = data["team_round"]
        assert [(t["pot"], t["dissolved_at"], t["n_left"]) for t in teams] == [
            (18, None, 0),
            (12, None, 0),
            (12, None, 0),
        ], teams
        assert teams[1]["contributions"] == {
            str(bots[0].id): 4,
            str(bots[1].id): 8,
            str(bots[2].id): None,
        }, teams
        rows = data["player_round"]
        assert all(r["outcome"] == "stayed" for r in rows), rows
        timed_out = [(r["participant_id"], r["round"]) for r in rows if r["timed_out"]]
        assert timed_out == [(bots[2].id, 1)], timed_out
        for bot in bots:
            paid = sum(r["bonus"] for r in rows if r["participant_id"] == bot.id)
            reward = bot.with_participant(lambda p: p.performance_reward)
            assert abs(paid - reward) < 1e-9, (bot.id, paid, reward)


def _play(bots, contributions):
    for bot, tokens in zip(bots, contributions):
        bot.take_page(response=tokens)
    advance_past_wait_pages(bots)


def _see_results(bots):
    for bot in bots:
        bot.take_page()

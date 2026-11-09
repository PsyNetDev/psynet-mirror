"""Repeated public goods game in groups of three that carries on when members leave.

In each of ``N_ROUNDS`` rounds, every member privately puts some of their
``ENDOWMENT`` tokens in the group pot. The pot is multiplied by ``MULTIPLIER``
and shared between the members who played the round, and everyone sees the
group's contributions and what they earned, paid as a bonus of
``TOKEN_VALUE`` per token.

Each round is one cued ``ContributionTrial`` per player. The team's trials in
one round share a node, which holds the team's contributions and pot; each
player's contribution and payoff are on their trial, which pays the bonus.

- Running out of time on the contribution page puts nothing in the pot, so
  the player keeps their tokens and still gets their share.
- A player who returns the study, or closes the page and so is late for the
  end of a round (``LATE_AFTER``), leaves the group and earns nothing for
  that round. The others carry on while at least two remain, sharing the pot
  between fewer players.
- When one player remains, the group dissolves, the round is cancelled and
  they keep their tokens for it.
- Nobody is failed because others left: the last player, a player who comes
  back after being removed, and a participant for whom no group forms within
  ``GROUPING_WAIT`` are each told why the game ended for them.
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
            # A cued trial runs to its end once started, so a player whose
            # group dissolves partway through a round is still paid for it.
            for_loop(
                label="rounds",
                iterate_over=range(N_ROUNDS),
                logic=ContributionTrial.cue({}),
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
                late_after=LATE_AFTER,
                late_action="leave_group",
                on_release=self.score_round,
                on_dissolve=self.cancel_round,
            ),
        )

    def contribution_page(self, participant):
        # sync_group_round is None on an ungrouped trial, which the loop's
        # stop_if=left_team never cues; without it, check for a group first.
        return ModularPage(
            "contribution",
            GroupPrompt(
                f"Round {self.sync_group_round + 1} of {N_ROUNDS}. How many of "
                f"your {ENDOWMENT} tokens do you put in the group pot?",
                participant=participant,
                group=self.sync_group,
            ),
            PushButtonControl(choices=list(range(ENDOWMENT + 1))),
            time_limit=DECISION_SECONDS,
            time_estimate=DECISION_SECONDS,
        )

    @classmethod
    def score_round(cls, trials: List["ContributionTrial"], node: SyncGroupNode):
        """Share the multiplied pot between the members who played the round."""
        contributions = _contributions_by_player(trials)
        pot = sum(contributions.values())
        multiplied_pot = MULTIPLIER * pot
        share = multiplied_pot / len(trials)
        node.var.contributions = contributions
        node.var.pot = pot
        node.var.multiplied_pot = multiplied_pot
        node.var.share = share
        for trial in trials:
            # An answer of None means the player ran out of time.
            trial.var.payoff = ENDOWMENT - (trial.answer or 0) + share

    @classmethod
    def cancel_round(cls, trials: List["ContributionTrial"], node: SyncGroupNode):
        """Record the contributions of a round cancelled while its last member waited."""
        node.var.contributions = _contributions_by_player(trials)

    def score_answer(self, answer, definition):
        if self.var.has("payoff"):
            return self.var.payoff
        # The group dissolved during the round, whether or not the last member
        # was already waiting at the barrier, so they keep their tokens. A
        # player removed for being late earns nothing for the round.
        if self.participant.sync_group_removal_reason(GROUP) == "group_dissolved":
            return ENDOWMENT
        return 0

    def compute_performance_reward(self, score):
        return TOKEN_VALUE * score

    def gives_feedback(self, experiment, participant):
        # Only rounds that were played to the end have results to show.
        return self.var.has("payoff")

    def show_feedback(self, experiment, participant):
        node = self.node
        if self.answer is None:
            you = "You ran out of time and put in nothing"
        else:
            you = f"You put in {self.answer}"
        return ModularPage(
            "results",
            GroupPrompt(
                f"The group put {node.var.pot} tokens in the pot, which became "
                f"{node.var.multiplied_pot:g} and was shared between "
                f"{len(node.var.contributions)} players: {node.var.share:g} tokens "
                f"each. {you}, so you earned {self.var.payoff:g} tokens this round.",
                participant=participant,
                group=self.sync_group,
                answers={
                    id_: f"{tokens} tokens"
                    for id_, tokens in node.var.contributions.items()
                },
            ),
            time_estimate=10,
        )


def _contributions_by_player(trials):
    """Return each player's tokens in the pot, keyed by participant ID as a string."""
    return {str(t.participant_id): t.answer or 0 for t in trials}


def game_over(participant):
    return InfoPage(f"The game is over. {bonus_text(participant)}", time_estimate=5)


def game_ended_early(participant):
    reason = participant.sync_group_removal_reason(GROUP)
    if reason == "no_group_formed":
        return InfoPage("Without a group, there is no game to play.", time_estimate=5)
    if reason == "late":
        text = "You were away for too long, so the game went on without you."
    else:
        text = "Too few players remained, so the game ended early."
    return InfoPage(f"{text} {bonus_text(participant)}", time_estimate=5)


def bonus_text(participant):
    return f"Your bonus is ${participant.performance_reward:.2f}."


class Exp(psynet.experiment.Experiment):
    label = "Public goods game demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round, from the trials, and one per group per round, from the nodes.

        Every trial gets a row, including one whose player left or whose
        round was cancelled; ``played`` says whether the round was scored.
        """
        trials = ContributionTrial.query.order_by(
            ContributionTrial.sync_group_round, ContributionTrial.id
        )
        groups = SyncGroupNode.query.filter_by(module_id="game").order_by(
            SyncGroupNode.sync_group_round, SyncGroupNode.id
        )
        return {
            "player_round": [
                {
                    "round": t.sync_group_round,
                    "group_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # None if the player ran out of time or never answered.
                    "contribution": t.answer,
                    "played": t.var.has("payoff"),
                    # None if the player returned the study during the round.
                    "payoff": t.score,
                    "bonus": t.performance_reward,
                }
                for t in trials
            ],
            "group_round": [
                {
                    "round": n.sync_group_round,
                    "group_id": n.sync_group_id,
                    "node_id": n.id,
                    "contributions": n.var.get("contributions"),
                    # None if the round was cancelled.
                    "pot": n.var.get("pot"),
                    "multiplied_pot": n.var.get("multiplied_pot"),
                    "share": n.var.get("share"),
                }
                for n in groups
            ],
        }

    test_n_bots = 10
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        self._test_full_game(bots[:3])
        self._test_dropouts(*bots[3:6])
        self._test_no_group(bots[6])
        self._test_others_leave_before_contributing(*bots[7:10])

        data = self.get_basic_data()
        # The full game's group, then the dropouts' group, whose last round
        # was cancelled with only the stayer's 5 tokens in.
        groups = [g for g in data["group_round"] if g["contributions"] is not None]
        assert [(g["round"], g["pot"]) for g in groups] == [
            (0, 18),
            (0, 18),
            (1, 12),
            (1, 14),
            (2, 12),
            (2, None),
        ], groups
        assert groups[-1]["contributions"] == {str(bots[5].id): 5}, groups[-1]

        rows = data["player_round"]
        for bot in bots:
            paid = sum(r["bonus"] or 0 for r in rows if r["participant_id"] == bot.id)
            reward = bot.with_participant(lambda p: p.performance_reward)
            assert abs(paid - reward) < 1e-9, (bot.id, paid, reward)

    def _test_full_game(self, bots):
        _start(bots)
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

    def _test_dropouts(self, quitter, silent, stayer):
        _start([quitter, silent, stayer])
        _play([quitter, silent, stayer], [3, 6, 9])
        _see_results([quitter, silent, stayer])

        # Round 2: the quitter returns the study; the other two carry on.
        silent.take_page(response=4)
        stayer.take_page(response=10)
        quitter.drop_out()
        advance_past_wait_pages([silent, stayer])
        text = stayer.current_page_text
        assert "shared between 2 players: 10.5 tokens each" in text, text

        # Round 3: silent stops responding and is removed for being late,
        # which dissolves the group while the stayer waits for the results.
        stayer.take_page()
        stayer.take_page(response=5)
        advance_past_wait_pages([stayer], timeout=LATE_AFTER + 15)
        assert stayer.current_notice == (
            "Too few members of your group remained. Please continue."
        ), stayer.current_notice
        text = stayer.current_page_text  # 10 + 10.5, and 10 for the cancelled round
        assert text == (
            "Too few players remained, so the game ended early. Your bonus is $0.61."
        ), text

        # Only the stayer was left when silent was removed, hence "partner".
        assert silent.current_notice == (
            "Your partner went on without you. Please continue."
        ), silent.current_notice
        silent.take_page()
        text = silent.current_page_text  # 13 + 16.5 tokens
        assert text == (
            "You were away for too long, so the game went on without you. "
            "Your bonus is $0.59."
        ), text
        run_bots_to_completion([silent, stayer])

    def _test_no_group(self, bot):
        bot.take_page()
        advance_past_wait_pages([bot], timeout=GROUPING_WAIT + 15)
        assert bot.current_notice == (
            "We couldn't form a group for you in time. Please continue."
        ), bot.current_notice
        text = bot.current_page_text
        assert text == "Without a group, there is no game to play.", text
        bot.run_to_completion()

    def _test_others_leave_before_contributing(self, quitter_1, quitter_2, stayer):
        # The group dissolves before the stayer reaches the barrier, so the
        # round is cancelled without on_dissolve; they still keep their tokens.
        _start([quitter_1, quitter_2, stayer])
        quitter_1.drop_out()
        quitter_2.drop_out()
        stayer.take_page(response=3)
        advance_past_wait_pages([stayer])
        text = stayer.current_page_text
        assert text == (
            "Too few players remained, so the game ended early. Your bonus is $0.20."
        ), text
        stayer.run_to_completion()


def _start(bots):
    for bot in bots:
        bot.take_page()
    advance_past_wait_pages(bots)
    assert all(bot.current_page_label == "contribution" for bot in bots)


def _play(bots, contributions):
    for bot, tokens in zip(bots, contributions):
        bot.take_page(response=tokens)
    advance_past_wait_pages(bots)


def _see_results(bots):
    for bot in bots:
        bot.take_page()

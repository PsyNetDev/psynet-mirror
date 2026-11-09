"""Wisdom of crowds: an estimation game in an open lobby that latecomers can join.

Players wait in a lobby for a group of four. If the first of them has waited
``START_SHORT_AFTER`` seconds and three are waiting, those three start
instead, and a latecomer can still join them until the game starts. For each
of two questions, every member estimates the answer, sees everyone's
estimate and the group's median, and gives a revised estimate.

Each question is one cued ``EstimateTrial`` per player. The group's trials
for a question share a node, which holds the group's estimates and median;
each player's estimate and revised estimate are their trial's answer. A
player without a group gets an ungrouped trial, which asks only for the
estimate.

Dropout decisions
-----------------

- A median of two estimates is just their mean, so a group needs three
  members (its quorum).
- Latecomers can join only until the game starts, so that everyone in a
  group answers every question together. After that, a latecomer waits in
  the lobby for a new group.
- A group that falls below three before the game starts waits up to
  ``TOP_UP_WAIT`` seconds for a latecomer to replace the member who left.
- Each estimate has a time limit of ``ANSWER_SECONDS``; a player who runs
  out of time gives none.
- A member who stops responding is removed, so nobody waits for them: at
  the start of the game ``LATE_AFTER`` seconds after the group formed, and
  during it ``LATE_AFTER`` seconds after their page's time limit.
- A group that falls below three once the game has started ends.
- A median needs three estimates. When fewer arrive, because players ran
  out of time or the group ended while they waited for it, the group's
  estimates are saved without a median and there is nothing to revise.
- Nobody is failed for what another player did, or for waiting: anyone
  without a group, because none formed within ``LOBBY_WAIT`` seconds, their
  group ended, or they were removed, answers the remaining questions alone.

The timeouts are short so that the bot test runs quickly. A real deployment
would start short after about a minute, wait about three minutes in the
lobby, allow about 30 seconds for ``ANSWER_SECONDS`` and about a minute for
each of ``TOP_UP_WAIT`` and ``LATE_AFTER``, which also covers reading the
introduction.
"""

import statistics
from typing import List

import psynet.experiment
from psynet.bot import (
    BotDriver,
    advance_past_wait_pages,
    bots_by_sync_group,
    run_bots_to_completion,
)
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, NumberControl
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, SimpleGrouper, only_in_group
from psynet.timeline import Module, PageMaker, Timeline, for_loop, join
from psynet.trial.main import SyncGroupNode, Trial

GROUP = "crowd"
GROUP_SIZE = 4
QUORUM = 3
START_SHORT_AFTER = 3
LOBBY_WAIT = 8
TOP_UP_WAIT = 4
ANSWER_SECONDS = 10
LATE_AFTER = 15

QUESTIONS = [
    "How many jelly beans fit in a one-litre jar?",
    "How far is it from London to Rome, in kilometres, as the crow flies?",
]

SOLO_TEXT = "You'll answer the questions on your own."


def get_timeline():
    return Timeline(
        InfoPage("Welcome to the estimation game.", time_estimate=5),
        SimpleGrouper(
            GROUP,
            initial_group_size=GROUP_SIZE,
            quorum=QUORUM,
            start_short_after=START_SHORT_AFTER,
            join_existing_groups=True,
            top_up_wait=TOP_UP_WAIT,
            below_quorum="continue_without_group",
            max_wait_time=LOBBY_WAIT,
            max_wait_action="continue_without_group",
            waiting_message="Waiting for other players to join…",
        ),
        only_in_group(
            GROUP,
            InfoPage(
                "You're in a group of up to four players. For each question, "
                "give an estimate, see your group's estimates, and then give "
                "a revised estimate.",
                time_estimate=10,
            ),
            GroupBarrier(
                id_="game_starts",
                group_type=GROUP,
                late_after=LATE_AFTER,
                late_action="leave_group",
                stop_top_ups=True,
            ),
            otherwise=InfoPage(SOLO_TEXT, time_estimate=5),
        ),
        Module(
            "game",
            for_loop(
                label="questions",
                iterate_over=range(len(QUESTIONS)),
                logic=cue_question,
                time_estimate_per_iteration=EstimateTrial.time_estimate,
                expected_repetitions=len(QUESTIONS),
            ),
        ),
    )


def cue_question(question):
    """Cue the group's next question, or this loop's question for a player alone."""

    def question_for_round(round):
        # A group's round is the same for all its members; a player without a
        # group has no round.
        return {"question": question if round is None else round}

    return EstimateTrial.cue(question_for_round)


class EstimateTrial(Trial):
    sync_group_type = GROUP
    time_estimate = 2 * ANSWER_SECONDS
    # The trial's answer holds both the estimate and the revised estimate.
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        if self.sync_group is None:
            # Alone, the estimate is the whole trial.
            return self.estimate_page(time_estimate=self.time_estimate)
        return join(
            self.estimate_page(time_estimate=ANSWER_SECONDS),
            GroupBarrier(
                id_="estimates",
                group_type=GROUP,
                late_after=LATE_AFTER,
                late_action="leave_group",
                on_release=self.share_median,
                on_dissolve=self.share_median,
            ),
            # show_trial runs when the trial starts, so the page that shows the
            # median is built later, once the barrier has saved it.
            PageMaker(self.revise_page, time_estimate=ANSWER_SECONDS),
        )

    @property
    def question(self):
        return QUESTIONS[self.definition["question"]]

    def estimate_page(self, time_estimate):
        return ModularPage(
            "estimate",
            self.question,
            NumberControl(),
            save_answer="estimate",
            time_limit=ANSWER_SECONDS,
            time_estimate=time_estimate,
        )

    @classmethod
    def share_median(cls, trials: List["EstimateTrial"], node: SyncGroupNode):
        """Save the group's estimates on the node, with their median if there are enough."""
        # Browsers submit numbers as strings, and running out of time saves None.
        node.var.estimates = {
            str(t.participant_id): float(t.participant.var.estimate)
            for t in trials
            if t.participant.var.get("estimate") not in (None, "")
        }
        if len(node.var.estimates) >= QUORUM:
            node.var.median = statistics.median(node.var.estimates.values())

    def revise_page(self, participant):
        estimates = self.node.var.get("estimates") or {}
        if not self.node.var.has("median"):
            return InfoPage(
                "Too few estimates arrived for a group median, so there is "
                "nothing to revise.",
                time_estimate=5,
            )
        if str(participant.id) not in estimates:
            # They ran out of time, or were removed for being late.
            return InfoPage(
                "Your estimate didn't reach your group in time, so there is "
                "nothing to revise.",
                time_estimate=5,
            )
        return ModularPage(
            "revised",
            GroupPrompt(
                f"{self.question} The median of your group's {len(estimates)} "
                f"estimates is {self.node.var.median:g}. Give your revised estimate.",
                participant=participant,
                group=self.sync_group,
                answers={pid: f"{value:g}" for pid, value in estimates.items()},
            ),
            NumberControl(),
            time_limit=ANSWER_SECONDS,
            time_estimate=ANSWER_SECONDS,
        )


class Exp(psynet.experiment.Experiment):
    label = "Wisdom-of-crowds estimation demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per answer, from the trials, and one per group per question, from the nodes."""
        trials = EstimateTrial.query.filter_by(finalized=True).order_by(
            EstimateTrial.id
        )
        groups = SyncGroupNode.query.filter_by(module_id="game").order_by(
            SyncGroupNode.sync_group_round, SyncGroupNode.id
        )
        return {
            "answer": [
                {
                    "participant_id": t.participant_id,
                    "question": t.definition["question"],
                    # None for an answer given alone.
                    "group_id": t.sync_group_id,
                    "trial_id": t.id,
                    "estimate": t.answer.get("estimate"),
                    # None for an answer given alone; False if it missed the
                    # group's estimates, which make up the median.
                    "in_median": None
                    if t.sync_group_id is None
                    else str(t.participant_id) in (t.node.var.get("estimates") or {}),
                    "revised": t.answer.get("revised"),
                }
                for t in trials
            ],
            "group_round": [
                {
                    "question": n.sync_group_round,
                    "group_id": n.sync_group_id,
                    "node_id": n.id,
                    # The estimates that arrived in time; None if no member
                    # was waiting for them.
                    "estimates": n.var.get("estimates"),
                    # None if fewer than three estimates arrived.
                    "median": n.var.get("median"),
                }
                for n in groups
            ],
        }

    test_n_bots = 11
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        group, latecomer, too_late = bots[:4], bots[3], bots[4]
        group_b, group_c = bots[5:8], bots[8:]
        silent, players = group[0], group[1:]

        # Three start short, and a latecomer joins before the game starts.
        for bot in group[:3]:
            bot.take_page()
        advance_past_wait_pages(group[:3], timeout=START_SHORT_AFTER + 10)
        latecomer.take_page()
        assert bots_by_sync_group(group, GROUP) == [group]
        for bot in group:
            bot.take_page()
        advance_past_wait_pages(group)

        # One member goes silent; the other three carry on above quorum.
        # Browsers submit estimates as strings.
        for bot, estimate in zip(players, [100, 200, "600.5"]):
            bot.take_page(response=estimate)
        advance_past_wait_pages(players, timeout=ANSWER_SECONDS + LATE_AFTER + 10)
        for bot in players:
            text = bot.current_page_text
            assert "median of your group's 3 estimates is 200." in text, text
            assert bot.current_notice is None, bot.current_notice

        # The game has started, so a latecomer can't join, even with a seat free.
        too_late.take_page()
        assert not too_late.with_participant(lambda p: p.in_sync_group(GROUP))

        for bot in players:
            bot.take_page(response=250)
        for bot, estimate in zip(players, [1000, 1400, 1500]):
            bot.take_page(response=estimate)
        advance_past_wait_pages(players)
        for bot in players:
            text = bot.current_page_text
            assert "median of your group's 3 estimates is 1400." in text, text
            bot.take_page(response=1300)

        # The silent member comes back, too late for the first question's
        # median, and answers the second alone.
        assert silent.current_notice == (
            "Your group went on without you. Please continue."
        ), silent.current_notice
        silent.take_page(response=300)
        assert silent.current_page_text.startswith("Your estimate didn't reach"), (
            silent.current_page_text
        )
        silent.take_page()
        assert silent.current_page_label == "estimate", silent.current_page_label

        # Nobody else arrived, so the latecomer plays alone.
        advance_past_wait_pages([too_late], timeout=LOBBY_WAIT + 10)
        assert too_late.current_page_text == SOLO_TEXT, too_late.current_page_text
        assert too_late.current_notice == (
            "We couldn't form a group for you in time. Please continue."
        ), too_late.current_notice

        # A group loses a member before the game, and nobody replaces them.
        for bot in group_b:
            bot.take_page()
        advance_past_wait_pages(group_b, timeout=START_SHORT_AFTER + 10)
        quitter, *stayers = group_b
        quitter.drop_out()
        for bot in stayers:
            bot.take_page()
        advance_past_wait_pages(stayers, timeout=TOP_UP_WAIT + 10)
        for bot in stayers:
            assert bot.current_page_text == SOLO_TEXT, bot.current_page_text
            assert bot.current_notice == (
                "Too few members of your group remained. Please continue."
            ), bot.current_notice

        # A group ends while two members wait for the first median.
        for bot in group_c:
            bot.take_page()
        advance_past_wait_pages(group_c, timeout=START_SHORT_AFTER + 10)
        for bot in group_c:
            bot.take_page()
        advance_past_wait_pages(group_c)
        quitter_c, *waiting = group_c
        for bot, estimate in zip(waiting, [10, 20]):
            bot.take_page(response=estimate)
        quitter_c.drop_out()
        advance_past_wait_pages(waiting)
        for bot in waiting:
            text = bot.current_page_text
            assert text.startswith("Too few estimates arrived"), text

        finishers = [*bots[:5], *stayers, *waiting]
        run_bots_to_completion(finishers)
        assert not any(bot.failed for bot in finishers)

        # The first group played both questions without the silent member;
        # the last one's estimates were saved without a median.
        data = self.get_basic_data()
        player_ids = sorted(str(bot.id) for bot in players)
        groups = data["group_round"]
        assert [
            (g["question"], g["median"], sorted(g["estimates"])) for g in groups
        ] == [
            (0, 200, player_ids),
            (0, None, sorted(str(bot.id) for bot in waiting)),
            (1, 1400, player_ids),
        ], groups
        answers = {(r["participant_id"], r["question"]): r for r in data["answer"]}
        for bot in players:
            revised = [answers[(bot.id, question)]["revised"] for question in (0, 1)]
            assert revised == [250, 1300], revised
        # The silent member's late answer is in their group's trial, but not
        # in its median.
        late = answers[(silent.id, 0)]
        assert (late["group_id"], late["in_median"]) == (groups[0]["group_id"], False)
        # Answers given alone have no revision.
        alone = (
            [(silent.id, 1)]
            + [
                (bot.id, question)
                for bot in [too_late, *stayers]
                for question in (0, 1)
            ]
            + [(bot.id, 1) for bot in waiting]
        )
        for key in alone:
            row = answers[key]
            assert (row["group_id"], row["revised"]) == (None, None), row

"""Wisdom of crowds: an estimation game in an open lobby that latecomers can join.

Players wait in a lobby for a group of four. If the first of them has waited
``START_SHORT_AFTER`` seconds and three are waiting, those three start
instead, and a latecomer can still join them until the game starts. For each
of two questions, every member estimates the answer, sees everyone's
estimate and the group's median, and gives a revised estimate.

Each question is one cued ``EstimateTrial`` per player, in the group's round
of that number (``round=question``). The group's trials for a question share
a node, which holds the group's estimates and median; each player's estimate
and revised estimate are their trial's answer, and ``trial.var.in_median``
says whether the estimate counted towards the median. A player without a
group, because none formed, their group ended or they were removed for being
late, gets ungrouped trials, which ask only for the estimate. See
``README.md`` for how the demo handles dropouts and time-outs.

The timeouts are short so that the bot test runs quickly; ``README.md``
suggests values for a real deployment.
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
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import (
    Module,
    PageMaker,
    Response,
    Timeline,
    conditional,
    for_loop,
    join,
)
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
        join(
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
            stop_if=left_group,
        ),
        conditional("solo", left_group, InfoPage(SOLO_TEXT, time_estimate=5)),
        Module(
            "game",
            for_loop(
                label="questions",
                iterate_over=range(len(QUESTIONS)),
                logic=lambda question: EstimateTrial.cue(
                    {"question": question}, round=question
                ),
                # An estimate and a revised estimate; alone, only the estimate.
                time_estimate_per_iteration=2 * ANSWER_SECONDS,
            ),
        ),
    )


def left_group(participant):
    return not participant.in_sync_group(GROUP)


class EstimateTrial(Trial):
    sync_group_type = GROUP
    # Alone, a trial is one estimate; in a group, its pages add a revised one.
    time_estimate = ANSWER_SECONDS
    # The trial's answer holds both the estimate and the revised estimate.
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        if self.sync_group is None:
            # Alone, the estimate is the whole trial.
            return self.estimate_page()
        return join(
            self.estimate_page(),
            GroupBarrier(
                id_="estimates",
                group_type=GROUP,
                late_after=LATE_AFTER,
                late_action="leave_group",
                on_release=self.score_round,
            ),
            # show_trial runs when the trial starts, so the page that shows the
            # median is built later, once the barrier has saved it.
            PageMaker(self.revise_page, time_estimate=ANSWER_SECONDS),
        )

    @property
    def question(self):
        return QUESTIONS[self.definition["question"]]

    def estimate_page(self):
        prompt = self.question
        if self.sync_group is None:
            # Also tells a member removed from the group partway through.
            prompt = f"You're answering on your own. {prompt}"
        return ModularPage(
            "estimate",
            prompt,
            NumberControl(),
            time_limit=ANSWER_SECONDS,
            time_estimate=ANSWER_SECONDS,
        )

    @classmethod
    def score_round(cls, trials: List["EstimateTrial"], node: SyncGroupNode):
        """Save the group's estimates on the node, with their median if there are enough, and on each trial whether its estimate is in the median."""
        estimates = {}
        for t in trials:
            # The answer so far; running out of time saves None.
            estimate = t.answer.get("estimate")
            if estimate is not None:
                estimates[str(t.participant_id)] = estimate
        node.var.estimates = estimates
        has_median = len(estimates) >= QUORUM
        node.var.median = statistics.median(estimates.values()) if has_median else None
        # From all the round's trials, so a member removed for being late is kept.
        for t in node.all_trials:
            t.var.in_median = str(t.participant_id) in estimates if has_median else None

    def revise_page(self, participant):
        # A member who left the group passes the barrier without waiting, so
        # their own outcome comes first: the group may not be scored yet. A
        # member removed as late after the release has an estimate in the
        # median, so they are told only that they left.
        if self.sync_group_outcome == "late" and not self.var.get("in_median"):
            reason = "Your estimate didn't reach your group in time"
        elif self.sync_group_outcome == "group_dissolved":
            # The framework's notice on this page says too few members remained.
            reason = "Your group ended before you saw its median"
        elif self.sync_group_outcome != "stayed":
            reason = "You left your group before you saw its median"
        elif self.node.var.get("median") is None:
            reason = "Too few estimates arrived for a group median"
        # The estimate is the trial's latest timed page so far, as barriers
        # don't count; the export reads its own response instead.
        elif self.time_limit_reached:
            reason = "You didn't give an estimate in time"
        else:
            estimates = self.node.var.estimates
            return ModularPage(
                "revised",
                GroupPrompt(
                    f"{self.question} The median of your group's {len(estimates)} "
                    f"estimates is {self.node.var.median:.15g}. "
                    "Give your revised estimate.",
                    participant=participant,
                    group=self.sync_group,
                    answers={pid: f"{v:.15g}" for pid, v in estimates.items()},
                ),
                NumberControl(),
                time_limit=ANSWER_SECONDS,
                time_estimate=ANSWER_SECONDS,
            )
        return InfoPage(f"{reason}, so there is nothing to revise.", time_estimate=5)


class Exp(psynet.experiment.Experiment):
    label = "Wisdom-of-crowds estimation demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per question, from the trials, and one per group per question, from the nodes.

        Every trial gets a row, including one whose player left before
        answering, so a missing answer is None rather than a missing row.
        """
        trials = EstimateTrial.query.order_by(EstimateTrial.id)
        # trial.time_limit_reached follows the trial's latest timed page,
        # which in a group is the revision, so read the estimate's response.
        estimate_timed_out = {
            r.trial_id: r.time_limit_reached
            for r in Response.query.filter_by(
                question="estimate", successful_validation=True
            )
        }
        crowds = SyncGroupNode.query.filter_by(module_id="game").order_by(
            SyncGroupNode.sync_group_round, SyncGroupNode.id
        )
        return {
            "player_round": [
                {
                    # None for an answer given alone.
                    "crowd_id": t.sync_group_id,
                    "question": t.definition["question"],
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # How the round ended for the player: "stayed" to the
                    # end, or why they last left during the round's pages,
                    # such as "late" or "group_dissolved", even after the
                    # median was shared (in_median says whether the estimate
                    # counted); None alone.
                    "outcome": t.sync_group_outcome,
                    # None if the player ran out of time or left first.
                    "estimate": t.answer.get("estimate"),
                    # Whether the estimate's time limit ran out, alone or in
                    # a group; None if the player left before answering it.
                    "estimate_timed_out": estimate_timed_out.get(t.id),
                    # Whether the estimate counted towards the group's median;
                    # None for an answer given alone or a group without one.
                    "in_median": t.var.get("in_median"),
                    "revised": t.answer.get("revised"),
                }
                for t in trials
            ],
            "crowd_round": [
                {
                    "crowd_id": n.sync_group_id,
                    "question": n.definition["question"],
                    "node_id": n.id,
                    # The estimates that arrived in time; None if the group
                    # ended before the barrier released it.
                    "estimates": n.var.get("estimates"),
                    # None if fewer than three estimates arrived.
                    "median": n.var.get("median"),
                }
                for n in crowds
            ],
        }

    test_n_bots = 4
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        # Three start short, and a latecomer joins before the game starts.
        for bot in bots[:3]:
            bot.take_page()
        advance_past_wait_pages(bots[:3], timeout=START_SHORT_AFTER + 10)
        bots[3].take_page()
        assert bots_by_sync_group(bots, GROUP) == [bots]
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots)

        medians = [250, 1450]
        for estimates, median in zip(
            [[100, 200, 300, 600.5], [1000, 1400, 1500, 1600]], medians
        ):
            for bot, estimate in zip(bots, estimates):
                bot.take_page(response=estimate)
            advance_past_wait_pages(bots)
            for bot in bots:
                text = bot.current_page_text
                assert f"median of your group's 4 estimates is {median}." in text, text
                bot.take_page(response=median)
        run_bots_to_completion(bots)
        assert not any(bot.failed for bot in bots)

        data = self.get_basic_data()
        assert [c["median"] for c in data["crowd_round"]] == medians, data
        rows = data["player_round"]
        assert len(rows) == 8, rows
        for r in rows:
            assert (r["outcome"], r["estimate_timed_out"], r["in_median"]) == (
                "stayed",
                False,
                True,
            ), r
            assert r["revised"] == medians[r["question"]], r

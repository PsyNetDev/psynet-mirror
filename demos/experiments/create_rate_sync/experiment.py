"""Synchronous create-and-rate game for groups of three.

In each trial, every member of the group first types the name of a food item,
then chooses between the items of the other two members, and then sees how
the group voted. The vote has a time limit of ``VOTE_SECONDS``, so one slow
member can't hold up the group; a member who runs out of time doesn't vote.

Each trial collects both answers in ``trial.answer`` (``accumulate_answers``).
After each phase, a :class:`~psynet.sync.GroupBarrier`'s ``on_release`` reads
the members' answers from their trials and stores what the next page needs
in each trial's ``var``: everyone's creations, and then everyone's votes and
the winning creation.
"""

import random
from collections import Counter
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

GROUP = "create_rate"
VOTE_SECONDS = 20


class CreateRateTrial(StaticTrial):
    time_estimate = 15
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        return join(
            ModularPage(
                "create",
                # Ticks appear as the others finish.
                GroupPrompt(
                    f"Type something you can have as {self.definition['target']}:",
                    group=self.sync_group,
                    participant=participant,
                ),
                TextControl(),
                time_estimate=5,
            ),
            GroupBarrier(
                id_="finished_creating",
                group_type=GROUP,
                waiting_message="Waiting for the rest of your group",
                on_release=self.store_creations,
            ),
            PageMaker(self.rate, time_estimate=5),
            GroupBarrier(
                id_="finished_rating",
                group_type=GROUP,
                waiting_message="Waiting for the rest of your group",
                # The fastest voter may wait out the rest of the vote.
                max_wait_time=VOTE_SECONDS + 30,
                on_release=self.count_votes,
            ),
            PageMaker(self.show_ratings, time_estimate=5),
        )

    @classmethod
    def store_creations(cls, trials: List["CreateRateTrial"]):
        """Store every member's creation on each member's trial."""
        creations = {str(t.participant_id): t.answer["create"] for t in trials}
        for trial in trials:
            trial.var.creations = creations

    @classmethod
    def count_votes(cls, trials: List["CreateRateTrial"]):
        """Store every member's vote and the result of the vote on each member's trial.

        A member who ran out of time has the vote ``None``. The result is
        ``"winner"`` (stored with the ``winner`` creation), ``"tie"`` or
        ``"no_votes"``.
        """
        votes = {str(t.participant_id): t.answer["rate"] for t in trials}
        counts = Counter(v for v in votes.values() if v is not None).most_common(2)
        if not counts:
            result, winner = "no_votes", None
        elif len(counts) == 1 or counts[0][1] > counts[1][1]:
            result, winner = "winner", counts[0][0]
        else:
            result, winner = "tie", None
        for trial in trials:
            trial.var.votes = votes
            trial.var.result = result
            trial.var.winner = winner

    def rate(self, participant):
        return ModularPage(
            "rate",
            GroupPrompt(
                f"Choose the {self.definition['target']} you prefer:",
                group=self.sync_group,
                participant=participant,
            ),
            PushButtonControl(choices=self.find_creations()),
            time_estimate=5,
            time_limit=VOTE_SECONDS,
        )

    def find_creations(self):
        """Return the other members' creations in random order."""
        creations = [
            creation
            for participant_id, creation in self.var.creations.items()
            if participant_id != str(self.participant_id)
        ]
        random.shuffle(creations)
        return creations

    def show_ratings(self, participant):
        votes = dict(self.var.votes)
        own = votes.pop(str(participant.id))
        others = sorted(v for v in votes.values() if v is not None)
        you = "You ran out of time to vote" if own is None else f"You voted for {own}"
        if not others:
            partners = "your partners didn't vote"
        elif len(others) == 1:
            partners = f"one partner voted for {others[0]} and the other didn't vote"
        else:
            partners = f"your partners voted for {others[0]} and {others[1]}"

        creations, winner = self.var.creations, self.var.winner
        highlight = {}
        if self.var.result == "winner":
            note = f"{winner} got the most votes."
            highlight = {pid: "winner" for pid, c in creations.items() if c == winner}
        elif self.var.result == "no_votes":
            note = "Nobody voted."
        else:
            note = "It's a tie."

        return ModularPage(
            "show_ratings",
            GroupPrompt(
                f"{you}, {partners}. Here is what everyone made.",
                group=self.sync_group,
                participant=participant,
                answers=creations,
                highlight=highlight,
                note=note,
            ),
            time_estimate=5,
        )


class Exp(psynet.experiment.Experiment):
    label = "Synchronous create and rate demo"

    timeline = Timeline(
        SimpleGrouper(
            group_type=GROUP,
            initial_group_size=3,
            # Every member creates and rates, so the group can't lose anyone.
            quorum=3,
            waiting_message="Waiting for the rest of your group",
        ),
        StaticTrialMaker(
            id_="create_rate",
            trial_class=CreateRateTrial,
            nodes=[
                StaticNode(definition={"target": target})
                for target in ["appetizer", "main dish", "dessert"]
            ],
            expected_trials_per_participant=3,
            max_trials_per_participant=3,
            sync_group_type=GROUP,
            sync_group_waiting_message="Waiting for the rest of your group",
        ),
    )

    test_n_bots = 3
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        # What each bot creates and votes for in each trial, and the most
        # popular creation, or None for a tie.
        trials = [
            (
                ["chocolate", "pudding", "yoghurt"],
                ["yoghurt", "yoghurt", "pudding"],
                "yoghurt",
            ),
            (
                ["schnitzel", "salad", "burger"],
                ["salad", "schnitzel", "salad"],
                "salad",
            ),
            (["melon", "shrimp", "soup"], ["shrimp", "soup", "melon"], None),
        ]
        advance_past_wait_pages(bots)

        for creations, votes, winner in trials:
            for bot, creation in zip(bots, creations):
                assert bot.current_page_label == "create"
                bot.take_page(response=creation)
            advance_past_wait_pages(bots)

            for bot, vote in zip(bots, votes):
                assert bot.current_page_label == "rate"
                bot.take_page(response=vote)
            advance_past_wait_pages(bots)

            note = "It's a tie." if winner is None else f"{winner} got the most votes."
            for i, bot in enumerate(bots):
                partners = " and ".join(sorted(votes[:i] + votes[i + 1 :]))
                assert bot.current_page_text == (
                    f"You voted for {votes[i]}, your partners voted for {partners}. "
                    f"Here is what everyone made. {note}"
                )
                bot.take_page()
            advance_past_wait_pages(bots)

        for bot in bots:
            assert "That's the end!" in bot.current_page_text

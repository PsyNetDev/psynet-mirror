import random
from collections import Counter
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
from psynet.participant import Participant
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import CodeBlock, PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

# Overview #####################################################################

# This experiment implements a synchronous create and rate task. Groups of three participants
# are created. In each trial, each participant is first asked to type the name of a food item.
# In a second phase of each trial, each participant chooses between the food items given by
# the other two participants, and is then informed about the choices made by the other participants.
# The vote has a time limit, so one slow participant can't hold up the group; a participant who
# runs out of time doesn't vote.

# #############################################################################

VOTE_SECONDS = 20


class CreateRateTrialMaker(StaticTrialMaker):
    pass


class CreateRateTrial(StaticTrial):
    time_estimate = 15
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        return join(
            PageMaker(self.create, time_estimate=5),
            GroupBarrier(
                id_="finished_creating",
                group_type="create_rate",
                content="Waiting for the rest of your group",
            ),
            PageMaker(self.rate, time_estimate=5),
            GroupBarrier(
                id_="finished_rating",
                group_type="create_rate",
                content="Waiting for the rest of your group",
                on_release=self.save_ratings,
            ),
            PageMaker(self.show_ratings, time_estimate=5),
        )

    def create(self, participant):
        prompt = f"Type something you can have as {self.definition['target']}:"
        return join(
            ModularPage(
                "create",
                # Ticks appear as the others finish.
                GroupPrompt(prompt, participant=participant),
                TextControl(),
                time_estimate=5,
                save_answer="create",
            ),
            CodeBlock(
                lambda participant: self.var.set("create", participant.var.create)
            ),
        )

    def rate(self, participant):
        prompt = f"Choose the {self.definition['target']} you prefer:"
        return join(
            ModularPage(
                "rate",
                GroupPrompt(prompt, participant=participant),
                PushButtonControl(
                    choices=self.find_creations(participant),
                ),
                time_estimate=5,
                save_answer="rate",
                time_limit=VOTE_SECONDS,
            ),
            CodeBlock(lambda participant: self.var.set("rate", participant.var.rate)),
        )

    def find_creations(self, participant):
        creations = [
            p.var.create
            for p in participant.sync_group.participants
            if p != participant
        ]
        random.shuffle(creations)
        return creations

    def show_ratings(self, participant):
        result = participant.var.last_trial
        own = result["rating_self"]
        others = [r for r in result["rating_others"] if r is not None]
        you = "You ran out of time to vote" if own is None else f"You chose {own}"
        if not others:
            partners = "your partners didn't vote"
        elif len(others) == 1:
            partners = f"one partner chose {others[0]} and the other didn't vote"
        else:
            partners = f"your partners chose {others[0]} and {others[1]}"
        prompt = f"{you}, {partners}. "
        creations = result["creation_by_player"]
        counts = Counter(
            r for r in result["rating_by_player"].values() if r is not None
        )
        highlight = {}
        if not counts:
            note = "Nobody voted."
        else:
            top, n_votes = counts.most_common(1)[0]
            if list(counts.values()).count(n_votes) == 1:
                note = f"{top} got the most votes."
                highlight = {pid: "winner" for pid, c in creations.items() if c == top}
            else:
                note = "It's a tie."

        return ModularPage(
            "show_ratings",
            GroupPrompt(
                prompt,
                participant=participant,
                answers=creations,
                highlight=highlight,
                note=note,
            ),
            time_estimate=5,
        )

    def save_ratings(self, participants: List[Participant]):
        assert len(participants) == 3

        ratings = [p.var.rate for p in participants]
        creations = {p.id: p.var.create for p in participants}
        rating_by_player = {p.id: p.var.rate for p in participants}

        for i in range(len(participants)):
            participants[i].var.last_trial = {
                "rating_self": ratings[i],
                "rating_others": sorted(
                    ratings[:i] + ratings[i + 1 :], key=lambda r: (r is None, r or "")
                ),
                "creation_by_player": creations,
                "rating_by_player": rating_by_player,
            }


class Exp(psynet.experiment.Experiment):
    label = "Synchronous create and rate demo"

    timeline = Timeline(
        SimpleGrouper(
            group_type="create_rate",
            initial_group_size=3,
            content="Waiting for the rest of your group",
        ),
        CreateRateTrialMaker(
            id_="create_rate",
            trial_class=CreateRateTrial,
            nodes=[
                StaticNode(definition={"target": target})
                for target in ["appetizer", "main dish", "dessert"]
            ],
            expected_trials_per_participant=3,
            max_trials_per_participant=3,
            sync_group_type="create_rate",
            sync_group_wait_content="Waiting for the rest of your group",
        ),
    )

    test_n_bots = 3
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        advance_past_wait_pages(bots)

        # CREATE 1
        assert bots[0].current_page_label == "create"
        bots[0].take_page(response="chocolate")
        assert bots[0].current_page_label == "wait"

        assert bots[1].current_page_label == "create"
        bots[1].take_page(response="pudding")

        assert bots[2].current_page_label == "create"
        bots[2].take_page(response="yoghurt")

        advance_past_wait_pages(bots)

        # RATE 1
        assert bots[0].current_page_label == "rate"
        bots[0].take_page(response="yoghurt")

        assert bots[1].current_page_label == "rate"
        bots[1].take_page(response="yoghurt")

        assert bots[2].current_page_label == "rate"
        bots[2].take_page(response="pudding")

        advance_past_wait_pages(bots)

        texts = [bot.current_page_text for bot in bots]
        assert texts[0] == "You chose yoghurt, your partners chose pudding and yoghurt."
        assert texts[1] == "You chose yoghurt, your partners chose pudding and yoghurt."
        assert texts[2] == "You chose pudding, your partners chose yoghurt and yoghurt."
        assert bots[0].get_current_page().prompt.note == "yoghurt got the most votes."

        bots[0].take_page()
        bots[1].take_page()
        bots[2].take_page()
        advance_past_wait_pages(bots)

        # CREATE 2
        bots[0].take_page(response="schnitzel")
        bots[1].take_page(response="salad")
        bots[2].take_page(response="burger")
        advance_past_wait_pages(bots)

        # RATE 2
        bots[0].take_page(response="salad")
        bots[1].take_page(response="schnitzel")
        bots[2].take_page(response="salad")
        advance_past_wait_pages(bots)

        texts = [bot.current_page_text for bot in bots]
        assert texts[0] == "You chose salad, your partners chose salad and schnitzel."
        assert texts[1] == "You chose schnitzel, your partners chose salad and salad."
        assert texts[2] == "You chose salad, your partners chose salad and schnitzel."

        bots[0].take_page()
        bots[1].take_page()
        bots[2].take_page()
        advance_past_wait_pages(bots)

        # CREATE 3
        bots[0].take_page(response="melon")
        bots[1].take_page(response="shrimp")
        bots[2].take_page(response="soup")
        advance_past_wait_pages(bots)

        # RATE 3
        bots[0].take_page(response="soup")
        bots[1].take_page(response="soup")
        bots[2].take_page(response="melon")
        advance_past_wait_pages(bots)

        texts = [bot.current_page_text for bot in bots]
        assert texts[0] == "You chose soup, your partners chose melon and soup."
        assert texts[1] == "You chose soup, your partners chose melon and soup."
        assert texts[2] == "You chose melon, your partners chose soup and soup."

        bots[0].take_page()
        bots[1].take_page()
        bots[2].take_page()
        advance_past_wait_pages(bots)

        texts = [bot.current_page_text for bot in bots]
        for text in texts:
            assert "That's the end!" in text

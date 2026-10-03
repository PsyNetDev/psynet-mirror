import random
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.modular_page import ModularPage, PushButtonControl, TextControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import CodeBlock, PageMaker, Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

# Overview #####################################################################

# This experiment implements a synchronous create and rate task. Groups of three participants
# are created. In each trial, each participant is first asked to type the name of a food item.
# In a second phase of each trial, each participant chooses between the food items given by
# the other two participants, and is then informed about the choices made by the other participants.

# #############################################################################


class CreateRateTrialMaker(StaticTrialMaker):
    pass


class CreateRateTrial(StaticTrial):
    time_estimate = 5
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

    def create(self):
        prompt = f"Type something you can have as {self.definition['target']}:"
        return join(
            ModularPage(
                "create",
                prompt,
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
                prompt,
                PushButtonControl(
                    choices=self.find_creations(participant),
                ),
                time_estimate=5,
                save_answer="rate",
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
        prompt = (
            f"You chose {participant.var.last_trial['rating_self']}, "
            + f"your partners chose {participant.var.last_trial['rating_others'][0]} and {participant.var.last_trial['rating_others'][1]}. "
        )

        return InfoPage(
            prompt,
            time_estimate=5,
        )

    def save_ratings(self, participants: List[Participant]):
        assert len(participants) == 3

        ratings = [p.var.rate for p in participants]

        for i in range(len(participants)):
            participants[i].var.last_trial = {
                "rating_self": ratings[i],
                "rating_others": sorted(ratings[:i] + ratings[i + 1 :]),
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

import time
from typing import List

import psynet.experiment
from psynet.bot import BotDriver
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.sync import SimpleGrouper
from psynet.timeline import PageMaker, Timeline, conditional, for_loop, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

nodes = [
    StaticNode(
        definition={"animal": animal},
    )
    for animal in ["cats", "dogs", "fish", "ponies", "zebras", "giraffes"]
]


class AnimalTrial(StaticTrial):
    time_estimate = 3

    def show_trial(self, experiment, participant):
        return ModularPage(
            "animal_trial",
            f"While we are waiting for other participants, please tell us: How much do you like {self.definition['animal']}?",
            PushButtonControl(
                ["Not at all", "A little", "Very much"],
            ),
        )


trial_maker = StaticTrialMaker(
    id_="animals",
    trial_class=AnimalTrial,
    nodes=nodes,
    expected_trials_per_participant=6,
    max_trials_per_participant=99,
    allow_repeated_nodes=True,
)


def show_quorum(participant):
    return ModularPage(
        "quorate",
        # Nobody waits at a barrier here, so there is nothing to tick.
        GroupPrompt(
            # No count here: the group display updates as people join and leave.
            "We are now quorate. These participants are present:",
            participant=participant,
            names="shown",
            show_progress=False,
        ),
        time_estimate=5,
    )


filler = PageMaker(trial_maker.cue_trial, time_estimate=AnimalTrial.time_estimate)


class Exp(psynet.experiment.Experiment):
    label = "Quorum experiment"

    timeline = Timeline(
        InfoPage(
            (
                "This demo demonstrates an experiment that operates with a quorum. "
                "In particular, there is a central part of the timeline that participants "
                "can only access once sufficiently many other participants are present at "
                "the same time. This would be useful for e.g. a multiplayer game. "
                "While participants are waiting for other participants, they take trials "
                "from another trial maker, so they don't waste their time."
            ),
            time_estimate=5,
        ),
        trial_maker.custom(
            SimpleGrouper(
                "quorum",
                initial_group_size=3,
                max_group_size=None,
                quorum=3,
                join_existing_groups=True,
                waiting_logic=filler,
                expected_wait=10 * AnimalTrial.time_estimate,
                max_wait_time=120,
            ),
            for_loop(
                label="quorate",
                iterate_over=range(
                    3
                ),  # Participant will only be allowed to visit the quorate page 3 times
                logic=join(
                    conditional(
                        "check_quorate",
                        condition=lambda participant: (
                            participant.sync_group.n_active_participants
                            >= participant.sync_group.quorum
                        ),
                        logic_if_true=PageMaker(show_quorum, time_estimate=5),
                        logic_if_false=filler,
                    ),
                ),
            ),
        ),
    )

    test_n_bots = 5

    def test_serial_run_bots(self, bots: List[BotDriver]):
        assert isinstance(bots[0].get_current_page(), InfoPage)
        bots[0].take_page()
        assert bots[0].get_current_page().label == "animal_trial"
        bots[0].take_page()
        assert bots[0].get_current_page().label == "animal_trial"

        assert isinstance(bots[1].get_current_page(), InfoPage)
        bots[1].take_page()
        assert bots[1].get_current_page().label == "animal_trial"

        assert isinstance(bots[2].get_current_page(), InfoPage)
        bots[2].take_page()

        # Currently barriers are checked in a background process, so
        # a participant should never be released instantly from a grouper,
        # even if they are the last participant to arrive.
        # We may change this in due course, once we're satisfied we're not going
        # to run into deadlocks.

        page = bots[2].get_current_page()
        if isinstance(page, ModularPage) and page.label == "animal_trial":
            # 2 seconds should be enough for the background process to run once
            time.sleep(2)
            bots[2].take_page()

        assert bots[2].current_page_label == "quorate"
        assert "We are now quorate." in bots[2].current_page_text
        assert bots[2].sync_group_n_active_participants == 3

        for bot in [bots[0], bots[1]]:
            bot.take_page()
            assert "We are now quorate." in bot.current_page_text
            assert bot.sync_group_n_active_participants == 3

        bots[0].drop_out()

        for bot in [bots[1], bots[2]]:
            bot.take_page()
            page = bot.get_current_page()
            assert page.label == "animal_trial"

        # Bring in a new bot to join the group
        bots[3].take_page()

        # As before, because of the background processes, bot 3 will probably need to
        # take one trial before they can continue.
        page = bots[3].get_current_page()
        if isinstance(page, ModularPage) and page.label == "animal_trial":
            time.sleep(2)
            bots[3].take_page()

        assert "We are now quorate." in bots[3].current_page_text
        assert bots[3].sync_group_n_active_participants == 3

        # If we bring in a 5th participant, they should be able to join the main room right away.
        assert isinstance(bots[4].get_current_page(), InfoPage)
        bots[4].take_page()
        assert "We are now quorate." in bots[4].current_page_text
        assert bots[4].sync_group_n_active_participants == 4

        for bot in [bots[1], bots[2], bots[3]]:
            bot.run_to_completion(render_pages=True)

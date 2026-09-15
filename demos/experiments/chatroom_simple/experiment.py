"""Simple chatroom demo.

A minimal real-time chat experiment built with PsyNet's high-level chatroom
component (:class:`~psynet.chatroom.EnableChatrooms` and
:class:`~psynet.chatroom.ChatRoom`). Participants are grouped into pairs with a
:class:`~psynet.sync.SimpleGrouper` and a synchronised trial maker, then placed
together in a shared chatroom where they exchange messages in real time.

This delivers the same core functionality as the lower-level
``demos/features/websocket_chatroom`` demo (two participants chatting in a
shared, persisted room with a live participant list), but with almost no custom
code: the chatroom UI, message persistence, history replay, and occupancy
tracking are all provided by the built-in ``ChatRoom`` component. The structure
mirrors the rock-paper-scissors chatroom demo, minus the game logic.
"""

from typing import List

from dominate import tags

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.chatroom import ChatRoom, EnableChatrooms
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger

logger = get_logger()

GROUP_TYPE = "chat"


class ChatTrialMaker(StaticTrialMaker):
    pass


class ChatTrial(StaticTrial):
    time_estimate = 60

    def show_trial(self, experiment, participant):
        return join(
            GroupBarrier(
                id_="wait_for_partner",
                group_type=GROUP_TYPE,
            ),
            self.chat_page(topic=self.definition["topic"]),
        )

    def chat_page(self, topic):
        prompt = tags.div()
        with prompt:
            tags.h1("Chatroom")
            tags.p(f"Discuss the following topic with your partner: {topic}")

        # The room_id is derived from this trial's sync group
        # (``self.sync_group``), not from ``participant.sync_group``.
        # ``self.sync_group`` always resolves to the group matching this trial
        # maker's ``sync_group_type``, so it is safe even when a participant is a
        # member of multiple sync groups. Both partners share the same
        # ``self.sync_group.id`` and therefore meet in the same room.
        return ModularPage(
            "chat",
            prompt,
            chatroom=ChatRoom(
                room_id=f"chat_room_{self.sync_group.id}",
                show_participants=True,
                show_history=True,
            ),
            time_estimate=60,
        )


class Exp(psynet.experiment.Experiment):
    label = "Simple chatroom demo"

    timeline = Timeline(
        EnableChatrooms(),
        SimpleGrouper(
            group_type=GROUP_TYPE,
            initial_group_size=2,
        ),
        ChatTrialMaker(
            id_="chat",
            trial_class=ChatTrial,
            nodes=[
                StaticNode(definition={"topic": topic})
                for topic in [
                    "your favourite food",
                    "the best film you have seen recently",
                ]
            ],
            expected_trials_per_participant=1,
            max_trials_per_participant=1,
            sync_group_type=GROUP_TYPE,
        ),
        InfoPage("That's the end of the experiment!", time_estimate=5),
    )

    test_n_bots = 2
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        advance_past_wait_pages(bots)

        for bot in bots:
            assert bot.current_page_label == "chat"
            page = bot.get_current_page()
            assert isinstance(page, ModularPage)
            assert isinstance(page.chatroom, ChatRoom)
            assert page.chatroom.show_participants is True
            assert page.chatroom.show_history is True

        # Both partners must be assigned to the same chatroom.
        assert (
            bots[0].get_current_page().chatroom.room_id
            == bots[1].get_current_page().chatroom.room_id
        )

        bots[0].take_page()
        bots[1].take_page()
        advance_past_wait_pages(bots)

        assert "That's the end of the experiment!" in bots[0].current_page_text
        assert "That's the end of the experiment!" in bots[1].current_page_text

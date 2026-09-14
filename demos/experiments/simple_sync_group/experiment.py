import random
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.page import InfoPage, WaitPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, GroupCloser, SimpleGrouper, SyncGroup
from psynet.timeline import PageMaker, Timeline
from psynet.utils import get_logger

logger = get_logger()

ROLE_SETS = {
    2: ["speaker", "listener"],
    3: ["speaker", "listener", "observer"],
}


def waiting_page(participant: Participant):
    active_barrier = next(iter(participant.active_barriers.values()), None)
    if active_barrier:
        all_participants = active_barrier.get_waiting_participants()
        all_participants.sort(key=lambda p: p.id)
        all_participant_ids = [str(participant.id) for participant in all_participants]
        content = (
            "Waiting for more participants to arrive. "
            f"IDs of currently waiting participants: {', '.join(all_participant_ids)}."
        )
    else:
        content = "Ready to go!"
    return WaitPage(content=content, wait_time=2.5)


def assign_roles(group: SyncGroup, participants: List[Participant]):
    roles = ROLE_SETS[len(participants)]
    random.shuffle(roles)
    if len(roles) != len(participants):
        raise ValueError(
            f"Number of roles ({len(roles)}) must match number of participants "
            f"({len(participants)})."
        )
    for participant, role in zip(participants, roles):
        participant.var.role = role


def format_group_message(participant: Participant) -> str:
    ordered_participants = sorted(
        participant.sync_group.active_participants, key=lambda p: p.id
    )
    participants_text = ", ".join(
        [
            f"{participant.id} ({participant.var.role})"
            for participant in ordered_participants
        ]
    )
    return (
        f"You are now in group {participant.sync_group.id} with participants "
        f"{participants_text}"
    )


def show_current_group():
    return PageMaker(
        lambda participant: InfoPage(
            format_group_message(participant),
        ),
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Simple SyncGroup demo"

    timeline = Timeline(
        SimpleGrouper(
            group_type="main",
            id_="main_grouper_of_3",
            initial_group_size=3,
            waiting_logic=PageMaker(waiting_page, time_estimate=5),
            max_wait_time=20,
        ),
        GroupBarrier(
            id_="assign_roles_first",
            group_type="main",
            content="Waiting for everyone in your group",
            on_release=assign_roles,
        ),
        show_current_group(),
        GroupCloser(group_type="main"),
        SimpleGrouper(
            group_type="main",
            id_="main_grouper_of_2",
            initial_group_size=2,
            waiting_logic=PageMaker(waiting_page, time_estimate=5),
            max_wait_time=20,
        ),
        GroupBarrier(
            id_="assign_roles_second",
            group_type="main",
            content="Waiting for everyone in your group",
            on_release=assign_roles,
        ),
        show_current_group(),
    )

    test_n_bots = 6
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        advance_past_wait_pages(bots)

        for bot in bots:
            assert bot.current_page_text.startswith("You are now in group")

        first_groups = SyncGroup.query.filter_by(active=True).all()
        assert len(first_groups) == 2
        for group in first_groups:
            assert group.n_active_participants == 3
            assert len(group.participants) == 3
            expected_roles = ROLE_SETS[3]
            assigned_roles = {
                participant.var.role for participant in group.active_participants
            }
            assert assigned_roles == set(expected_roles)

        for bot in bots:
            bot.take_page()

        advance_past_wait_pages(bots)

        for bot in bots:
            assert bot.current_page_text.startswith("You are now in group")
            assert bot.sync_group_n_active_participants == 2

        second_groups = SyncGroup.query.filter_by(active=True).all()
        assert len(second_groups) == 3
        for group in second_groups:
            assert group.n_active_participants == 2
            expected_roles = ROLE_SETS[2]
            assigned_roles = {
                participant.var.role for participant in group.active_participants
            }
            assert assigned_roles == set(expected_roles)

        for bot in bots:
            bot.run_to_completion()

"""Form groups of three, then regroup the same participants into pairs.

A :class:`~psynet.sync.SimpleGrouper` forms groups of three, a barrier gives
each member a role, and a page shows the group. A
:class:`~psynet.sync.GroupCloser` then ends those groups, and a second
grouper of the same ``group_type`` forms pairs, which get roles in the same way.
"""

import random
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, GroupCloser, SimpleGrouper, SyncGroup
from psynet.timeline import PageMaker, Timeline

GROUP = "main"
ROLE_SETS = {
    2: ["speaker", "listener"],
    3: ["speaker", "listener", "observer"],
}


def assign_roles(participants: List[Participant]):
    roles = random.sample(ROLE_SETS[len(participants)], len(participants))
    for participant, role in zip(participants, roles):
        participant.var.role = role


def format_group_message(participant: Participant) -> str:
    ordered_participants = sorted(
        participant.sync_group.active_participants, key=lambda p: p.id
    )
    participants_text = ", ".join(
        [
            f"{member.pseudonym.name} ({member.var.role})"
            for member in ordered_participants
        ]
    )
    return f"You are now in a group with {participants_text}."


def show_current_group():
    return PageMaker(
        lambda participant: ModularPage(
            "current_group",
            GroupPrompt(
                format_group_message(participant),
                participant=participant,
                # Each member's role in their speech bubble.
                answers={
                    p.id: p.var.role for p in participant.sync_group.active_participants
                },
                names="shown",
            ),
        ),
        time_estimate=5,
    )


class Exp(psynet.experiment.Experiment):
    label = "Simple SyncGroup demo"

    timeline = Timeline(
        SimpleGrouper(
            group_type=GROUP,
            initial_group_size=3,
            quorum=3,
            waiting_message="Waiting for more participants to arrive",
            max_wait_time=20,
        ),
        GroupBarrier(
            id_="assign_roles_first",
            group_type=GROUP,
            waiting_message="Waiting for everyone in your group",
            on_release=assign_roles,
        ),
        show_current_group(),
        GroupCloser(group_type=GROUP),
        SimpleGrouper(
            group_type=GROUP,
            initial_group_size=2,
            waiting_message="Waiting for more participants to arrive",
            max_wait_time=20,
        ),
        GroupBarrier(
            id_="assign_roles_second",
            group_type=GROUP,
            waiting_message="Waiting for everyone in your group",
            on_release=assign_roles,
        ),
        show_current_group(),
    )

    test_n_bots = 6
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        advance_past_wait_pages(bots)

        for bot in bots:
            assert bot.current_page_text.startswith("You are now in a group with")

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
            assert bot.current_page_text.startswith("You are now in a group with")
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

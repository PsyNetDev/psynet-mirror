"""Lowest unique number: a round-based game where latecomers sit out a round.

Every ``ROUND_SECONDS`` the :class:`~psynet.sync.Regrouper` puts everyone who
is waiting into rooms of at most ``ROOM_SIZE`` players. Each player picks a
number, and the lowest number that nobody else in the room picked wins.

The choice page has a ``time_limit`` of ``CHOICE_SECONDS``. A player who
doesn't choose in time sits out the round and joins the next one, so the rest
of the room isn't held up. A player who leaves the page, for example by
closing the tab, is removed from their room ``LEFT_PAGE_SECONDS`` later.
Missing a round doesn't fail anyone. A player who comes back after the
others' last round has started waits alone, though, and is failed once they
reach the regrouper's ``max_wait_time`` (300 s by default), as at any barrier.

To keep the same people together across rounds, for example in teams, form
the teams first and regroup within them::

    SimpleGrouper(
        "team", initial_group_size=8, min_group_size=2,
        start_short_after=60, max_wait_time=300,
    ),
    ...
    Regrouper("room", within="team", group_size=4, deadline=30),

See the ``ultimatum_pairing`` demo for a full example.
"""

import time
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import Clock, GroupBarrier, Regrouper
from psynet.timeline import (
    TIME_LIMIT_GRACE_SECONDS,
    PageMaker,
    Timeline,
    for_loop,
    join,
)

ROUND_SECONDS = 10
CHOICE_SECONDS = 15
# Extra seconds before a player who left the choice page is removed from their room.
LEFT_PAGE_SECONDS = 15
ROOM_SIZE = 8
N_ROUNDS = 2
NUMBERS = [1, 2, 3, 4, 5]
WAIT_TIMEOUT = ROUND_SECONDS + CHOICE_SECONDS + LEFT_PAGE_SECONDS + 10


def lowest_unique(choices: dict):
    """Return the lowest number chosen exactly once, or ``None``."""
    numbers = list(choices.values())
    unique = [n for n in numbers if numbers.count(n) == 1]
    return min(unique, default=None)


def score_round(participants: List[Participant]):
    """Record the room's choices and winning number for every player in the room.

    Players who ran out of time have no choice and sit out the round.
    """
    choices = {p.id: p.var.choice for p in participants if p.var.choice is not None}
    winner = lowest_unique(choices)
    for participant in participants:
        participant.var.last_round = {
            "choices": sorted(choices.values()),
            "choice_by_player": choices,
            "winning_number": winner,
            "won": winner is not None and choices.get(participant.id) == winner,
        }


def round_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player."
    return "The next round starts in {SECONDS} s."


def choose_number(participant):
    return ModularPage(
        "choose",
        # Ticks appear as the others choose.
        GroupPrompt(
            "Pick a number.",
            participant=participant,
            group_type="room",
        ),
        PushButtonControl(choices=NUMBERS, arrange_vertically=False),
        save_answer="choice",
        time_limit=CHOICE_SECONDS,
        time_estimate=5,
    )


def your_pick(participant):
    """Replace the number buttons with the player's pick while the rest of the room chooses."""
    if participant.var.choice is None:
        text = "You ran out of time, so you'll sit out this round."
    else:
        text = f"You picked {participant.var.choice}."
    # Ticks appear as the others choose.
    return GroupPrompt(
        text,
        participant=participant,
        group_type="room",
    )


def show_result(participant):
    if "room" not in participant.active_sync_groups or participant.var.choice is None:
        return InfoPage(
            "You ran out of time, so you sat out this round.", time_estimate=5
        )
    result = participant.var.last_round
    winner = result["winning_number"]
    if winner is None:
        outcome = "Nobody picked a unique number, so nobody won."
    elif result["won"]:
        outcome = f"You won with {winner}!"
    else:
        outcome = f"The winning number was {winner}."
    choices = result["choice_by_player"]
    picks = list(choices.values())
    highlight = {
        pid: "winner" if n == winner else "duplicate"
        for pid, n in choices.items()
        if n == winner or picks.count(n) > 1
    }
    return ModularPage(
        "result",
        GroupPrompt(
            f"The room picked {', '.join(map(str, result['choices']))}. {outcome}",
            participant=participant,
            group_type="room",
            answers=choices,
            highlight=highlight,
        ),
        time_estimate=5,
    )


def play_round():
    return join(
        Regrouper(
            "room",
            group_size=ROOM_SIZE,
            min_group_size=2,
            deadline=Clock(ROUND_SECONDS),
            content=round_message,
            waiting_screen="Getting the next round ready.",
        ),
        PageMaker(choose_number, time_estimate=5),
        GroupBarrier(
            id_="round_finished",
            group_type="room",
            content="Waiting for the rest of the room…",
            waiting_screen=your_pick,
            timeout_between_barriers_time=CHOICE_SECONDS + LEFT_PAGE_SECONDS,
            timeout_between_barriers_action="kick",
            on_release=score_round,
        ),
        PageMaker(show_result, time_estimate=5),
    )


class Exp(psynet.experiment.Experiment):
    label = "Lowest unique number demo"

    timeline = Timeline(
        InfoPage(
            "In each round, pick a number. The lowest number that nobody else "
            "in your room picked wins.",
            time_estimate=5,
        ),
        for_loop(
            label="rounds",
            iterate_over=range(N_ROUNDS),
            logic=play_round(),
            expected_repetitions=N_ROUNDS,
        ),
    )

    test_n_bots = 3
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        assert [bot.current_page_label for bot in bots] == ["choose"] * 3

        # The third player doesn't choose in time, so their late answer
        # counts as no choice and they sit out the round.
        bots[0].take_page(response=1)
        bots[1].take_page(response=2)
        time.sleep(CHOICE_SECONDS + TIME_LIMIT_GRACE_SECONDS + 1)
        bots[2].take_page(response=1)
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        assert "You won with 1!" in bots[0].current_page_text
        assert "The room picked 1, 2." in bots[1].current_page_text
        assert "sat out this round" in bots[2].current_page_text

        # Next round, the third player is back in the room.
        for bot in bots:
            bot.take_page()
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        bots[0].take_page(response=3)
        bots[1].take_page(response=3)
        bots[2].take_page(response=4)
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        assert "You won with 4!" in bots[2].current_page_text
        assert "The room picked 3, 3, 4." in bots[0].current_page_text

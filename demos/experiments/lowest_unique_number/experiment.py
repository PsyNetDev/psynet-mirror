"""Lowest unique number: a round-based game where latecomers miss a round.

Every ``ROUND_SECONDS`` the :class:`~psynet.sync.Regrouper` puts everyone who
is waiting into rooms of at most ``ROOM_SIZE`` players. Each player picks a
number, and the lowest number that nobody else in the room picked wins.

The choice page has a ``time_limit`` of ``CHOICE_SECONDS``. A player who
doesn't choose in time misses the round and joins the next one, so the rest
of the room isn't held up. A player who leaves the page, for example by
closing the tab, is removed from their room 30 s after the room forms, or
10 s after the time limit if that is later.
Missing a round doesn't fail anyone. A player who comes back after the
others' last round has started waits alone, though, and is failed once they
reach the regrouper's ``max_wait_time`` (300 s by default), as at any barrier.

To keep the same people together across rounds, for example in cohorts, form
the cohorts first and regroup within them::

    SimpleGrouper(
        "cohort", initial_group_size=8, quorum=2,
        start_short_after=60, max_wait_time=300,
    ),
    ...
    Regrouper("room", within="cohort", group_size=4, deadline=30),

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
from psynet.sync import (
    GroupBarrier,
    Regrouper,
    SyncGroup,
    group_rounds,
    participant_rounds,
)
from psynet.timeline import (
    PageMaker,
    Timeline,
    for_loop,
    join,
)

ROUND_SECONDS = 10
CHOICE_SECONDS = 15
ROOM_SIZE = 8
N_ROUNDS = 2
NUMBERS = [1, 2, 3, 4, 5]
WIN_BONUS = 0.10
WAIT_TIMEOUT = ROUND_SECONDS + CHOICE_SECONDS + 20


def lowest_unique(choices: dict):
    """Return the lowest number chosen exactly once, or ``None``."""
    numbers = list(choices.values())
    unique = [n for n in numbers if numbers.count(n) == 1]
    return min(unique, default=None)


def score_round(group: SyncGroup, participants: List[Participant]):
    """Record the room's choices and winning number, and pay the winner a bonus.

    Players who ran out of time have no choice and miss the round.
    Nobody wins when only one player chose.
    """
    # String keys, as the record stores them.
    choices = {
        str(p.id): p.var.choice for p in participants if p.var.choice is not None
    }
    winner = lowest_unique(choices) if len(choices) > 1 else None
    group.record_round(choices=choices, winning_number=winner)
    for participant in participants:
        won = winner is not None and participant.var.choice == winner
        participant.record_round(
            bonus=WIN_BONUS if won else 0.0,
            choice=participant.var.choice,
        )


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
        text = "You ran out of time, so you'll miss this round."
    else:
        text = f"You picked {participant.var.choice}."
    # Ticks appear as the others choose.
    return GroupPrompt(
        text,
        participant=participant,
        group_type="room",
    )


def show_result(participant):
    if not participant.in_sync_group("room"):
        return InfoPage(
            "You were away for too long, so you missed this round.", time_estimate=5
        )
    if participant.var.choice is None:
        return InfoPage(
            "You ran out of time, so you missed this round.", time_estimate=5
        )
    # The round the player just played: the next one can't start for them
    # until they leave this page.
    room = group_rounds("round_finished", participant)[-1]
    choices, winner = room["choices"], room["winning_number"]
    picks = sorted(choices.values())
    if len(picks) == 1:
        return InfoPage(
            "Nobody else in your room picked a number in time, so nobody won this round.",
            time_estimate=5,
        )
    if winner is None:
        outcome = "Nobody picked a unique number, so nobody won."
    elif participant.var.choice == winner:
        outcome = f"You won with {winner}! You earn ${WIN_BONUS:.2f}."
    else:
        outcome = f"The winning number was {winner}."
    highlight = {
        pid: "winner" if n == winner else "duplicate"
        for pid, n in choices.items()
        if n == winner or picks.count(n) > 1
    }
    return ModularPage(
        "result",
        GroupPrompt(
            f"The room picked {', '.join(map(str, picks))}. {outcome}",
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
            smallest_group=2,
            every=ROUND_SECONDS,
            waiting_message=round_message,
            waiting_screen="Getting the next round ready.",
        ),
        PageMaker(choose_number, time_estimate=5),
        GroupBarrier(
            id_="round_finished",
            group_type="room",
            waiting_message="Waiting for the rest of the room…",
            waiting_screen=your_pick,
            # A player is taken out 30 s after the round starts (long enough
            # for a background tab to notice), but not while their answer to
            # the timed choice page may still be on its way.
            late_after=30,
            late_action="leave_group",
            on_release=score_round,
            record_rounds=True,
        ),
        PageMaker(show_result, time_estimate=5),
    )


def _arrive_together(bots):
    """Take each bot's page to the regrouper between the same two ticks.

    A tick between two arrivals would form a room without the later bots, and
    a bot left alone never gets a room.
    """
    seconds_to_tick = ROUND_SECONDS - time.time() % ROUND_SECONDS
    if seconds_to_tick < 3:
        time.sleep(seconds_to_tick + 0.1)
    for bot in bots:
        bot.take_page()


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

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round, with the bonus it paid, and one per room per round."""
        return {
            "player_round": participant_rounds("round_finished"),
            "group_round": group_rounds("round_finished"),
        }

    test_n_bots = 3
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        _arrive_together(bots)
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        assert [bot.current_page_label for bot in bots] == ["choose"] * 3

        # The third player doesn't choose in time, so they miss the round.
        bots[0].take_page(response=1)
        bots[1].take_page(response=2)
        bots[2].run_out_of_time()
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        assert "You won with 1!" in bots[0].current_page_text
        assert "The room picked 1, 2." in bots[1].current_page_text
        assert "missed this round" in bots[2].current_page_text

        # Next round, the third player is back in the room.
        _arrive_together(bots)
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        bots[0].take_page(response=3)
        # While the others choose, the waiting screen shows the player's pick.
        advance_past_wait_pages(
            bots[:1], stop_at="round_finished", timeout=WAIT_TIMEOUT
        )
        assert "You picked 3." in bots[0].current_page_text
        bots[1].take_page(response=3)
        bots[2].take_page(response=4)
        advance_past_wait_pages(bots, timeout=WAIT_TIMEOUT)
        assert "You won with 4!" in bots[2].current_page_text
        assert "The room picked 3, 3, 4." in bots[0].current_page_text

        data = self.get_basic_data()
        rooms = data["group_round"]
        assert [
            (r["round"], sorted(r["choices"].values()), r["winning_number"])
            for r in rooms
        ] == [
            (1, [1, 2], 1),
            (2, [3, 3, 4], 4),
        ], rooms
        rows = data["player_round"]
        assert [(r["round"], r["choice"], r["bonus"]) for r in rows] == [
            (1, 1, WIN_BONUS),
            (1, 2, 0.0),
            (1, None, 0.0),
            (2, 3, 0.0),
            (2, 3, 0.0),
            (2, 4, WIN_BONUS),
        ], rows

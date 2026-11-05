"""Lowest unique number: a round-based game where latecomers sit out a round.

Every ``ROUND_SECONDS`` the :class:`~psynet.sync.Regrouper` puts everyone who
is waiting into rooms of at most ``ROOM_SIZE`` players. Each player picks a
number, and the lowest number that nobody else in the room picked wins.

A player who doesn't choose within ``CHOICE_SECONDS`` is removed from their
room, so the rest of the room isn't held up, and joins the next round
instead. Nobody is failed for missing a round.

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
from psynet.bot import BotDriver
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import Clock, GroupBarrier, Regrouper
from psynet.timeline import PageMaker, Timeline, for_loop, join

ROUND_SECONDS = 10
CHOICE_SECONDS = 15
ROOM_SIZE = 8
N_ROUNDS = 2
NUMBERS = [1, 2, 3, 4, 5]


def lowest_unique(choices: dict):
    """Return the lowest number chosen exactly once, or ``None``."""
    numbers = list(choices.values())
    unique = [n for n in numbers if numbers.count(n) == 1]
    return min(unique, default=None)


def score_round(participants: List[Participant]):
    """Record the room's choices and winning number for every player in the room."""
    choices = {p.id: p.var.choice for p in participants}
    winner = lowest_unique(choices)
    for participant in participants:
        participant.var.last_round = {
            "choices": sorted(choices.values()),
            "choice_by_player": choices,
            "winning_number": winner,
            "won": winner is not None and choices[participant.id] == winner,
        }


def choose_number(participant):
    # The page is rebuilt on submit, when a player who ran out of time has
    # already left the room.
    room = participant.active_sync_groups.get("room")
    text = f"Pick a number. You have {CHOICE_SECONDS} seconds."
    prompt = text
    if room is not None:
        others = len(room.participants) - 1
        text = (
            f"You're in a room with {others} other player{'s' * (others != 1)}. {text}"
        )
        # Ticks appear as the others choose.
        prompt = GroupPrompt(text, group=room, participant=participant)
    return ModularPage(
        "choose",
        prompt,
        PushButtonControl(choices=NUMBERS, arrange_vertically=False),
        save_answer="choice",
        time_estimate=5,
    )


def show_result(participant):
    if "room" not in participant.active_sync_groups:
        return InfoPage(
            "You ran out of time, so you sat out this round. You'll join the next one.",
            time_estimate=5,
        )
    result = participant.var.last_round
    winner = result["winning_number"]
    if winner is None:
        outcome = "Nobody picked a unique number, so nobody won."
    elif result["won"]:
        outcome = f"You won with {winner}!"
    else:
        outcome = f"The winning number was {winner}."
    # Stored vars are JSON, so the player IDs are strings here.
    choices = {int(pid): n for pid, n in result["choice_by_player"].items()}
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
            group=participant.active_sync_groups["room"],
            participant=participant,
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
            # Players who switched to another tab sit the round out.
            active_within=10,
            content="The next round starts in {SECONDS} s.",
        ),
        PageMaker(choose_number, time_estimate=5),
        GroupBarrier(
            id_="round_finished",
            group_type="room",
            content="Waiting for the rest of the room…",
            timeout_between_barriers_time=CHOICE_SECONDS,
            timeout_between_barriers_action="kick",
            skip_if_not_in_group=True,
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
        _wait_while_held(bots)
        assert [bot.current_page_label for bot in bots] == ["choose"] * 3
        assert "You're in a room with 2 other players." in bots[0].current_page_text

        # The third player doesn't choose in time, so the room goes ahead without them.
        bots[0].take_page(response=1)
        bots[1].take_page(response=2)
        _wait_while_held(bots[:2])
        assert "You won with 1!" in bots[0].current_page_text
        assert "The room picked 1, 2." in bots[1].current_page_text

        bots[2].take_page(response=1)
        assert "sat out this round" in bots[2].current_page_text

        # Next round, the third player is back in the room.
        for bot in bots:
            bot.take_page()
        _wait_while_held(bots)
        bots[0].take_page(response=3)
        bots[1].take_page(response=3)
        bots[2].take_page(response=4)
        _wait_while_held(bots)
        assert "You won with 4!" in bots[2].current_page_text
        assert "The room picked 3, 3, 4." in bots[0].current_page_text


def _wait_while_held(bots, timeout=ROUND_SECONDS + CHOICE_SECONDS + 10):
    """Poll until no bot is on a waiting screen, as a browser would."""
    deadline = time.monotonic() + timeout
    while True:
        held = []
        for bot in bots:
            bot.refresh_status()
            if getattr(bot.get_current_page(), "is_timeline_hold", False):
                held.append(bot)
                bot.take_page()
        if not held:
            return
        if time.monotonic() > deadline:
            raise RuntimeError(f"Bots {[b.id for b in held]} are still waiting.")
        time.sleep(0.5)

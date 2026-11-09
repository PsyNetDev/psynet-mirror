"""Lowest unique number: a round-based game where latecomers miss a round.

Every ``ROUND_SECONDS`` the :class:`~psynet.sync.Regrouper` puts everyone who
is waiting into rooms of at most ``ROOM_SIZE`` players. Each player picks a
number, and the lowest number that nobody else in the room picked wins
``WIN_BONUS``.

Each round is one cued ``PickTrial`` per player. Because the trial class has
``sync_group_type = "room"``, the trials of a room's players share a node: the
room's results go in ``trial.node.var`` and each player's in ``trial.var``, and
``get_basic_data`` reads both back. The regrouper forms new rooms every round,
so every room plays only its round 0. A room can mix players at different
rounds of the game, for example a latecomer playing their first round with
others playing their second, so the export numbers each player's own rounds.

The choice page has a ``time_limit`` of ``CHOICE_SECONDS``. A player who
doesn't choose in time misses the round and joins the next one, so the rest
of the room isn't held up. A player who leaves the page, for example by
closing the tab, is removed from their room 30 s after the room forms, or
10 s after the time limit if that is later.
Missing a round doesn't fail anyone. A player left with nobody to play
with, for example one who comes back after the others' last round has
started, waits at the regrouper for up to ``MAX_WAIT_SECONDS``, then skips
that round with a short message (``max_wait_action="continue_without_group"``
and a ``conditional``) instead of being failed.

To keep the same people together across rounds, form cohorts first and
regroup within them (``Regrouper("room", within="cohort", ...)``); see the
``ultimatum_pairing`` demo.
"""

import time
from typing import List

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.sync import GroupBarrier, Regrouper
from psynet.timeline import Module, Timeline, conditional, for_loop, join
from psynet.trial.main import SyncGroupNode, Trial

ROUND_SECONDS = 10
CHOICE_SECONDS = 15
ROOM_SIZE = 8
N_ROUNDS = 2
NUMBERS = [1, 2, 3, 4, 5]
WIN_BONUS = 0.10
WAIT_TIMEOUT = ROUND_SECONDS + CHOICE_SECONDS + 20
# Longer than the others can take to finish a round (the choice page plus the
# barrier's late_after) and reach the next split. The feedback pages have no
# time_limit, so a latecomer can still skip a round while the others read
# their results.
MAX_WAIT_SECONDS = 60


def get_timeline():
    return Timeline(
        InfoPage(
            "In each round, pick a number. The lowest number that nobody else "
            "in your room picked wins.",
            time_estimate=5,
        ),
        Module(
            "game",
            for_loop(
                label="rounds",
                iterate_over=range(N_ROUNDS),
                logic=join(
                    Regrouper(
                        "room",
                        group_size=ROOM_SIZE,
                        smallest_group=2,
                        every=ROUND_SECONDS,
                        waiting_message=round_message,
                        waiting_screen="Getting the next round ready.",
                        max_wait_time=MAX_WAIT_SECONDS,
                        max_wait_action="continue_without_group",
                    ),
                    conditional(
                        "in_room",
                        in_room,
                        PickTrial.cue({"numbers": NUMBERS}),
                        InfoPage(NO_ROOM_TEXT, time_estimate=5),
                    ),
                ),
                time_estimate_per_iteration=PickTrial.time_estimate + 5,
                expected_repetitions=N_ROUNDS,
            ),
        ),
    )


AWAY_TEXT = "You were away for too long, so you missed this round."
NO_ROOM_TEXT = "Nobody else was left to play this round with, so you skip it."


def in_room(participant):
    return participant.in_sync_group("room")


def lowest_unique(choices: dict):
    """Return the lowest number chosen exactly once, or ``None``."""
    numbers = list(choices.values())
    unique = [n for n in numbers if numbers.count(n) == 1]
    return min(unique, default=None)


def round_message(seconds_left):
    if seconds_left is None:
        return "Waiting for another player."
    return "The next round starts in {SECONDS} s."


class PickTrial(Trial):
    sync_group_type = "room"
    time_estimate = 15

    def show_trial(self, experiment, participant):
        return join(
            self.choose_number(participant),
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
                on_release=self.score_room,
            ),
        )

    def choose_number(self, participant):
        return ModularPage(
            "choose",
            # Ticks appear as the others choose.
            GroupPrompt(
                "Pick a number.", participant=participant, group=self.sync_group
            ),
            PushButtonControl(
                choices=self.definition["numbers"], arrange_vertically=False
            ),
            save_answer="choice",
            time_limit=CHOICE_SECONDS,
            time_estimate=5,
        )

    @classmethod
    def score_room(cls, trials: List["PickTrial"], node: SyncGroupNode):
        """Save the room's choices and winning number on the node, and whether each player won on their trial.

        The trials' answers are only saved once the trials end, after this
        barrier, so the choices are read from ``participant.var``. Players who
        ran out of time have no choice and miss the round. Nobody wins when
        only one player chose.
        """
        picks = {str(t.participant_id): t.participant.var.choice for t in trials}
        choices = {pid: n for pid, n in picks.items() if n is not None}
        winner = lowest_unique(choices) if len(choices) > 1 else None
        node.var.choices = choices
        node.var.winning_number = winner
        for trial in trials:
            trial.var.won = (
                winner is not None and picks[str(trial.participant_id)] == winner
            )

    def score_answer(self, answer, definition):
        return 1 if self.var.get("won") else 0

    def compute_performance_reward(self, score):
        return WIN_BONUS * score

    def show_feedback(self, experiment, participant):
        if not in_room(participant):
            # Taken out of the room mid-round by the barrier's late_after.
            return InfoPage(AWAY_TEXT, time_estimate=5)
        if self.answer is None:
            return InfoPage(
                "You ran out of time, so you missed this round.", time_estimate=5
            )
        choices, winner = self.node.var.choices, self.node.var.winning_number
        picks = sorted(choices.values())
        if len(picks) == 1:
            return InfoPage(
                "Nobody else in your room picked a number in time, so nobody won this round.",
                time_estimate=5,
            )
        if winner is None:
            outcome = "Nobody picked a unique number, so nobody won."
        elif self.var.won:
            outcome = f"You won with {winner}! You earn ${WIN_BONUS:.2f}."
        else:
            outcome = f"The winning number was {winner}."
        return ModularPage(
            "result",
            GroupPrompt(
                f"The room picked {', '.join(map(str, picks))}. {outcome}",
                participant=participant,
                group=self.sync_group,
                answers=choices,
                highlight={
                    pid: "winner" if n == winner else "duplicate"
                    for pid, n in choices.items()
                    if n == winner or picks.count(n) > 1
                },
            ),
            time_estimate=5,
        )


def your_pick(participant):
    """Replace the number buttons with the player's pick while the rest of the room chooses."""
    if participant.var.choice is None:
        text = "You ran out of time, so you'll miss this round."
    else:
        text = f"You picked {participant.var.choice}."
    # Ticks appear as the others choose.
    return GroupPrompt(text, participant=participant, group_type="room")


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

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round, from the trials, and one per room, from the nodes.

        A room can mix players at different rounds, so ``round`` counts each
        player's own trials from 0. Each room plays one round, so the room
        table has no round column.
        """
        rounds = {}
        player_rounds = []
        for t in PickTrial.query.order_by(PickTrial.id):
            rounds[t.participant_id] = rounds.get(t.participant_id, -1) + 1
            player_rounds.append((rounds[t.participant_id], t))
        rooms = SyncGroupNode.query.filter_by(module_id="game")
        return {
            "player_round": [
                {
                    "round": round_,
                    "room_id": t.sync_group_id,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    "choice": t.answer,
                    # None if the player was away too long to play the round.
                    "won": t.var.get("won"),
                    "bonus": t.performance_reward,
                }
                for round_, t in player_rounds
            ],
            "room": [
                {
                    "room_id": n.sync_group_id,
                    "node_id": n.id,
                    "choices": n.var.get("choices"),
                    "winning_number": n.var.get("winning_number"),
                }
                for n in rooms.order_by(SyncGroupNode.id)
            ],
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
        assert [
            (sorted(r["choices"].values()), r["winning_number"]) for r in data["room"]
        ] == [([1, 2], 1), ([3, 3, 4], 4)], data["room"]
        # Players cue their trials in their own order, so compare sorted rows.
        assert sorted(
            ((r["round"], r["choice"], r["bonus"]) for r in data["player_round"]),
            key=lambda row: (row[0], row[1] is None, row[1] or 0),
        ) == [
            (0, 1, WIN_BONUS),
            (0, 2, 0.0),
            (0, None, 0.0),
            (1, 3, 0.0),
            (1, 3, 0.0),
            (1, 4, WIN_BONUS),
        ], data["player_round"]

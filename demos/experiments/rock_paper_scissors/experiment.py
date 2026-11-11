"""Rock paper scissors for a fixed pair, with a chat after each round.

A ``SimpleGrouper`` pairs participants, and the pair plays ``N_ROUNDS``
rounds. In each round both players choose an action within
``CHOICE_SECONDS``, a barrier scores the round once both have chosen, and
both see the two actions and the winner, then chat about the round.

Each round is one cued ``RockPaperScissorsTrial`` per player, cued with the
loop value as ``round=`` because the pair stays together. Each player's
choice is their trial's answer. When the barrier releases the pair, it
saves on each player's trial the action they played, their partner's
action and the result, and the results page and the basic data read them
from there.

- A player who runs out of time gets a random action, so every round has a
  winner or a draw. Their answer stays ``None``; the action they played is
  saved with the result.
- The demo doesn't handle dropouts: a player whose partner goes silent
  waits up to ``PARTNER_WAIT_SECONDS`` at the next barrier and is then
  failed, as is a participant for whom no partner arrives in that time. A
  partner who is removed from the pair instead, for example by returning
  the study or being failed elsewhere, dissolves it at once, and the
  remaining player is failed with no wait. See ``public_goods`` for a game
  that carries on when players leave.
- Each trial's ``sync_group_outcome`` is ``"stayed"`` if the round was
  scored. Otherwise it records how the player left the pair, which doesn't
  always show who dropped out: when a partner goes silent, the player who
  waited for them is failed and leaves as ``"left_experiment"``, and the
  silent partner then leaves as ``"group_dissolved"``
  (https://gitlab.com/PsyNetDev/PsyNet/-/work_items/1162).
"""

import random
from typing import List

from dominate import tags

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.chatroom import ChatRoom, EnableChatrooms
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Module, Timeline, for_loop, join
from psynet.trial.main import Trial

GROUP = "rock_paper_scissors"
PARTNER_WAIT_SECONDS = 300
CHOICE_SECONDS = 20
N_ROUNDS = 3
ACTIONS = ["rock", "paper", "scissors"]
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
POINTS = {"won": 1, "drew": 0, "lost": -1}
RESULT_TEXTS = {"won": "You won!", "drew": "You drew.", "lost": "You lost."}


def get_timeline():
    return Timeline(
        EnableChatrooms(),
        SimpleGrouper(
            group_type=GROUP,
            initial_group_size=2,
            waiting_message="Waiting for your partner",
            max_wait_time=PARTNER_WAIT_SECONDS,
        ),
        Module(
            "game",
            for_loop(
                label="rounds",
                iterate_over=range(N_ROUNDS),
                logic=lambda i: RockPaperScissorsTrial.cue(round=i),
                time_estimate_per_iteration=RockPaperScissorsTrial.time_estimate,
            ),
        ),
    )


def _result(action, partner_action):
    """Return ``"won"``, ``"drew"`` or ``"lost"`` for the player who played ``action``."""
    if action == partner_action:
        return "drew"
    if BEATS[action] == partner_action:
        return "won"
    return "lost"


class RockPaperScissorsTrial(Trial):
    sync_group_type = GROUP
    time_estimate = 35

    def show_trial(self, experiment, participant):
        return join(
            self.choose_action(participant),
            GroupBarrier(
                id_="finished_trial",
                group_type=GROUP,
                waiting_message="Waiting for your partner",
                # Releasing the pair closes the round and scores it.
                on_release=self.score_round,
                max_wait_time=PARTNER_WAIT_SECONDS,
            ),
        )

    def choose_action(self, participant):
        return ModularPage(
            "choose_action",
            # A tick appears once the partner has chosen.
            GroupPrompt(
                "Choose your action:", group=self.sync_group, participant=participant
            ),
            PushButtonControl(choices=ACTIONS),
            time_estimate=5,
            # Running out of time saves None; score_round then plays a random action.
            time_limit=CHOICE_SECONDS,
        )

    @classmethod
    def score_round(cls, trials: List["RockPaperScissorsTrial"]):
        """Save each player's action, their partner's action and the result on the player's trial."""
        for trial in trials:
            trial.var.timed_out = trial.response.time_limit_reached
            trial.var.action = trial.answer or random.choice(ACTIONS)
        # A pair needs both players to pass a barrier, so there are two trials.
        first, second = trials
        for trial, partner in [(first, second), (second, first)]:
            trial.var.partner_id = partner.participant_id
            trial.var.partner_action = partner.var.action
            trial.var.partner_timed_out = partner.var.timed_out
            trial.var.result = _result(trial.var.action, partner.var.action)
            trial.var.points = POINTS[trial.var.result]

    def show_feedback(self, experiment, participant):
        if self.sync_group_outcome != "stayed":
            # The round was never scored, so there is nothing to show.
            return None
        if self.var.timed_out:
            you = f"You ran out of time, so we chose {self.var.action} for you"
        else:
            you = f"You chose {self.var.action}"
        if self.var.partner_timed_out:
            partner = (
                "your partner ran out of time, so we chose "
                f"{self.var.partner_action} for them"
            )
        else:
            partner = f"your partner chose {self.var.partner_action}"
        winner = {"won": participant.id, "lost": self.var.partner_id}.get(
            self.var.result
        )
        prompt = tags.div()
        with prompt:
            tags.h1("Round results")
            tags.p(f"{you}, {partner}. {RESULT_TEXTS[self.var.result]}")
        return ModularPage(
            "results",
            GroupPrompt(
                prompt,
                group=self.sync_group,
                participant=participant,
                answers={
                    participant.id: self.var.action,
                    self.var.partner_id: self.var.partner_action,
                },
                highlight={} if winner is None else {winner: "winner"},
                note="Now chat with your partner about the round you just played!",
            ),
            chatroom=ChatRoom(
                # Both members share this trial's sync group, so they meet in
                # the same room.
                room_id=f"rps_room_{self.sync_group.id}",
                show_participants=True,
                show_history=True,
            ),
            time_estimate=30,
        )


class Exp(psynet.experiment.Experiment):
    label = "Rock paper scissors demo"

    timeline = get_timeline()

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round, from the trials.

        Every trial gets a row, including the trial of a player who left
        during the round; the columns from ``action`` on are ``None`` for a
        round that was never scored.
        """
        trials = RockPaperScissorsTrial.query.order_by(
            RockPaperScissorsTrial.sync_group_id,
            RockPaperScissorsTrial.sync_group_round,
            RockPaperScissorsTrial.id,
        )
        return {
            "player_round": [
                {
                    "pair_id": t.sync_group_id,
                    "round": t.sync_group_round,
                    "participant_id": t.participant_id,
                    "trial_id": t.id,
                    # "stayed" if the round was scored; otherwise how the
                    # player left the pair (see the module docstring).
                    "outcome": t.sync_group_outcome,
                    # None if the player ran out of time or never answered.
                    "choice": t.answer,
                    # The action played, random after a timeout.
                    "action": t.var.get("action"),
                    "timed_out": t.var.get("timed_out"),
                    "partner_id": t.var.get("partner_id"),
                    "partner_action": t.var.get("partner_action"),
                    "partner_timed_out": t.var.get("partner_timed_out"),
                    # "won", "drew" or "lost".
                    "result": t.var.get("result"),
                    "points": t.var.get("points"),
                }
                for t in trials
            ],
        }

    test_n_bots = 2
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        # In round 1, the second bot runs out of time and plays a random action.
        rounds = [
            ("rock", "paper", "You lost.", "You won!"),
            ("scissors", None, None, None),
            ("scissors", "scissors", "You drew.", "You drew."),
        ]
        for first, second, first_result, second_result in rounds:
            advance_past_wait_pages(bots)
            _assert_on_page(bots, "choose_action")

            # The first to choose waits for their partner.
            bots[0].take_page(response=first)
            bots[0].refresh_status()
            assert bots[0].current_page_label == "wait", bots[0].current_page_label
            if second is None:
                bots[1].run_out_of_time()
            else:
                bots[1].take_page(response=second)
            advance_past_wait_pages(bots)
            _assert_on_page(bots, "results")

            text = bots[0].current_page_text
            if second is None:
                assert "your partner ran out of time, so we chose" in text, text
            else:
                assert f"You chose {first}, your partner chose {second}. " in text
                assert first_result in text, text
                text = bots[1].current_page_text
                assert f"You chose {second}, your partner chose {first}. " in text
                assert second_result in text, text
            assert isinstance(bots[0].get_current_page().chatroom, ChatRoom)

            for bot in bots:
                bot.take_page()

        advance_past_wait_pages(bots)
        for bot in bots:
            bot.refresh_status()
            assert "That's the end!" in bot.current_page_text, bot.current_page_text

        rows = self.get_basic_data()["player_round"]
        assert len(rows) == 6, rows
        assert all(r["outcome"] == "stayed" for r in rows), rows
        assert len({r["pair_id"] for r in rows}) == 1, rows
        by_player = {(r["round"], r["participant_id"]): r for r in rows}
        first, second = (bot.id for bot in bots)
        summary = {
            key: (r["action"], r["partner_id"], r["partner_action"], r["points"])
            for key, r in by_player.items()
        }
        assert summary[(0, first)] == ("rock", second, "paper", -1), summary
        assert summary[(0, second)] == ("paper", first, "rock", 1), summary
        assert summary[(2, first)] == ("scissors", second, "scissors", 0), summary
        assert summary[(2, second)] == ("scissors", first, "scissors", 0), summary
        timed_out = by_player[(1, second)]
        assert timed_out["choice"] is None and timed_out["timed_out"], timed_out
        assert timed_out["action"] in ACTIONS, timed_out
        assert by_player[(1, first)]["partner_timed_out"], by_player[(1, first)]


def _assert_on_page(bots, label):
    """Every bot has left the waiting overlay, whose label is "wait", and is on ``label``."""
    for bot in bots:
        bot.refresh_status()
        assert bot.current_page_label == label, bot.current_page_label

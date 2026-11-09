"""Rock paper scissors for a fixed pair, with a chat after each round.

A ``SimpleGrouper`` pairs participants, and the pair plays ``N_ROUNDS``
rounds. In each round both players choose an action within
``CHOICE_SECONDS``, a barrier scores the round once both have chosen, and
both see the two actions and the winner, then chat about the round.

Each round is one cued ``RockPaperScissorsTrial`` per player. The pair's two
trials in a round share a node, which holds the round's facts: both actions,
who ran out of time and the winner. Each player's choice is their trial's
answer, and their view of the result (their action, their partner's and
their score) is computed from the node.

- A player who runs out of time gets a random action, so every round has a
  winner or a draw. Their answer stays ``None``; the action they played is
  on the node.
- The demo doesn't handle dropouts: a player whose partner leaves waits up
  to ``PARTNER_WAIT_SECONDS`` at the next barrier and is then failed, as is
  a participant for whom no partner arrives in that time. See
  ``public_goods`` for a game that carries on when players leave.
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
from psynet.trial.main import SyncGroupNode, Trial

GROUP = "rock_paper_scissors"
PARTNER_WAIT_SECONDS = 300
CHOICE_SECONDS = 20
N_ROUNDS = 3
ACTIONS = ["rock", "paper", "scissors"]
BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


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
                logic=RockPaperScissorsTrial.cue({}),
                time_estimate_per_iteration=RockPaperScissorsTrial.time_estimate,
            ),
        ),
    )


def _winner(actions):
    """Return the ID of the player whose action wins, or ``None`` for a draw."""
    (first, first_action), (second, second_action) = actions.items()
    if first_action == second_action:
        return None
    return first if BEATS[first_action] == second_action else second


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
    def score_round(cls, trials: List["RockPaperScissorsTrial"], node: SyncGroupNode):
        """Save both players' actions and the winner on the pair's node."""
        actions = {
            str(t.participant_id): t.answer or random.choice(ACTIONS) for t in trials
        }
        node.var.actions = actions
        node.var.timed_out = [str(t.participant_id) for t in trials if t.answer is None]
        node.var.winner = _winner(actions)

    def round_result(self):
        """Return the round's result from this trial's player's point of view, or ``None`` if it wasn't scored."""
        node = self.node
        if not node.var.has("actions"):
            return None
        player = str(self.participant_id)
        # The grouper forms pairs and accepts no newcomers, so a round has
        # exactly two players.
        (partner,) = [id_ for id_ in node.var.actions if id_ != player]
        winner = node.var.winner
        return {
            "action": node.var.actions[player],
            "timed_out": player in node.var.timed_out,
            "partner_id": int(partner),
            "partner_action": node.var.actions[partner],
            "partner_timed_out": partner in node.var.timed_out,
            "score": 0 if winner is None else 1 if winner == player else -1,
        }

    def show_feedback(self, experiment, participant):
        result = self.round_result()
        outcome = {1: "You won!", 0: "You drew.", -1: "You lost."}[result["score"]]
        if result["timed_out"]:
            you = f"You ran out of time, so we chose {result['action']} for you"
        else:
            you = f"You chose {result['action']}"
        if result["partner_timed_out"]:
            other = (
                "your partner ran out of time, so we chose "
                f"{result['partner_action']} for them"
            )
        else:
            other = f"your partner chose {result['partner_action']}"
        winner = self.node.var.winner
        prompt = tags.div()
        with prompt:
            tags.h1("Round results")
            tags.p(f"{you}, {other}. {outcome}")
        return ModularPage(
            "results",
            GroupPrompt(
                prompt,
                group=self.sync_group,
                participant=participant,
                answers=self.node.var.actions,
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
        """Return one row per player per round, with their partner's action.

        Every trial gets a row, including the trial of a player who closed the
        page before finishing it; the result columns are ``None`` for a round
        that was never scored.
        """
        unscored = dict.fromkeys(
            ["action", "timed_out", "partner_id", "partner_action"]
            + ["partner_timed_out", "score"]
        )
        rows = [
            {
                "group_id": trial.sync_group_id,
                "round": trial.sync_group_round,
                "participant_id": trial.participant_id,
                "trial_id": trial.id,
                # A player who ran out of time played a random action.
                **(trial.round_result() or unscored),
            }
            for trial in RockPaperScissorsTrial.query.all()
        ]
        rows.sort(key=lambda r: (r["group_id"], r["round"], r["participant_id"]))
        return {"player_round": rows}

    test_n_bots = 2
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        # In round 1, the second bot runs out of time and plays a random action.
        rounds = [
            ("rock", "paper", "You lost.", "You won!"),
            ("scissors", None, None, None),
            ("scissors", "scissors", "You drew.", "You drew."),
        ]
        for first, second, first_outcome, second_outcome in rounds:
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
                assert first_outcome in text, text
                text = bots[1].current_page_text
                assert f"You chose {second}, your partner chose {first}. " in text
                assert second_outcome in text, text
            assert isinstance(bots[0].get_current_page().chatroom, ChatRoom)

            for bot in bots:
                bot.take_page()

        advance_past_wait_pages(bots)
        for bot in bots:
            bot.refresh_status()
            assert "That's the end!" in bot.current_page_text, bot.current_page_text

        rows = self.get_basic_data()["player_round"]
        assert len(rows) == 6, rows
        by_player = {(r["round"], r["participant_id"]): r for r in rows}
        first, second = (bot.id for bot in bots)
        summary = {
            key: (r["action"], r["partner_id"], r["partner_action"], r["score"])
            for key, r in by_player.items()
        }
        assert summary[(0, first)] == ("rock", second, "paper", -1), summary
        assert summary[(0, second)] == ("paper", first, "rock", 1), summary
        assert summary[(2, first)] == ("scissors", second, "scissors", 0), summary
        assert summary[(2, second)] == ("scissors", first, "scissors", 0), summary
        timed_out = by_player[(1, second)]
        assert timed_out["timed_out"] and timed_out["action"] in ACTIONS, timed_out
        assert by_player[(1, first)]["partner_timed_out"], by_player[(1, first)]
        assert len({r["group_id"] for r in rows}) == 1, rows
        assert rows[0]["group_id"] is not None, rows


def _assert_on_page(bots, label):
    """Every bot has left the waiting overlay, whose label is "wait", and is on ``label``."""
    for bot in bots:
        bot.refresh_status()
        assert bot.current_page_label == label, bot.current_page_label

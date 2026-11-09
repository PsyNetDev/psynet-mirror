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


def score(action, partner_action):
    """Return 1 for a win, 0 for a draw and -1 for a loss."""
    if action == partner_action:
        return 0
    return 1 if BEATS[action] == partner_action else -1


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
                on_release=self.score_trial,
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
            # Running out of time saves None; score_trial then plays a random move.
            time_limit=CHOICE_SECONDS,
        )

    @classmethod
    def score_trial(cls, trials: List["RockPaperScissorsTrial"]):
        """Save each player's action, their partner's and the score on their trial."""
        timed_out = {t.id: t.answer is None for t in trials}
        actions = {
            t.id: random.choice(ACTIONS) if timed_out[t.id] else t.answer
            for t in trials
        }
        for trial in trials:
            # The grouper forms pairs and accepts no newcomers, so a round has
            # exactly two trials.
            (partner,) = [t for t in trials if t != trial]
            trial.var.result = {
                "action": actions[trial.id],
                "timed_out": timed_out[trial.id],
                "partner_id": partner.participant_id,
                "partner_action": actions[partner.id],
                "partner_timed_out": timed_out[partner.id],
                "score": score(actions[trial.id], actions[partner.id]),
            }

    def show_feedback(self, experiment, participant):
        result = self.var.result
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
        actions = {
            participant.id: result["action"],
            result["partner_id"]: result["partner_action"],
        }
        winner = {1: participant.id, -1: result["partner_id"]}.get(result["score"])
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
                answers=actions,
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
        """Return one row per player per round, with their partner's action."""
        # Not only complete trials: a trial is completed by its player's next
        # request, which never comes if they close the page after the round.
        trials = RockPaperScissorsTrial.query.all()
        rows = [
            {
                "group_id": trial.sync_group_id,
                "round": trial.sync_group_round,
                "participant_id": trial.participant_id,
                "trial_id": trial.id,
                # A player who ran out of time played a random action.
                **trial.var.result,
            }
            for trial in trials
            if trial.var.has("result")
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
        summary = [
            (r["round"], r["action"], r["partner_action"], r["score"]) for r in rows
        ]
        assert summary[:2] + summary[4:] == [
            (0, "rock", "paper", -1),
            (0, "paper", "rock", 1),
            (2, "scissors", "scissors", 0),
            (2, "scissors", "scissors", 0),
        ], summary
        timed_out = rows[3]
        assert timed_out["timed_out"] and timed_out["action"] in ACTIONS, timed_out
        assert rows[2]["partner_timed_out"], rows[2]
        assert len({r["group_id"] for r in rows}) == 1, rows
        assert rows[0]["group_id"] is not None, rows
        assert {r["partner_id"] for r in rows} == {bot.id for bot in bots}, rows


def _assert_on_page(bots, label):
    """Every bot has left the waiting overlay and is on ``label``."""
    for bot in bots:
        bot.refresh_status()
        assert not getattr(bot.get_current_page(), "is_timeline_hold", False)
        assert bot.current_page_label == label, bot.current_page_label

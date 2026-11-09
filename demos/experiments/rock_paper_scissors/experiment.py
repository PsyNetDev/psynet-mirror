import random
from typing import List

from dominate import tags

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.chatroom import ChatRoom, EnableChatrooms
from psynet.group_prompt import GroupPrompt
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger

logger = get_logger()

PARTNER_WAIT_SECONDS = 300
CHOICE_SECONDS = 20
ACTIONS = ["rock", "paper", "scissors"]


def _assert_on_page(bots, expected_label):
    """Every bot has left its hold overlay and is on ``expected_label``."""
    for bot in bots:
        bot.refresh_status()
        page = bot.get_current_page()
        assert not getattr(page, "is_timeline_hold", False)
        assert bot.current_page_label == expected_label


def _last_arriver_self_skips_then_partners_catch_up(last_bot, bots, expected_label):
    """Last-arrival self-skips on this request; partners overlay-catch-up."""
    _assert_on_page([last_bot], expected_label)
    advance_past_wait_pages(bots)
    _assert_on_page(bots, expected_label)


class RockPaperScissorsTrialMaker(StaticTrialMaker):
    pass


class RockPaperScissorsTrial(StaticTrial):
    time_estimate = 35
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        return join(
            self.choose_action(participant),
            GroupBarrier(
                id_="finished_trial",
                group_type="rock_paper_scissors",
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
            save_answer="last_action",
            # Running out of time saves None; score_trial then plays a random move.
            time_limit=CHOICE_SECONDS,
        )

    def show_feedback(self, experiment, participant):
        result = self.var.result
        score = result["score"]
        if score == -1:
            outcome = "You lost."
        elif score == 0:
            outcome = "You drew."
        else:
            assert score == 1
            outcome = "You won!"
        if result["timed_out_self"]:
            you = f"You ran out of time, so we chose {result['action_self']} for you"
        else:
            you = f"You chose {result['action_self']}"
        if result["timed_out_other"]:
            other = (
                "your partner ran out of time, so we chose "
                f"{result['action_other']} for them"
            )
        else:
            other = f"your partner chose {result['action_other']}"
        prompt = tags.div()
        with prompt:
            tags.h1("Round results")
            tags.p(f"{you}, {other}. {outcome}")
        actions = result["action_by_player"]
        winning_action = result["action_self" if score == 1 else "action_other"]
        return ModularPage(
            "results",
            GroupPrompt(
                prompt,
                group=self.sync_group,
                participant=participant,
                answers=actions,
                highlight={}
                if score == 0
                else {
                    pid: "winner" for pid, a in actions.items() if a == winning_action
                },
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

    @classmethod
    def score_trial(cls, trials: List["RockPaperScissorsTrial"]):
        """Save each player's result for the round on their trial."""
        assert len(trials) == 2
        participants = [trial.participant for trial in trials]
        timed_out = [p.var.last_action is None for p in participants]
        answers = [
            random.choice(ACTIONS) if out else p.var.last_action
            for p, out in zip(participants, timed_out)
        ]
        score_0 = cls.scoring_matrix[answers[0]][answers[1]]
        action_by_player = {p.id: a for p, a in zip(participants, answers)}
        for i, (trial, score) in enumerate(zip(trials, (score_0, -score_0))):
            trial.var.result = {
                "action_self": answers[i],
                "action_other": answers[1 - i],
                "timed_out_self": timed_out[i],
                "timed_out_other": timed_out[1 - i],
                "action_by_player": action_by_player,
                "score": score,
            }

    scoring_matrix = {
        "rock": {
            "rock": 0,
            "paper": -1,
            "scissors": 1,
        },
        "paper": {
            "rock": 1,
            "paper": 0,
            "scissors": -1,
        },
        "scissors": {"rock": -1, "paper": 1, "scissors": 0},
    }


class Exp(psynet.experiment.Experiment):
    label = "Rock paper scissors demo"

    timeline = Timeline(
        EnableChatrooms(),
        SimpleGrouper(
            group_type="rock_paper_scissors",
            initial_group_size=2,
            waiting_message="Waiting for your partner",
            max_wait_time=PARTNER_WAIT_SECONDS,
        ),
        RockPaperScissorsTrialMaker(
            id_="rock_paper_scissors",
            trial_class=RockPaperScissorsTrial,
            # A single node: every round is the same game, so each pair
            # revisits it for three rounds.
            nodes=[StaticNode(definition={"game": "rock_paper_scissors"})],
            allow_repeated_nodes=True,
            expected_trials_per_participant=3,
            max_trials_per_participant=3,
            sync_group_type="rock_paper_scissors",
            sync_group_waiting_message="Waiting for your partner",
            sync_group_max_wait_time=PARTNER_WAIT_SECONDS,
        ),
    )

    @classmethod
    def get_basic_data(cls, context=None, **kwargs):
        """Return one row per player per round, from the result each trial saved.

        A player who timed out plays a random move, which the result records.
        """
        trials = (
            RockPaperScissorsTrial.query.filter(
                RockPaperScissorsTrial.sync_group_id.isnot(None)
            )
            .filter_by(failed=False, complete=True)
            .order_by(
                RockPaperScissorsTrial.sync_group_id,
                RockPaperScissorsTrial.sync_group_round,
                RockPaperScissorsTrial.participant_id,
            )
            .all()
        )
        rows = []
        for trial in trials:
            result = trial.var.result
            partners = [
                int(p)
                for p in result["action_by_player"]
                if int(p) != trial.participant_id
            ]
            rows.append(
                {
                    "group_id": trial.sync_group_id,
                    "round": trial.sync_group_round,
                    "participant_id": trial.participant_id,
                    "partner_id": partners[0] if partners else None,
                    "trial_id": trial.id,
                    "action": result["action_self"],
                    "partner_action": result["action_other"],
                    "timed_out": result["timed_out_self"],
                    "score": result["score"],
                }
            )
        return {"player_round": rows}

    test_n_bots = 2
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        # Trial-maker init/prepare holds stay up as silent catch-up spinners
        # until each bot resumes. Last-arrival does not skip partner cursors.
        advance_past_wait_pages(bots)
        _assert_on_page(bots, "choose_action")

        bots[0].take_page(response="rock")
        bots[0].refresh_status()
        page = bots[0].get_current_page()
        assert getattr(page, "is_timeline_hold", False)
        assert bots[0].current_page_label == "wait"

        assert bots[1].current_page_label == "choose_action"
        bots[1].take_page(response="paper")
        _last_arriver_self_skips_then_partners_catch_up(bots[1], bots, "results")

        assert (
            "You chose rock, your partner chose paper. You lost."
            in bots[0].current_page_text
        )
        assert (
            "You chose paper, your partner chose rock. You won!"
            in bots[1].current_page_text
        )

        assert bots[0].current_page_label == "results"
        page = bots[0].get_current_page()
        assert isinstance(page, ModularPage)
        assert isinstance(page.chatroom, ChatRoom)
        assert page.chatroom.show_participants is True
        assert page.chatroom.show_history is True

        bots[0].take_page()
        bots[1].take_page()
        advance_past_wait_pages(bots)
        _assert_on_page(bots, "choose_action")

        bots[0].take_page(response="scissors")
        bots[1].take_page(response="paper")
        _last_arriver_self_skips_then_partners_catch_up(bots[1], bots, "results")

        assert (
            "You chose scissors, your partner chose paper. You won!"
            in bots[0].current_page_text
        )
        assert (
            "You chose paper, your partner chose scissors. You lost."
            in bots[1].current_page_text
        )

        bots[0].take_page()
        bots[1].take_page()
        advance_past_wait_pages(bots)
        _assert_on_page(bots, "choose_action")

        bots[0].take_page(response="scissors")
        bots[1].take_page(response="scissors")
        _last_arriver_self_skips_then_partners_catch_up(bots[1], bots, "results")

        assert (
            "You chose scissors, your partner chose scissors. You drew."
            in bots[0].current_page_text
        ), (
            "A rare error sometimes occurs here. If you see it, please report it to Peter Harrison (pmcharrison) for "
            "further debugging."
        )
        assert (
            "You chose scissors, your partner chose scissors. You drew."
            in bots[1].current_page_text
        ), (
            "A rare error sometimes occurs here. If you see it, please report it to Peter Harrison (pmcharrison) for "
            "further debugging."
        )

        bots[0].take_page()
        bots[1].take_page()
        advance_past_wait_pages(bots)
        for bot in bots:
            bot.refresh_status()

        assert "That's the end!" in bots[0].current_page_text
        assert "That's the end!" in bots[1].current_page_text

        rows = self.get_basic_data()["player_round"]
        assert [
            (row["round"], row["action"], row["partner_action"]) for row in rows
        ] == [
            (0, "rock", "paper"),
            (0, "paper", "rock"),
            (1, "scissors", "paper"),
            (1, "paper", "scissors"),
            (2, "scissors", "scissors"),
            (2, "scissors", "scissors"),
        ], rows
        assert {row["partner_id"] for row in rows} == {bot.id for bot in bots}

from typing import List

from dominate import tags

import psynet.experiment
from psynet.bot import BotDriver, advance_past_wait_pages
from psynet.chatroom import ChatRoom, EnableChatrooms
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.participant import Participant
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline, join
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker
from psynet.utils import get_logger

logger = get_logger()

PARTNER_WAIT_SECONDS = 300


def _assert_arrived_without_hold(bot, expected_label):
    """The last group member should skip the partner hold on the same request."""
    bot.refresh_status()
    page = bot.get_current_page()
    assert not getattr(page, "is_timeline_hold", False)
    assert bot.current_page_label == expected_label


def _refresh_arrived_without_hold(bot, expected_label):
    """Reload a partner who was advanced on the last arriver's request."""
    _assert_arrived_without_hold(bot, expected_label)


class RockPaperScissorsTrialMaker(StaticTrialMaker):
    pass


class RockPaperScissorsTrial(StaticTrial):
    time_estimate = 5
    accumulate_answers = True

    def show_trial(self, experiment, participant):
        return join(
            self.choose_action(color=self.definition["color"]),
            GroupBarrier(
                id_="finished_trial",
                group_type="rock_paper_scissors",
                content="Waiting for your partner",
                on_release=self.score_trial,
                max_wait_time=PARTNER_WAIT_SECONDS,
            ),
        )

    def choose_action(self, color):
        prompt = tags.p("Choose your action:", style=f"color: {color};")
        return ModularPage(
            "choose_action",
            prompt,
            PushButtonControl(
                choices=["rock", "paper", "scissors"],
            ),
            time_estimate=5,
            save_answer="last_action",
        )

    def show_feedback(self, experiment, participant):
        score = participant.var.last_trial["score"]
        if score == -1:
            outcome = "You lost."
        elif score == 0:
            outcome = "You drew."
        else:
            assert score == 1
            outcome = "You won!"
        prompt = tags.div()
        with prompt:
            tags.h1("Round results")
            tags.p(
                f"You chose {participant.var.last_trial['action_self']}, "
                + f"your partner chose {participant.var.last_trial['action_other']}. "
                + outcome
            )
            tags.h2("Now chat with your partner about the round you just played!")

        # Derive the room from this trial's sync group (``self.sync_group``)
        # rather than ``participant.sync_group``, which raises an error if the
        # participant belongs to more than one active sync group. Both members
        # share the same ``self.sync_group.id``, so they meet in the same room.
        return ModularPage(
            "results",
            prompt,
            chatroom=ChatRoom(
                room_id=f"rps_room_{self.sync_group.id}",
                show_participants=True,
                show_history=True,
            ),
            time_estimate=30,
        )

    def score_trial(self, participants: List[Participant]):
        assert len(participants) == 2
        answers = [participant.var.last_action for participant in participants]
        score_0 = self.scoring_matrix[answers[0]][answers[1]]
        score_1 = -score_0
        participants[0].var.last_trial = {
            "action_self": answers[0],
            "action_other": answers[1],
            "score": score_0,
        }
        participants[1].var.last_trial = {
            "action_self": answers[1],
            "action_other": answers[0],
            "score": score_1,
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
            content="Waiting for your partner",
            max_wait_time=PARTNER_WAIT_SECONDS,
        ),
        RockPaperScissorsTrialMaker(
            id_="rock_paper_scissors",
            trial_class=RockPaperScissorsTrial,
            nodes=[
                StaticNode(definition={"color": color})
                for color in ["red", "green", "blue"]
            ],
            expected_trials_per_participant=3,
            max_trials_per_participant=3,
            sync_group_type="rock_paper_scissors",
            sync_group_wait_content="Waiting for your partner",
            sync_group_max_wait_time=PARTNER_WAIT_SECONDS,
        ),
    )

    test_n_bots = 2
    test_mode = "serial"

    def test_serial_run_bots(self, bots: List[BotDriver]):
        for bot in bots:
            bot.refresh_status()
            _assert_arrived_without_hold(bot, "choose_action")

        assert bots[0].current_page_label == "choose_action"
        bots[0].take_page(response="rock")
        assert bots[0].current_page_label == "wait"

        assert bots[1].current_page_label == "choose_action"
        bots[1].take_page(response="paper")
        _assert_arrived_without_hold(bots[1], "results")
        _refresh_arrived_without_hold(bots[0], "results")

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
        _assert_arrived_without_hold(bots[1], "choose_action")
        _refresh_arrived_without_hold(bots[0], "choose_action")

        bots[0].take_page(response="scissors")
        bots[1].take_page(response="paper")
        _assert_arrived_without_hold(bots[1], "results")
        _refresh_arrived_without_hold(bots[0], "results")

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
        _assert_arrived_without_hold(bots[1], "choose_action")
        _refresh_arrived_without_hold(bots[0], "choose_action")

        bots[0].take_page(response="scissors")
        bots[1].take_page(response="scissors")
        _assert_arrived_without_hold(bots[1], "results")
        _refresh_arrived_without_hold(bots[0], "results")

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

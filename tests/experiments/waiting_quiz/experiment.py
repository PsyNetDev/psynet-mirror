"""Quiz questions with feedback and points while participants wait for a group.

The grouper's ``waiting_logic`` cues one trial of the ``waiting_quiz`` trial
maker per pass, so each waiting participant answers a question, sees whether
they were right and how many points they have, and earns a performance reward
for each correct answer. Once they have answered every question, PsyNet shows
them its waiting page until the group forms. The documentation's recipe for
quiz questions while waiting includes this file.
"""

import json
import math
from typing import List

import psynet.experiment
from psynet.bot import BotDriver
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.sync import SimpleGrouper
from psynet.timeline import PageMaker, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

QUESTIONS = [
    {
        "question": "What is the capital of France?",
        "choices": ["Paris", "Rome", "Madrid"],
        "answer": "Paris",
    },
    {
        "question": "How many legs does a spider have?",
        "choices": ["6", "8", "10"],
        "answer": "8",
    },
    {
        "question": "Which planet is closest to the Sun?",
        "choices": ["Venus", "Mercury", "Mars"],
        "answer": "Mercury",
    },
]
REWARD_PER_POINT = 0.05  # In the experiment's currency.


class QuizTrial(StaticTrial):
    time_estimate = 10  # Question and feedback.

    def show_trial(self, experiment, participant):
        return ModularPage(
            "waiting_quiz",
            f"While you wait ({points_text(participant)} so far): "
            f"{self.definition['question']}",
            PushButtonControl(self.definition["choices"]),
            time_estimate=7,
            bot_response=self.definition["answer"],
        )

    def score_answer(self, answer, definition):
        return int(answer == definition["answer"])

    def compute_performance_reward(self, score):
        return score * REWARD_PER_POINT

    def show_feedback(self, experiment, participant):
        if self.score:
            verdict = "Correct!"
        else:
            verdict = f"Not quite: the answer is {self.definition['answer']}."
        return InfoPage(
            f"{verdict} You have {points_text(participant)}.", time_estimate=3
        )


def answered_trials(participant):
    """Return the participant's answered quiz trials, leaving out interrupted ones."""
    return QuizTrial.query.filter_by(
        participant_id=participant.id, finalized=True, failed=False
    )


def quiz_points(participant):
    return int(sum(trial.score for trial in answered_trials(participant)))


def points_text(participant):
    points = quiz_points(participant)
    return "1 point" if points == 1 else f"{points} points"


quiz = StaticTrialMaker(
    id_="waiting_quiz",
    trial_class=QuizTrial,
    nodes=[StaticNode(definition=question) for question in QUESTIONS],
    expected_trials_per_participant=len(QUESTIONS),
)


class Exp(psynet.experiment.Experiment):
    label = "Quiz questions while waiting"

    timeline = Timeline(
        InfoPage("Welcome!", time_estimate=2),
        quiz.custom(
            SimpleGrouper(
                "trio",
                initial_group_size=3,
                quorum=3,
                waiting_logic=PageMaker(
                    quiz.cue_trial, time_estimate=QuizTrial.time_estimate
                ),
                expected_wait=len(QUESTIONS) * QuizTrial.time_estimate,
                max_wait_time=300,
            ),
        ),
        InfoPage("Your group is ready.", time_estimate=2),
    )

    test_n_bots = 3

    def test_serial_run_bots(self, bots: List[BotDriver]):
        first, second, third = bots

        first.take_page()
        for answer_wrongly in [False, True, False]:
            assert first.current_page_label == "waiting_quiz"
            if answer_wrongly:
                first.take_page(response=_wrong_choice(first.current_page_text))
                assert "Not quite: the answer is" in first.current_page_text
            else:
                first.take_page()
                assert "Correct!" in first.current_page_text
            first.take_page()
        assert "Waiting for other participants" in first.current_page_text

        second.take_page()
        second.take_page()
        second.take_page()
        assert "1 point so far" in second.current_page_text

        # The third arrival completes the group and skips the quiz. The group
        # forming ends the second's question unanswered, as their browser
        # would once the grace period is over.
        third.take_page()
        assert third.current_page_text == "Your group is ready."
        _end_page_unanswered(second)
        first.take_page()
        for bot, points in zip(bots, [2, 1, 0]):
            assert bot.current_page_text == "Your group is ready."
            participant = Participant.query.get(bot.id)
            assert quiz_points(participant) == points
            assert math.isclose(
                participant.performance_reward, points * REWARD_PER_POINT
            )
        interrupted = QuizTrial.query.filter_by(
            participant_id=second.id, failed_reason="interrupted_by_release"
        )
        assert interrupted.count() == 1

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        node_ids = [trial.node_id for trial in answered_trials(bot)]
        assert len(set(node_ids)) == len(node_ids)


def _wrong_choice(page_text):
    """Return a wrong choice for the question on the page."""
    (question,) = [q for q in QUESTIONS if q["question"] in page_text]
    return next(c for c in question["choices"] if c != question["answer"])


def _end_page_unanswered(bot):
    """Send the interrupt that a browser sends when a release ends a waiting page."""
    payload = {
        "participant_id": bot.id,
        "page_uuid": bot.current_page_uuid,
        "raw_answer": None,
        "metadata": {"time_taken": 1},
        "interrupted": True,
    }
    response = bot.http_session.post(
        f"{bot.experiment.base_url}/response", data={"json": json.dumps(payload)}
    )
    assert response.json()["submission"] == "approved"
    bot.refresh_status()

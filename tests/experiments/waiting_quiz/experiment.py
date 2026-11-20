"""Quiz questions with feedback and points while participants wait for a group.

The grouper's ``waiting_logic`` cues one trial of the ``waiting_quiz`` trial
maker per pass, so each waiting participant answers a question, sees whether
they were right and how many points they have, and earns a performance reward
for each correct answer. Once they have answered every question, they see a
waiting page until the group forms. The documentation's recipe for quiz
questions while waiting includes this file.
"""

from typing import List

import psynet.experiment
from psynet.bot import BotDriver
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.page import InfoPage, WaitPage
from psynet.participant import Participant
from psynet.sync import SimpleGrouper
from psynet.timeline import PageMaker, Timeline, conditional
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
            f"While you wait ({quiz_points(participant)} points so far): "
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
            f"{verdict} You have {quiz_points(participant)} points.", time_estimate=3
        )


def answered_trials(participant):
    """Return the participant's answered quiz trials, leaving out interrupted ones."""
    return QuizTrial.query.filter_by(participant_id=participant.id, finalized=True)


def quiz_points(participant):
    return int(sum(trial.score for trial in answered_trials(participant)))


quiz = StaticTrialMaker(
    id_="waiting_quiz",
    trial_class=QuizTrial,
    nodes=[StaticNode(definition=question) for question in QUESTIONS],
    expected_trials_per_participant=len(QUESTIONS),
)

waiting_quiz = conditional(
    "questions_left",
    lambda participant: answered_trials(participant).count() < len(QUESTIONS),
    logic_if_true=PageMaker(quiz.cue_trial, time_estimate=QuizTrial.time_estimate),
    logic_if_false=WaitPage(
        wait_time=3, content="You have answered every question. Please wait…"
    ),
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
                waiting_logic=waiting_quiz,
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
        for _ in QUESTIONS:
            assert first.current_page_label == "waiting_quiz"
            first.take_page()
            assert "Correct!" in first.current_page_text
            first.take_page()
        assert "answered every question" in first.current_page_text

        second.take_page()
        assert second.current_page_label == "waiting_quiz"
        second.take_page()
        second.take_page()
        assert "1 points so far" in second.current_page_text

        # The third arrival completes the group and skips the quiz, and the
        # second still gets the point for the question they were on.
        third.take_page()
        assert third.current_page_text == "Your group is ready."
        second.take_page()
        first.take_page()
        for bot, points in zip(bots, [3, 2, 0]):
            assert bot.current_page_text == "Your group is ready."
            participant = Participant.query.get(bot.id)
            assert quiz_points(participant) == points
            assert participant.performance_reward == points * REWARD_PER_POINT

    def test_check_bot(self, bot, **kwargs):
        super().test_check_bot(bot, **kwargs)
        node_ids = [trial.node_id for trial in answered_trials(bot)]
        assert len(set(node_ids)) == len(node_ids)

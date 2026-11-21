from markupsafe import Markup

import psynet.experiment
from psynet.modular_page import ModularPage
from psynet.page import InfoPage
from psynet.timeline import FailedValidation, PageMaker, Timeline
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

WORDS = ["apple", "brick", "cloud", "drum", "eagle", "flute"]


class WordTrial(StaticTrial):
    time_estimate = 1

    def show_trial(self, experiment, participant):
        return ModularPage(
            "word",
            Markup(
                "<p id='word'></p>"
                "<button id='answer-button' type='button'>Answer</button>"
                "<button id='reject-button' type='button'>Reject</button>"
            ),
            contents={"word": self.definition["word"]},
            show_next_button=False,
            js_page_modules=["/static/word-trial.js"],
            validate=lambda response: (
                FailedValidation("Rejected.") if response.answer == "reject" else None
            ),
            bot_response=self.definition["word"],
        )


class WordTrialMaker(StaticTrialMaker):
    def show_before_trial(self, trial):
        if trial.position == 3:
            return InfoPage("Take a break.", time_estimate=1)


def list_answers(participant):
    trials = WordTrial.query.filter_by(participant_id=participant.id).order_by(
        WordTrial.position
    )
    return InfoPage(
        "Answers: " + ",".join(trial.answer for trial in trials), time_estimate=1
    )


class Exp(psynet.experiment.Experiment):
    label = "Predicted trials test"

    timeline = Timeline(
        WordTrialMaker(
            id_="words",
            trial_class=WordTrial,
            nodes=[StaticNode(definition={"word": word}) for word in WORDS],
            expected_trials_per_participant=len(WORDS),
            node_order="listed",
            prepare_trials_in_advance=True,
        ),
        PageMaker(list_answers, time_estimate=1),
    )

    def test_check_bot(self, bot, **kwargs):
        trials = WordTrial.query.filter_by(participant_id=bot.id).order_by(
            WordTrial.position
        )
        assert [trial.answer for trial in trials] == WORDS
        assert all(trial.response_started_at for trial in trials)

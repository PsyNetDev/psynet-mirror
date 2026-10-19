from dallinger import db
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

import psynet.experiment
from psynet.bot import Bot
from psynet.data import SQLBase, SQLMixin, register_table
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.timeline import Module, PageMaker, Timeline, while_loop
from psynet.trial.main import Trial

from . import adaptive_logic


@register_table
class AdaptiveDecision(SQLBase, SQLMixin):
    __tablename__ = "adaptive_decision"

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    trial_id = Column(Integer, ForeignKey("trial.id"), unique=True, index=True)
    selected_candidate_id = Column(String)
    trial = relationship(Trial, foreign_keys=[trial_id])


class StaircaseTrial(Trial):
    time_estimate = 5

    def show_trial(self, experiment, participant):
        difficulty = self.definition["difficulty"]
        return ModularPage(
            "staircase_trial",
            f"Is {difficulty} a large number?",
            PushButtonControl(["Yes", "No"], bot_response="Yes"),
            time_estimate=self.time_estimate,
        )


def trial_history(participant):
    trials = [
        trial
        for trial in participant.all_trials
        if isinstance(trial, StaircaseTrial) and trial.complete
    ]
    trials.sort(key=lambda trial: trial.id)
    return [
        {
            "difficulty": trial.definition["difficulty"],
            "correct": trial.answer == "Yes",
        }
        for trial in trials
    ]


def record_decision(trial, creation_context):
    decision = AdaptiveDecision(
        participant_id=trial.participant_id,
        selected_candidate_id=str(creation_context["selected_candidate_id"]),
    )
    decision.trial = trial
    db.session.add(decision)


def select_and_cue(participant, experiment):
    difficulty = adaptive_logic.select_difficulty(trial_history(participant))
    return StaircaseTrial.cue(
        definition={"difficulty": difficulty},
        on_trial_created=record_decision,
        creation_context={"selected_candidate_id": difficulty},
    )


staircase = Module(
    "staircase",
    while_loop(
        label="adaptive staircase",
        condition=lambda participant: (
            not adaptive_logic.should_stop(trial_history(participant))
        ),
        logic=PageMaker(
            select_and_cue,
            time_estimate=StaircaseTrial.time_estimate,
        ),
        expected_repetitions=adaptive_logic.MAX_TRIALS,
    ),
)


class Exp(psynet.experiment.Experiment):
    label = "Trial.cue adaptive staircase"

    timeline = Timeline(
        staircase,
    )

    def test_check_bot(self, bot: Bot, **kwargs):
        trials = sorted(
            [trial for trial in bot.all_trials if isinstance(trial, StaircaseTrial)],
            key=lambda trial: trial.id,
        )
        assert [trial.definition["difficulty"] for trial in trials] == [
            4,
            5,
            6,
            7,
            7,
            7,
            7,
            7,
        ]
        assert all(trial.answer == "Yes" for trial in trials)
        assert all(trial.complete and trial.finalized for trial in trials)

        decisions = (
            AdaptiveDecision.query.filter_by(participant_id=bot.id)
            .order_by(AdaptiveDecision.id)
            .all()
        )
        assert [decision.selected_candidate_id for decision in decisions] == [
            "4",
            "5",
            "6",
            "7",
            "7",
            "7",
            "7",
            "7",
        ]
        assert [decision.trial for decision in decisions] == trials

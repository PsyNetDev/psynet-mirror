from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.trial.main import Trial

EXPERIMENT = str(Path(__file__).parents[2] / "demos/experiments/simple_audio_rating")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_failed_prepared_trials_are_replaced_up_to_the_limit(monkeypatch):
    bot = BotDriver()
    bot.take_page()
    trials = Trial.query.filter_by(participant_id=bot.id).all()
    assert len(trials) > 1
    for trial in trials:
        trial.fail("test")
    db.session.commit()

    trial_maker = trials[0].trial_maker
    monkeypatch.setattr(trial_maker, "max_trials_per_participant", len(trials) - 1)
    participant = Participant.query.get(bot.id)
    trial, status = trial_maker.prepare_trial(get_experiment(), participant)
    assert status == "available"
    replacements = [
        t for t in trial_maker.get_participant_trials(participant) if not t.failed
    ]
    assert trial in replacements and len(replacements) == len(trials) - 1
    # The failed trials' nodes can be chosen again.
    assert set(participant.module_state.participated_networks) == {
        t.network_id for t in replacements
    }

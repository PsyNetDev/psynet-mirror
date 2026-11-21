import datetime
from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.trial.main import Trial

EXPERIMENT = str(Path(__file__).parents[1] / "playwright/experiments/predicted_trials")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_prepared_trials_are_predicted_and_time_out_once_shown():
    bot = BotDriver()
    page = bot.get_current_page()
    # The break before the fourth trial ends the prediction.
    assert page.contents == {"word": "apple"}
    assert page.upcoming_contents == [{"word": "brick"}, {"word": "cloud"}]

    trials = Trial.query.filter_by(participant_id=bot.id).order_by(Trial.position)
    trials = trials.all()
    assert len(trials) == 6
    month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
    for trial in trials:
        trial.creation_time = month_ago
    db.session.commit()
    trial_maker = trials[0].trial_maker
    trial_maker.check_old_trials()
    assert not any(trial.failed for trial in trials)

    trials[0].response_started_at = month_ago
    db.session.commit()
    trial_maker.check_old_trials()
    assert [trial.failed for trial in trials] == [True] + [False] * 5

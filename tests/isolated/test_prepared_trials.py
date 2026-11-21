import datetime
from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.trial.main import Trial

EXPERIMENT = str(Path(__file__).parents[2] / "demos/features/rapid_ratings")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_prepared_trials_are_predicted_and_time_out_once_shown():
    bot = BotDriver()
    bot.take_page()
    page = bot.get_current_page()
    assert page.contents["name"] == "red circle"
    # The break before the fifth trial ends the prediction.
    assert [c["name"] for c in page.upcoming_contents] == [
        "orange triangle",
        "yellow star",
        "green square",
    ]

    trials = Trial.query.filter_by(participant_id=bot.id).order_by(Trial.position)
    trials = trials.all()
    assert len(trials) == 8
    trial_maker = trials[0].trial_maker
    # A time limit is set up for each page, so such pages aren't predicted.
    page.time_limit = 10
    assert trial_maker._upcoming_contents(trials[0], page, None, bot) is None

    month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
    for trial in trials:
        trial.creation_time = month_ago
    db.session.commit()
    trial_maker.check_old_trials()
    assert not any(trial.failed for trial in trials)

    trials[0].response_started_at = month_ago
    db.session.commit()
    trial_maker.check_old_trials()
    assert [trial.failed for trial in trials] == [True] + [False] * 7

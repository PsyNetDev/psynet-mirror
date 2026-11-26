from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.participant import Participant
from psynet.trial.main import Trial

EXPERIMENT = str(Path(__file__).parents[1] / "experiments/prepared_trial_options")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_the_browser_runs_ahead_up_to_the_next_checked_trial():
    bot = BotDriver()
    # Only every second trial is checked, so the first trial's page carries
    # the second trial's page but not the third's.
    assert len(bot.get_current_page().upcoming_pages) == 1
    bot.take_page()
    assert bot.get_current_page().upcoming_pages is None


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_a_failed_check_fails_the_trials_prepared_ahead():
    bot = BotDriver()
    Participant.query.get(bot.id).var.fail_checks = True
    db.session.commit()
    bot.take_page()
    bot.take_page()
    db.session.expire_all()
    assert Participant.query.get(bot.id).failed
    trials = Trial.query.filter_by(participant_id=bot.id).order_by(Trial.position)
    # The two trials prepared ahead are never answered.
    assert [t.complete for t in trials] == [True, True, False, False]
    assert all(t.failed for t in trials)


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_repeat_trials_are_prepared_a_window_at_a_time():
    bot = BotDriver()

    def n_repeats():
        trials = Trial.query.filter_by(participant_id=bot.id)
        return sum(trial.is_repeat_trial for trial in trials)

    for _ in range(5):
        bot.take_page()
    # The current trial and the two after it.
    assert n_repeats() == 3
    bot.take_page()
    assert n_repeats() == 4

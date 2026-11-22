import datetime
from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.participant import Participant
from psynet.trial.main import Trial
from psynet.trial.static import StaticNode, StaticTrial, StaticTrialMaker

EXPERIMENT = str(Path(__file__).parents[2] / "demos/features/rapid_ratings")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_prepared_trials_are_predicted_and_time_out_once_shown():
    bot = BotDriver()
    bot.take_page()
    page = bot.get_current_page()
    assert page.contents["name"] == "red circle"
    # The break after the fourth trial ends the prediction.
    assert [p.contents["name"] for p in page.upcoming_pages] == [
        "orange triangle",
        "yellow star",
        "green square",
    ]

    trials = Trial.query.filter_by(participant_id=bot.id).order_by(Trial.position)
    trials = trials.all()
    assert len(trials) == 8
    # Each trial's page UUID is issued in advance, so the browser can tell
    # which page a reply is.
    participant = Participant.query.get(bot.id)
    assert participant.page_uuid == trials[0].page_uuid
    assert [p._page_uuid for p in page.upcoming_pages] == [
        t.page_uuid for t in trials[1:4]
    ]
    trial_maker = trials[0].trial_maker
    # A time limit is set up for each page, so such pages aren't predicted.
    page.time_limit = 10
    assert trial_maker._upcoming(trials[0], page, None, participant)[0] is None

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


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_a_break_does_not_count_towards_the_next_trial():
    bot = BotDriver()
    while "break" not in str(bot.get_current_page().prompt.text).lower():
        bot.take_page()
    # Bots report each page's time_estimate as its time_taken.
    bot.take_page()
    bot.take_page()
    trial = Trial.query.filter_by(participant_id=bot.id, position=4).one()
    assert trial.complete and trial.time_taken == 2


@pytest.mark.parametrize(
    "option",
    [
        {"sync_group_type": "pairs"},
        {"check_performance_every_trial": True},
        {"n_repeat_trials": 1},
        {"recruit_mode": "n_trials"},
    ],
)
def test_prepared_trials_reject_options_they_cant_support(option):
    with pytest.raises(ValueError, match="prepare_trials_in_advance"):
        StaticTrialMaker(
            id_="ratings",
            trial_class=StaticTrial,
            nodes=[StaticNode(definition={})],
            expected_trials_per_participant=1,
            prepare_trials_in_advance=True,
            **option,
        )

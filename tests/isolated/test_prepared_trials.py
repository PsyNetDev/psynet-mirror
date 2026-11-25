import datetime
import json
from pathlib import Path

import pytest
from dallinger import db

from psynet.bot import BotDriver
from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.timeline import Page
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
    assert [p.contents["name"] for p in page.upcoming_pages] == [
        "orange triangle",
        "yellow star",
    ]

    def prepared():
        return Trial.query.filter_by(participant_id=bot.id).order_by(Trial.id).all()

    # The trial on screen and the two its page carries.
    trials = prepared()
    assert len(trials) == 3
    bot.take_page()
    assert len(prepared()) == 4
    page = bot.get_current_page()
    trials = [t for t in prepared() if not t.complete]
    participant = Participant.query.get(bot.id)
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

    # Once the trial on screen times out, the trials waiting their turn are
    # failed too, so they stop counting towards their nodes.
    trials[0].response_started_at = month_ago
    db.session.commit()
    trial_maker.check_old_trials()
    assert all(trial.failed for trial in trials)


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_pages_are_pre_rendered_once_before_they_are_compared(monkeypatch):
    bot = BotDriver()
    bot.take_page()
    participant = Participant.query.get(bot.id)
    trial = Trial.query.filter_by(participant_id=bot.id, position=0).one()
    pre_rendered = []

    def pre_render(self):
        pre_rendered.append(self)
        self.page_config = {**self.page_config, "pre_rendered": True}

    monkeypatch.setattr(Page, "pre_render", pre_render)
    page = trial.show_trial(None, participant)
    shown, _ = trial.trial_maker._upcoming(trial, page, None, participant)
    assert len(shown) == 2
    # Each page, including the one on screen, is pre-rendered exactly once.
    assert page in pre_rendered
    assert len(pre_rendered) == len({id(page) for page in pre_rendered})


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_a_break_does_not_count_towards_the_next_trial():
    bot = BotDriver()
    bot.take_page()
    # The browser is told the page UUIDs the next trials' pages will have,
    # so it can tell which page a reply is.
    page = bot.get_current_page()
    first_page_uuid = bot.current_page_uuid
    upcoming = page._upcoming_pages_payload(
        get_experiment(), Participant.query.get(bot.id)
    )
    for expected in upcoming:
        bot.take_page()
        assert Participant.query.get(bot.id).page_uuid == expected["page_uuid"]
    # An answer from a page the server has moved past says so, for the
    # browser to load the current page instead. Without the participant's
    # unique_id, the current page's UUID can't be guessed either.
    current = Participant.query.get(bot.id).page_uuid
    guess = current.rsplit("-", 1)[0] + "-0123456789abcdef"
    for page_uuid in [first_page_uuid, guess]:
        reply = bot.http_session.post(
            f"{bot.experiment.base_url}/response",
            data={
                "json": json.dumps(
                    {
                        "participant_id": bot.id,
                        "page_uuid": page_uuid,
                        "raw_answer": 1,
                        "metadata": {},
                    }
                )
            },
        ).json()
        assert reply["submission"] == "rejected" and reply["stale_page"]
    assert Participant.query.get(bot.id).page_uuid == current
    while not isinstance(bot.get_current_page(), InfoPage):
        bot.take_page()
    # Bots report each page's time_estimate as its time_taken.
    bot.take_page()
    bot.take_page()
    trial = Trial.query.filter_by(participant_id=bot.id, position=4).one()
    assert trial.complete and trial.time_taken == 2


def test_prepared_trials_reject_sync_groups():
    with pytest.raises(ValueError, match="prepare_trials_in_advance"):
        StaticTrialMaker(
            id_="ratings",
            trial_class=StaticTrial,
            nodes=[StaticNode(definition={})],
            expected_trials_per_participant=1,
            prepare_trials_in_advance=True,
            sync_group_type="pairs",
        )


def test_n_upcoming_trials_is_set_on_the_trial_maker():
    class TrialMaker(StaticTrialMaker):
        time_estimate_per_trial = 1

    def trial_maker(n_upcoming_trials):
        return TrialMaker(
            id_="ratings",
            trial_class=StaticTrial,
            nodes=[StaticNode(definition={})],
            expected_trials_per_participant=1,
            prepare_trials_in_advance=True,
            n_upcoming_trials=n_upcoming_trials,
        )

    assert trial_maker(3).n_upcoming_trials == 3
    with pytest.raises(ValueError, match="n_upcoming_trials"):
        trial_maker(0)


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_a_trial_whose_page_has_a_different_layout_is_not_shown_in_advance(monkeypatch):
    bot = BotDriver()
    bot.take_page()
    trials = Trial.query.filter_by(participant_id=bot.id).order_by(Trial.position)
    trials = trials.all()
    # Each trial's page is rendered once to compare layouts.
    assert trials[0].layout_key is not None
    assert {trial.layout_key for trial in trials[:3]} == {trials[0].layout_key}

    trials[2].layout_key = "another layout"
    db.session.commit()
    participant = Participant.query.get(bot.id)
    reply = bot.http_session.post(
        f"{bot.experiment.base_url}/response",
        data={
            "json": json.dumps(
                {
                    "participant_id": bot.id,
                    "page_uuid": participant.page_uuid,
                    "unique_id": participant.unique_id,
                    "raw_answer": 3,
                    "metadata": {},
                }
            )
        },
    ).json()
    upcoming = reply["timeline_fragment"]["upcoming_pages"]
    assert upcoming == []
    # The browser compares the same key, computed from the page it receives.
    assert reply["timeline_fragment"]["layout_key"] == trials[1].layout_key

    # Bot tests fail if no trial could be shown in advance, even if the
    # experiment's own bot checks don't call super().
    experiment = get_experiment()
    monkeypatch.setattr(type(experiment), "test_check_bots", lambda self, bots: None)
    experiment._check_bots([participant])
    for i, trial in enumerate(trials):
        trial.layout_key = f"layout {i}"
    with pytest.raises(AssertionError, match="none could be shown in advance"):
        experiment._check_bots([participant])

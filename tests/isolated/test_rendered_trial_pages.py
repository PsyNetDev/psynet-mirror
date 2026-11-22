from pathlib import Path

import pytest
from flask import Flask, g

from psynet.bot import BotDriver
from psynet.participant import Participant
from psynet.trial.main import Trial

BUILT_IN = str(Path(__file__).parents[2] / "demos/features/rapid_ratings_built_in")


@pytest.mark.parametrize("experiment_directory", [BUILT_IN], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_built_in_pages_carry_the_next_trials_pages():
    bot = BotDriver()
    bot.take_page()
    page = bot.get_current_page()
    # The break after the fourth trial ends the pages sent in advance.
    assert [entry["page"].prompt.url for entry in page.upcoming_pages] == [
        "/static/pictures/orange-triangle.svg",
        "/static/pictures/yellow-star.svg",
        "/static/pictures/green-square.svg",
    ]

    # Pages the browser already holds aren't rendered again.
    trial = Trial.query.filter_by(participant_id=bot.id, position=0).one()
    participant = Participant.query.get(bot.id)
    held = page.upcoming_pages[0]["trial_id"]
    with Flask(__name__).test_request_context():
        g.held_trial_ids = {held}
        *_, upcoming = trial.trial_maker._upcoming(trial, page, None, participant)
    assert [entry["page"] is None for entry in upcoming] == [True, False, False]

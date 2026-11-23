import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from psynet.bot import BotDriver
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.trial.main import Trial

BUILT_IN = str(Path(__file__).parents[2] / "demos/features/rapid_ratings_built_in")


def _template_data(bot):
    """The data that the bot's current page sends the browser."""
    html = bot.http_session.get(
        f"{bot.experiment.base_url}/timeline",
        params={"unique_id": bot.participant_unique_id},
    ).text
    script = BeautifulSoup(html, "html.parser").find(id="psynet-template-data")
    return json.loads(script.string)


@pytest.mark.parametrize("experiment_directory", [BUILT_IN], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_built_in_pages_carry_the_next_trials_pages():
    bot = BotDriver()
    bot.take_page()
    upcoming = _template_data(bot)["upcomingPages"]
    # The break after the fourth trial ends the pages sent in advance.
    pictures = ["orange-triangle", "yellow-star", "green-square"]
    assert len(upcoming) == len(pictures)
    assert all(name in page["html"] for name, page in zip(pictures, upcoming))

    # A page rendered in advance carries the page UUID the participant gets
    # on reaching it, so the browser can answer it before the server is there.
    assert upcoming[0]["page_uuid"] in upcoming[0]["html"]
    bot.take_page()
    assert Participant.query.get(bot.id).page_uuid == upcoming[0]["page_uuid"]
    # The browser adopts the server's reply only if the page still renders
    # as it did in advance.
    served = _template_data(bot)["page"]["attributes"]["layout_key"]
    assert served == upcoming[0]["layout_key"]

    # The browser has moved on by the time an answer would be turned down,
    # so pages whose answers the server may turn down aren't swapped in.
    page = bot.get_current_page()
    participant = Participant.query.get(bot.id)
    trial = Trial.query.filter_by(participant_id=bot.id, position=1).one()
    page._validate_function = lambda answer: None
    assert (
        trial.trial_maker._upcoming(trial, page, get_experiment(), participant)[0]
        is None
    )

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from psynet.bot import BotDriver
from psynet.participant import Participant

BUILT_IN = str(Path(__file__).parents[2] / "demos/features/rapid_ratings_built_in")


def _template_data(bot):
    """The data that the bot's current page sends the browser."""
    script = BeautifulSoup(_timeline_html(bot), "html.parser").find(
        id="psynet-template-data"
    )
    return json.loads(script.string)


@pytest.mark.parametrize("experiment_directory", [BUILT_IN], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_built_in_pages_carry_the_next_trials_pages():
    bot = BotDriver()
    # The instructions page directly after the intro is rendered in advance,
    # with the page UUID the participant gets on reaching it.
    [instructions] = _template_data(bot)["upcomingPages"]
    # It can go back to the intro.
    assert 'id="back-button"' in instructions["html"]
    assert "Rate each picture" in instructions["html"]
    bot.take_page()
    assert bot.current_page_uuid == instructions["page_uuid"]

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


def _timeline_html(bot):
    return bot.http_session.get(
        f"{bot.experiment.base_url}/timeline",
        params={"unique_id": bot.participant_unique_id},
    ).text


@pytest.mark.parametrize("experiment_directory", [BUILT_IN], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_back_button_returns_to_the_previous_timeline_page():
    bot = BotDriver()
    assert 'id="back-button"' not in _timeline_html(bot)
    bot.take_page()
    assert 'id="back-button"' in _timeline_html(bot)
    previous = _template_data(bot)["previousPage"]
    assert "as you rate the one before" in previous["html"]
    credit = Participant.query.get(bot.id).time_credit

    reply = bot.http_session.post(
        f"{bot.experiment.base_url}/response",
        data={
            "json": json.dumps(
                {
                    "participant_id": bot.id,
                    "page_uuid": bot.current_page_uuid,
                    "raw_answer": None,
                    "metadata": {},
                    "back": True,
                }
            )
        },
    ).json()
    assert reply["submission"] == "approved"
    assert "as you rate the one before" in reply["timeline_fragment"]["html"]
    participant = Participant.query.get(bot.id)
    assert participant.time_credit == credit - 5
    # The browser can show the page before getting the reply.
    assert participant.page_uuid == previous["page_uuid"]

    bot.take_page()
    bot.take_page()
    # The first trial page can't go back to the instructions.
    assert 'id="back-button"' not in _timeline_html(bot)

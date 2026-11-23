import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from psynet.bot import BotDriver
from psynet.participant import Participant

BUILT_IN = str(Path(__file__).parents[2] / "demos/features/rapid_ratings_built_in")


def _upcoming_pages_in_browser(bot):
    """The upcoming pages that the bot's current page sends the browser."""
    html = bot.http_session.get(
        f"{bot.experiment.base_url}/timeline",
        params={"unique_id": bot.participant_unique_id},
    ).text
    script = BeautifulSoup(html, "html.parser").find(id="psynet-template-data")
    return json.loads(script.string)["upcomingPages"]


@pytest.mark.parametrize("experiment_directory", [BUILT_IN], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_built_in_pages_carry_the_next_trials_pages():
    bot = BotDriver()
    # The instructions page directly after the intro is rendered in advance,
    # with the page UUID the participant gets on reaching it.
    [instructions] = _upcoming_pages_in_browser(bot)
    # It can go back to the intro.
    assert 'id="back-button"' in instructions["html"]
    assert "Rate each picture" in instructions["html"]
    bot.take_page()
    assert bot.current_page_uuid == instructions["page_uuid"]

    bot.take_page()
    upcoming = bot.get_current_page().upcoming_pages
    # The break after the fourth trial ends the pages sent in advance.
    assert [page.prompt.url for page in upcoming] == [
        "/static/pictures/orange-triangle.svg",
        "/static/pictures/yellow-star.svg",
        "/static/pictures/green-square.svg",
    ]

    participant = Participant.query.get(bot.id)
    assert upcoming[0]._browser_page_uuid(participant) != participant.page_uuid
    bot.take_page()
    participant = Participant.query.get(bot.id)
    assert participant.page_uuid == upcoming[0]._browser_page_uuid(participant)


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

    bot.take_page()
    bot.take_page()
    # The first trial page can't go back to the instructions.
    assert 'id="back-button"' not in _timeline_html(bot)

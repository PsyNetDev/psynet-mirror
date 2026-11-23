import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from psynet.bot import BotDriver
from psynet.participant import Participant

DEMO = str(Path(__file__).parents[2] / "demos/features/back_button")


def _template_data(bot):
    """The data that the bot's current page sends the browser."""
    html = bot.http_session.get(
        f"{bot.experiment.base_url}/timeline",
        params={"unique_id": bot.participant_unique_id},
    ).text
    script = BeautifulSoup(html, "html.parser").find(id="psynet-template-data")
    return json.loads(script.string)


def _progress_shown(html):
    return int(re.search(r'aria-valuenow="(\d+)"', html).group(1))


def _progress_now(bot):
    return round(Participant.query.get(bot.id).progress * 100)


def _go_back(bot):
    return bot.http_session.post(
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


@pytest.mark.parametrize("experiment_directory", [DEMO], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_back_returns_to_pages_without_answers():
    bot = BotDriver()
    assert _template_data(bot)["previousPage"] is None
    bot.take_page()
    data = _template_data(bot)
    previous, [following] = data["previousPage"], data["upcomingPages"]
    assert "Welcome!" in previous["html"]
    credit = Participant.query.get(bot.id).time_credit

    reply = _go_back(bot)
    assert reply["submission"] == "approved"
    assert "Welcome!" in reply["timeline_fragment"]["html"]
    participant = Participant.query.get(bot.id)
    assert participant.time_credit == credit - 5
    # The browser can show the page before getting the reply.
    assert participant.page_uuid == previous["page_uuid"]
    assert _progress_shown(previous["html"]) == _progress_now(bot)

    bot.take_page()
    bot.take_page()
    assert _progress_shown(following["html"]) == _progress_now(bot)

    bot.take_page()
    bot.take_page()
    # The question's page can go back to the instructions.
    assert "page 3 of 3" in _template_data(bot)["previousPage"]["html"]
    bot.take_page(response="green")
    # But no page goes back to the question, and the last page opts out.
    assert _template_data(bot)["previousPage"] is None
    bot.take_page()
    assert _template_data(bot)["previousPage"] is None

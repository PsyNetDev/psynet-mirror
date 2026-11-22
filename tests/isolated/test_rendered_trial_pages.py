from pathlib import Path

import pytest

from psynet.bot import BotDriver
from psynet.participant import Participant

BUILT_IN = str(Path(__file__).parents[2] / "demos/features/rapid_ratings_built_in")


@pytest.mark.parametrize("experiment_directory", [BUILT_IN], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_built_in_pages_carry_the_next_trials_pages():
    bot = BotDriver()
    bot.take_page()
    upcoming = bot.get_current_page().upcoming_pages
    # The break after the fourth trial ends the pages sent in advance.
    assert [page.prompt.url for page in upcoming] == [
        "/static/pictures/orange-triangle.svg",
        "/static/pictures/yellow-star.svg",
        "/static/pictures/green-square.svg",
    ]

    # A page rendered in advance has the page UUID the participant gets on
    # reaching it, so the browser can answer it before the server is there.
    participant = Participant.query.get(bot.id)
    assert upcoming[0]._browser_page_uuid(participant) != participant.page_uuid
    bot.take_page()
    participant = Participant.query.get(bot.id)
    assert participant.page_uuid == upcoming[0]._browser_page_uuid(participant)

from pathlib import Path

import pytest

from psynet.bot import BotDriver
from psynet.trial.static import StaticTrialMaker

EXPERIMENT = str(Path(__file__).parents[2] / "demos/experiments/static_audio_3")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_audio_prompt_and_push_buttons_show_trials_in_advance():
    bot = BotDriver()
    bot.take_page()
    page = bot.get_current_page()
    sounds = [
        contents["modular_page"]["prompt"]["audio"]
        for contents in [page.contents, *page.upcoming_contents]
    ]
    assert len(set(sounds)) == 1 + StaticTrialMaker.n_upcoming_trials
    assert page.js_page_modules[-1].endswith("modular-page-in-advance.js")

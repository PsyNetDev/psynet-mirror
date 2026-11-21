from pathlib import Path

import pytest

from psynet.bot import BotDriver
from psynet.modular_page import ImagePrompt, ModularPage, PushButtonControl
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


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({}, True),
        ({"show_next_button": True}, False),
        ({"start_trial_automatically": False}, False),
    ],
)
def test_pages_with_their_own_buttons_load_each_trial(kwargs, expected):
    page = ModularPage(
        "rating",
        ImagePrompt("/static/a.png", "Rate it", width="100px", height="100px"),
        PushButtonControl(["1", "2"]),
        time_estimate=1,
        **kwargs,
    )
    assert page._show_in_advance() is expected

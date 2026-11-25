from pathlib import Path

import pytest

from psynet.bot import BotDriver

EXPERIMENT = str(Path(__file__).parents[1] / "experiments/prepared_trial_options")


@pytest.mark.parametrize("experiment_directory", [EXPERIMENT], indirect=True)
@pytest.mark.usefixtures("launched_experiment")
def test_the_browser_runs_ahead_up_to_the_next_checked_trial():
    bot = BotDriver()
    # Only every second trial is checked, so the first trial's page carries
    # the second trial's page but not the third's.
    assert len(bot.get_current_page().upcoming_pages) == 1
    bot.take_page()
    assert bot.get_current_page().upcoming_pages is None

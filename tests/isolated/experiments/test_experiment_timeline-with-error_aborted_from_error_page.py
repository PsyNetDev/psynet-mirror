import time

import pytest
from dallinger import db
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from psynet.experiment import get_experiment
from psynet.participant import get_participant
from psynet.pytest_psynet import (
    assert_text,
    bot_class,
    next_page,
    path_to_test_experiment,
)
from psynet.utils import get_config

PYTEST_BOT_CLASS = bot_class()


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("timeline_with_error")],
    indirect=True,
)
class TestExp:
    def test_variables(self, db_session):
        config = get_config()
        assert config.get("min_reward_for_paid_early_exit") == 0.10
        assert config.get("show_early_exit_button") is True

    def test_abort(self, bot_recruits, db_session):
        # Exercise the popup-window error flow.
        exp = get_experiment()
        exp.var.set("start_experiment_in_popup_window", True)
        db.session.commit()
        for participant, bot in enumerate(bot_recruits):
            driver = bot.driver
            time.sleep(1)

            driver.switch_to.window(driver.window_handles[0])
            assert not driver.find_elements(By.ID, "abort-button")
            driver.close()
            driver.switch_to.window(driver.window_handles[0])

            next_page(driver, "consent")
            next_page(driver, "next-button")
            next_page(driver, "next-button")

            with pytest.raises(RuntimeError):
                next_page(driver, "next-button")

            WebDriverWait(driver, 15).until(
                lambda browser: "An error occurred" in browser.page_source
            )
            assert "/recruiter-exit" not in driver.current_url
            assert_text(driver, "header", "An error occurred")
            assert_text(
                driver,
                "automatic-early-exit-ready",
                "Unfortunately an error occurred and we cannot continue. "
                "However, your responses so far have been saved. You may close this page.",
            )
            assert not driver.find_elements(By.ID, "automatic-early-exit-continue")
            assert not driver.find_elements(By.ID, "early-exit-open")

            participant = get_participant(1)

            assert participant.early_exited is True
            assert participant.failed is True
            assert participant.end_time is not None
            assert participant.early_exited_modules == [
                "introduction",
            ]
            assert participant.module_states["introduction"][0].early_exited
            assert not participant.module_states["introduction"][0].finished

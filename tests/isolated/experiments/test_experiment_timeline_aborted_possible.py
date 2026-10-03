import time

import pytest
from selenium.webdriver.common.by import By

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
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_variables(self, db_session):
        config = get_config()
        assert config.get("min_reward_for_paid_early_exit") == 0.15
        assert config.get("show_early_exit_button") is True

    def test_abort(self, bot_recruits, db_session):
        for participant, bot in enumerate(bot_recruits):
            driver = bot.driver
            time.sleep(1)

            next_page(driver, "consent")
            next_page(driver, "next-button")
            next_page(driver, "next-button")
            next_page(driver, "next-button")

            url = driver.current_url
            page_uuid = driver.execute_script("return window.pageUuid")
            exit_button = driver.find_element(By.ID, "early-exit-button")
            exit_button.click()
            assert_text(driver, "early-exit-title", "Leave without finishing?")

            driver.find_element(By.ID, "early-exit-cancel").click()
            assert driver.find_element(By.ID, "early-exit-modal").get_attribute(
                "hidden"
            )
            assert driver.current_url == url
            assert driver.execute_script("return window.pageUuid") == page_uuid

            exit_button.click()
            driver.find_element(By.ID, "early-exit-confirm").click()
            time.sleep(0.5)

            participant = get_participant(1)

            assert participant.early_exited is True
            assert participant.failed is True
            assert participant.early_exited_modules == [
                "introduction",
            ]
            assert participant.module_states["introduction"][0].early_exited
            assert not participant.module_states["introduction"][0].finished

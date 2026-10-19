import time

import pytest
from selenium.webdriver.common.by import By

from psynet.pytest_psynet import (
    bot_class,
    click_finish_button,
    next_page,
    path_to_demo_feature,
)

PYTEST_BOT_CLASS = bot_class()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_feature("custom_theme")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp(object):
    def test_exp(self, bot_recruits, db_session):
        for i, bot in enumerate(bot_recruits):
            driver = bot.driver

            # Page 0
            time.sleep(1)

            # Content emitted before <!doctype html> would silently put every
            # participant page into quirks mode.
            assert driver.execute_script("return document.compatMode") == "CSS1Compat"

            # The default theme ships as a cacheable stylesheet.
            assert driver.execute_script(
                "return [...document.styleSheets].some("
                "  (s) => (s.href || '').includes('participant.css'))"
            )

            # Experiment-supplied CSS must still win over the defaults.
            # This attribute is set via static/theme.css
            button = driver.find_element(By.ID, "next-button")
            col_rosybrown = "rgba(188, 143, 143, 1)"
            assert button.value_of_css_property("background-color") == col_rosybrown

            body = driver.find_element(By.TAG_NAME, "body")
            col_powderblue = "rgba(176, 224, 230, 1)"
            assert body.value_of_css_property("background-color") == col_powderblue

            next_page(driver, "next-button")
            click_finish_button(driver)

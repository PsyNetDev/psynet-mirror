import time

import pytest
from selenium.webdriver.common.by import By

from psynet.experiment import get_experiment
from psynet.pytest_psynet import (
    assert_text,
    bot_class,
    click_finish_button,
    is_release_branch,
    next_page,
    path_to_demo_experiment,
)

PYTEST_BOT_CLASS = bot_class()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("translation")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp(object):
    def test_variables(self, db_session):
        exp = get_experiment()
        assert set(exp.supported_locales) == set(["en", "de", "nl"])

    def test_exp(self, bot_recruits, db_session):
        for i, bot in enumerate(bot_recruits):
            driver = bot.driver

            # Page 0
            time.sleep(1)

            # Page 1
            # Framework catalogs are refreshed on release branches, so a
            # feature-branch build may contain either the previous translated
            # label or the current English fallback. The demo's own copy must
            # remain translated in both cases.
            next_label = driver.find_element(By.ID, "next-button-text").text
            assert next_label in {"Next", "Weiter"}
            assert_text(
                driver,
                "main-body",
                f"Willkommen zur Übersetzungsdemo! {next_label}",
            )
            next_page(driver, "next-button")

            # Page 2
            assert_text(
                driver,
                "main-body",
                "You have chosen to translate this experiment to de. Below you will see this text translated! Unten sehen Sie diesen Text übersetzt! "
                + next_label,
            )

            next_page(driver, "next-button")

            # Page 3
            assert_text(
                driver,
                "main-body",
                "Here is an example of inline variable usage: Mein Name ist Alice. Mein Lieblingsessen ist pizza. Mein am wenigsten bevorzugtes Essen ist broccoli. "
                + next_label,
            )

            next_page(driver, "next-button")

            # Page 4
            assert_text(
                driver,
                "main-body",
                "Sie können auch Text in Schaltflächen oder auf jeder Art von Seite übersetzen! Schokolade Vanille Erdbeere",
            )
            next_page(driver, "Schokolade")

            # The end page is PsyNet framework copy, not experiment-authored
            # text, and its exact wording depends on catalogs that feature MRs
            # do not update. Check only that it rendered in German, and only
            # after the release-branch ``psynet translate`` pass.
            if is_release_branch():
                end_page = driver.find_element(By.ID, "main-body").text
                assert "Das ist das Ende des Experiments!" in end_page

            click_finish_button(driver)

import re
import time

import pytest
from dallinger import db
from selenium.webdriver.common.by import By

from psynet.participant import Participant, get_participant
from psynet.pytest_psynet import (
    assert_text,
    bot_class,
    click_finish_button,
    next_page,
    path_to_test_experiment,
)
from psynet.utils import get_config

PYTEST_BOT_CLASS = bot_class()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp(object):
    def test_variables(self, db_session):
        from psynet.experiment import get_experiment

        exp = get_experiment()
        assert exp.var.new_variable == "some-value"

        config = get_config()
        assert config.get("wage_per_hour") == 12.0
        assert config.get("min_accumulated_reward_for_abort") == 0.15
        assert config.get("show_abort_button") is True

    def test_exp(self, bot_recruits, db_session):
        for i, bot in enumerate(bot_recruits):
            driver = bot.driver

            # Page 0
            time.sleep(3)

            assert list(get_participant(1).started_modules) == ["main_consent"]

            driver.execute_script(
                "$('html').animate({ scrollTop: $(document).height() }, 0);"
            )
            next_page(driver, "consent")

            assert_text(driver, "main-body", "Welcome Welcome to the experiment! Next")
            next_page(driver, "next-button")

            # Page 1
            participant = get_participant(1)
            assert participant.started_modules == [
                "main_consent",
                "introduction",
            ]
            assert participant.module_states["introduction"][0].time_started is not None
            assert participant.module_states["introduction"][0].time_finished is None

            assert participant.finished_modules == ["main_consent"]
            assert participant.module_id == "introduction"

            assert re.search(
                "The current time is [0-9][0-9]:[0-9][0-9]:[0-9][0-9].",
                driver.find_element(By.ID, "main-body").text,
            )
            button = driver.find_element(By.ID, "next-button")
            assert button.text == "Next"
            next_page(driver, "next-button")

            # Page 2
            assert_text(driver, "main-body", "Write me a message! Next")
            text_input = driver.find_element(By.ID, "text-input")
            text_input.send_keys("Hello! I am a robot.")
            assert_text(driver, "next-button", "Next")
            next_page(driver, "next-button")

            # Page 3
            assert_text(driver, "main-body", "Your message: Hello! I am a robot. Next")
            next_page(driver, "next-button")

            db_session.commit()
            participant = Participant.query.filter_by(id=1).one()

            event_log = participant.last_response.metadata["event_log"]
            event_ids = [e["eventType"] for e in event_log]

            assert event_ids == [
                "trialConstruct",
                "pageReady",
                "trialPrepare",
                "trialStart",
                "responseEnable",
                "submitEnable",
            ]

            # Page 4
            assert_text(driver, "main-body", "What is your weight in kg? Next")
            text_input = driver.find_element(By.ID, "number-input")
            text_input.send_keys("78.5")
            assert_text(driver, "next-button", "Next")
            next_page(driver, "next-button")

            # Page 5
            assert_text(driver, "main-body", "Your weight is 78.5 kg. Next")
            next_page(driver, "next-button")

            db_session.commit()
            participant = Participant.query.filter_by(id=1).one()

            assert (
                participant.var.weight == "78.5"
            )  # ideally, NumberControl should really return a number, not a string!

            event_log = participant.last_response.metadata["event_log"]
            event_ids = [e["eventType"] for e in event_log]
            assert event_ids == [
                "trialConstruct",
                "pageReady",
                "trialPrepare",
                "trialStart",
                "responseEnable",
                "submitEnable",
            ]

            # Page 6
            button = driver.find_element(By.ID, "A")
            button.click()

            button = driver.find_element(By.ID, "C")
            button.click()

            button = driver.find_element(By.ID, "A")
            button.click()

            next_page(driver, "next-button")

            db_session.commit()
            participant = Participant.query.filter_by(id=1).one()
            buttons = [
                e["info"]["buttonId"]
                for e in participant.answer
                if e["eventType"] == "pushButtonClicked"
            ]
            assert buttons == ["A", "C", "A"]

            event_log = participant.response.metadata["event_log"]
            assert (
                len([e for e in event_log if e["eventType"] == "pushButtonClicked"])
                == 3
            )

            # Page 7
            db_session.commit()
            participant = get_participant(1)

            assert participant.module_states["introduction"][0].finished
            assert not participant.module_states["chocolate"][0].finished
            assert participant.started_modules == [
                "main_consent",
                "introduction",
                "weight",
                "chocolate",
            ]
            assert participant.finished_modules == [
                "main_consent",
                "introduction",
                "weight",
            ]
            assert participant.module_id == "chocolate"

            assert_text(driver, "main-body", "Do you like chocolate? Yes No")
            next_page(driver, "Yes")

            # Page 8
            assert_text(
                driver, "main-body", "It's nice to hear that you like chocolate! Next"
            )
            next_page(driver, "next-button")

            # Loop
            assert_text(
                driver, "main-body", "Would you like to stay in this loop? Yes No"
            )

            for _ in range(3):
                next_page(driver, "Yes")
                assert_text(
                    driver, "main-body", "Would you like to stay in this loop? Yes No"
                )

            next_page(driver, "No")

            db_session.commit()

            assert len(participant.module_states["loop"]) == 4

            assert_text(
                driver,
                "main-body",
                "It is possible to generate multiple pages from the same PageMaker, as in the following example: Next",
            )
            next_page(driver, "next-button")

            assert_text(
                driver, "main-body", "Participant 1, choose a shape: Square Circle"
            )
            next_page(driver, "Square")

            assert_text(
                driver, "main-body", "Participant 1, choose a chord: Major Minor"
            )
            next_page(driver, "Minor")

            assert_text(
                driver,
                "main-body",
                "If accumulate_answers is True, then the answers are stored in a dictionary, in this case: {'shape': 'Square', 'chord': 'Minor'}. Next",
            )
            next_page(driver, "next-button")

            assert_text(
                driver, "main-body", "What's your favourite color? Red Green Blue"
            )
            next_page(driver, "Red")

            assert_text(driver, "main-body", "Red is a nice color, wait 1s. Next")
            next_page(driver, "next-button")

            # Final page
            assert_text(
                driver,
                "main-body",
                (
                    "That's the end of the experiment! You will receive a reward of $0.36 "
                    "for the time you spent on the experiment. You have also been awarded a performance reward of $0.00! "
                    'Thank you for taking part. Please click "Finish" to finalize the session. Finish'
                ),
            )

            click_finish_button(driver)

            db.session.commit()
            assert participant.base_payment == 0.34

            # We haven't worked out by hand exactly what the bonus should be, so this number just comes
            # from running the test ourselves.
            assert participant.bonus == 0.02

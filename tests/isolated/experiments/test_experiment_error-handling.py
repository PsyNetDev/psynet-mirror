import time

import pytest
import requests

from psynet.error import ErrorRecord
from psynet.pytest_psynet import (
    assert_text,
    bot_class,
    click_finish_button,
    next_page,
    path_to_test_experiment,
    psynet_loaded,
    wait_until,
)
from psynet.utils import log_pexpect_errors


def test_empty():
    # We need to include this empty test otherwise the test suite will throw an error
    # while the below test is skipped
    pass


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("error_handling")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp(object):
    # To re-enable this test, rename this function to test_exp.
    # It was disabled on 25 April 2023 because it was flaky, but we will try fixing it in the future.
    def skip_test_exp(
        self, launched_experiment, debug_server_process, bot_recruits, db_session
    ):  # two_iterations, bot_recruits):
        for i in range(4):
            url = launched_experiment.recruiter.recruit()[0]
            bot = bot_class()(url)

            bot.participant_id = i + 1
            bot.sign_up()

            driver = bot.driver

            wait_until(
                psynet_loaded,
                max_wait=5.0,
                error_message="Page never became ready.",
                driver=driver,
            )

            assert_text(driver, "main-body", "Welcome to the experiment! Next")

            if bot.participant_id == 1:
                next_page(driver, "next-button")

                # The first participant triggers an error on 'submit response'
                assert_text(driver, "main-body", "Lorem ipsum Next")
                click_finish_button(driver)

                assert_text(
                    driver,
                    "error-text",
                    "Something went wrong, so the experiment cannot continue. "
                    "We're sorry.",
                )

                with log_pexpect_errors(debug_server_process):
                    debug_server_process.expect_exact(
                        "'participant_id': 1",
                        timeout=5,
                    )
                    debug_server_process.expect_exact(
                        "Traceback (most recent call last):", timeout=5
                    )
                    debug_server_process.expect_exact(
                        "ValueError: Error code 38574", timeout=5
                    )

                time.sleep(0.5)

                error = ErrorRecord.query.filter_by(id=1).one()
                assert error.kind == "ValueError"
                assert error.message == "Error code 38574"
                assert error.traceback
                assert error.participant_id == 1

            elif bot.participant_id == 2:
                # We set finished=True because otherwise the bot will
                # wait forever for the PsyNet library to load on
                # the next page, which it never will, because it's an
                # error page
                next_page(driver, "next-button", finished=True)

                # The second participant triggers an error on 'get page'
                assert_text(
                    driver,
                    "error-text",
                    "Something went wrong, so the experiment cannot continue. "
                    "We're sorry.",
                )

                with log_pexpect_errors(debug_server_process):
                    debug_server_process.expect_exact(
                        "'participant_id': 2",
                        timeout=5,
                    )
                    debug_server_process.expect_exact(
                        "Traceback (most recent call last):", timeout=5
                    )
                    debug_server_process.expect_exact(
                        "RuntimeError: Error code 82626", timeout=5
                    )

                time.sleep(0.5)

                error = ErrorRecord.query.filter_by(id=2).one()
                assert error.kind == "RuntimeError"
                assert error.message == "Error code 82626"
                assert error.traceback
                assert error.participant_id == 2

            elif bot.participant_id == 3:
                next_page(driver, "next-button")

                # The third participant triggers an error in a worker asynchronous process'
                click_finish_button(driver)

                with log_pexpect_errors(debug_server_process):
                    debug_server_process.expect_exact(
                        "'participant_id': 3",
                        timeout=5,
                    )
                    debug_server_process.expect_exact(
                        "Traceback (most recent call last):", timeout=20
                    )
                    debug_server_process.expect_exact(
                        "AssertionError: Error code 48473", timeout=20
                    )

                time.sleep(0.5)

                error = ErrorRecord.query.filter_by(id=3).one()
                assert error.kind == "AssertionError"
                assert error.message == "Error code 48473"
                assert error.traceback
                assert error.participant_id == 3
                assert error.process_id == 1

            elif bot.participant_id == 4:
                next_page(driver, "next-button")

                # The third participant triggers an error in a worker asynchronous process'
                click_finish_button(driver)

                with log_pexpect_errors(debug_server_process):
                    debug_server_process.expect_exact(
                        "'participant_id': 4",
                        timeout=20,
                    )
                    debug_server_process.expect_exact(
                        "Traceback (most recent call last):", timeout=20
                    )
                    debug_server_process.expect_exact(
                        "AssertionError: Error code 73722", timeout=20
                    )

                time.sleep(0.5)

                error = ErrorRecord.query.filter_by(id=4).one()
                assert error.kind == "AssertionError"
                assert error.message == "Error code 73722"
                assert error.traceback
                assert error.participant_id == 4
                assert error.process_id == 2

            # The built-in Dallinger.complete_experiment doesn't work because it mistakenly
            # uses a GET request instead of a POST request
            requests.post(
                f"http://localhost:5000/worker_complete?participant_id={bot.participant_id}"
            )

            bot.driver.quit()

            # We can use this code one day to code a dashboard test
            #
            # user = launched_experiment.var.dashboard_user
            # password = launched_experiment.var.dashboard_password
            #
            # dashboard_url = f"http://{user}:{password}@localhost:5000/dashboard/"
            # driver.get(dashboard_url)

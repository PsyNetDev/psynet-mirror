from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from selenium.webdriver.common.by import By

from psynet.participant import Participant
from psynet.pytest_psynet import bot_class, path_to_test_experiment
from psynet.utils import wait_until

PYTEST_BOT_CLASS = bot_class()


def _get_query_param(url, key):
    return parse_qs(urlparse(url).query).get(key, [None])[0]


def _get_unique_id(driver):
    return _get_query_param(driver.current_url, "unique_id")


def _get_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _get_recruitment_params(url):
    return {
        "recruiter": _get_query_param(url, "recruiter"),
        "hitId": _get_query_param(url, "hitId"),
        "workerId": _get_query_param(url, "workerId"),
        "assignmentId": _get_query_param(url, "assignmentId"),
        "mode": _get_query_param(url, "mode"),
    }


def _start_url(base_url, params):
    return f"{base_url}/start?{urlencode(params)}"


def _wait_for_timeline(driver, message):
    wait_until(
        lambda: "/timeline" in driver.current_url,
        max_wait=10,
        error_message=message,
    )


def _wait_for_error_form(driver, message):
    wait_until(
        lambda: bool(driver.find_elements(By.NAME, "error_type")),
        max_wait=10,
        error_message=message,
    )


@pytest.fixture(scope="class", autouse=True)
def configure_repeat_worker_policy(request, env):
    """Set the worker policy for the server launched for each test class."""
    key = "allow_repeat_worker_ids"
    previous = env.get(key)
    env[key] = str(bool(getattr(request.cls, "allow_repeat_worker_ids", False))).lower()
    yield
    if previous is None:
        env.pop(key, None)
    else:
        env[key] = previous


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestStartResumeDefault:
    # Overview: assignment ID resumes, repeat worker blocks by default, new IDs create new participant.
    def test_start_resume_scenarios(self, bot_recruits, db_session):
        for bot in bot_recruits:
            driver = bot.driver
            _wait_for_timeline(driver, "Timeline page never loaded.")
            initial_unique_id = _get_unique_id(driver)
            assert initial_unique_id is not None

            base_url = _get_base_url(driver.current_url)
            recruitment_params = _get_recruitment_params(bot.URL)

            # Existing assignment ID should resume the same participant.
            driver.get(_start_url(base_url, recruitment_params))
            _wait_for_timeline(
                driver, "Resume by assignment ID did not reach timeline."
            )
            assert _get_unique_id(driver) == initial_unique_id

            # Same worker with a new assignment ID should error by default.
            repeat_params = dict(recruitment_params)
            repeat_params["assignmentId"] = f"{repeat_params['assignmentId']}REPEAT"
            driver.get(_start_url(base_url, repeat_params))
            _wait_for_error_form(
                driver,
                "Repeat worker ID did not render the error page by default.",
            )
            error_type = driver.find_element(By.NAME, "error_type").get_attribute(
                "value"
            )
            assert "worker has already participated" in error_type

            # A completely new participant should create a fresh session.
            new_params = dict(recruitment_params)
            new_params["workerId"] = f"{new_params['workerId']}NEW"
            new_params["assignmentId"] = f"{new_params['assignmentId']}NEW"
            new_params["hitId"] = f"{new_params['hitId']}NEW"
            driver.get(_start_url(base_url, new_params))
            _wait_for_timeline(driver, "New participant did not reach the timeline.")
            assert _get_unique_id(driver) == (
                f"{new_params['workerId']}:{new_params['assignmentId']}"
            )
            assert (
                Participant.query.filter_by(worker_id=new_params["workerId"]).count()
                == 1
            )

            # Resuming a finished assignment still loads the same participant,
            # but the timeline route must hand it straight to the exit page
            # rather than revive a completed consent/trial.
            db_session.commit()
            initial_participant = Participant.query.filter_by(
                unique_id=initial_unique_id
            ).one()
            initial_participant.complete = True
            initial_participant.progress = 1
            db_session.commit()

            driver.get(_start_url(base_url, recruitment_params))
            wait_until(
                lambda: "/recruiter-exit" in driver.current_url,
                max_wait=10,
                error_message="Finished assignment did not return to the exit page.",
            )
            assert not driver.find_elements(By.ID, "consent")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestStartResumeAllowRepeat:
    allow_repeat_worker_ids = True

    # Overview: a worker can create multiple participants when repeats are enabled.
    def test_repeat_worker_id_creates_new_participants(self, bot_recruits):
        for bot in bot_recruits:
            driver = bot.driver
            _wait_for_timeline(driver, "Timeline page never loaded.")
            previous_unique_id = _get_unique_id(driver)
            assert previous_unique_id is not None

            base_url = _get_base_url(driver.current_url)
            recruitment_params = _get_recruitment_params(bot.URL)

            for expected_count in (2, 3):
                repeat_params = dict(recruitment_params)
                repeat_params["assignmentId"] = (
                    f"{repeat_params['assignmentId']}REPEAT{expected_count}"
                )
                driver.get(_start_url(base_url, repeat_params))
                _wait_for_timeline(
                    driver, "Repeat worker ID did not reach the timeline."
                )
                repeated_unique_id = _get_unique_id(driver)
                assert repeated_unique_id != previous_unique_id
                assert repeated_unique_id == (
                    f"{repeat_params['workerId']}:{repeat_params['assignmentId']}"
                )
                assert (
                    Participant.query.filter_by(
                        worker_id=repeat_params["workerId"]
                    ).count()
                    == expected_count
                )
                previous_unique_id = repeated_unique_id

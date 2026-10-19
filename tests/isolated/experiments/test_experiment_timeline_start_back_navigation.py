from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from selenium.webdriver.common.by import By

from psynet.pytest_psynet import bot_class, path_to_test_experiment
from psynet.utils import wait_until

PYTEST_BOT_CLASS = bot_class()


def _query_param(url, key):
    return parse_qs(urlparse(url).query).get(key, [None])[0]


def _start_url(timeline_url, recruitment_url):
    parsed = urlparse(timeline_url)
    params = {
        key: _query_param(recruitment_url, key)
        for key in ("recruiter", "hitId", "workerId", "assignmentId", "mode")
        if _query_param(recruitment_url, key) is not None
    }
    return f"{parsed.scheme}://{parsed.netloc}/start?{urlencode(params)}"


def _is_psynet_session_url(url):
    return urlparse(url).path in {"/ad", "/consent", "/start", "/timeline"}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_back_navigation_leaves_the_recruiter_handshake(self, bot_recruits):
        """Ad, gateway consent, and /start are replaced out of history."""
        for bot in bot_recruits:
            driver = bot.driver
            wait_until(
                lambda: "/timeline" in driver.current_url,
                max_wait=10,
                error_message="Timeline page never loaded.",
            )
            initial_unique_id = _query_param(driver.current_url, "unique_id")
            assert initial_unique_id is not None
            wait_until(
                lambda: bool(driver.find_elements(By.ID, "consent")),
                max_wait=10,
                error_message="Timeline consent button never appeared.",
            )
            resume_url = _start_url(driver.current_url, bot.URL)

            driver.back()
            wait_until(
                lambda: not _is_psynet_session_url(driver.current_url),
                max_wait=10,
                error_message="Back navigation returned to the recruiter handshake.",
            )

            driver.get(resume_url)
            wait_until(
                lambda: "/timeline" in driver.current_url,
                max_wait=10,
                error_message="Explicit /start did not resume the participant.",
            )
            assert _query_param(driver.current_url, "unique_id") == initial_unique_id

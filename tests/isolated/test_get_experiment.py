import threading
from unittest.mock import Mock

import pytest
import requests

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_get_experiment():
    from psynet.experiment import Experiment, get_experiment

    exp = get_experiment()
    assert isinstance(exp, Experiment)


def test_dashboard_sessions_share_one_login_across_experiments_and_threads(
    monkeypatch,
):
    from psynet.experiment import Experiment, _dashboard_login_cookies

    login = requests.Session()
    login.cookies.set("session", "logged-in")
    get_authenticated_session = Mock(return_value=login)
    monkeypatch.setattr(
        "psynet.experiment.get_authenticated_session", get_authenticated_session
    )
    _dashboard_login_cookies.cache_clear()

    def session():
        return Experiment.authenticated_session.fget(Mock(base_url="http://x"))

    first, second = session(), session()
    other_thread = []
    thread = threading.Thread(target=lambda: other_thread.append(session()))
    thread.start()
    thread.join()
    _dashboard_login_cookies.cache_clear()

    assert get_authenticated_session.call_count == 1
    assert first is second
    assert other_thread[0] is not first
    assert other_thread[0].cookies["session"] == "logged-in"

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


_loaded_experiment_classes = []


@pytest.fixture(scope="class")
def class_scoped_experiment_class(in_experiment_directory):
    from psynet.experiment import import_local_experiment

    experiment_class = import_local_experiment()["class"]
    _loaded_experiment_classes.append(experiment_class)
    return experiment_class


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
class TestExperimentStaysImportedDuringTests:
    def test_importing_the_experiment_module_reuses_its_classes(
        self, class_scoped_experiment_class
    ):
        """A lazy import of the experiment must not execute experiment.py again."""
        import importlib

        experiment_class = class_scoped_experiment_class
        module = importlib.import_module(experiment_class.__module__)
        assert getattr(module, experiment_class.__name__) is experiment_class


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
class TestExperimentIsReusedByTheNextLoad:
    def test_loading_the_experiment_again_reuses_its_classes(
        self, class_scoped_experiment_class
    ):
        """Reloading the experiment in the same process must not execute experiment.py again.

        Running it again would register its SQLAlchemy classes twice.
        """
        import importlib

        experiment_class = class_scoped_experiment_class
        assert _loaded_experiment_classes[0] is experiment_class
        module = importlib.import_module(experiment_class.__module__)
        assert getattr(module, experiment_class.__name__) is experiment_class


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

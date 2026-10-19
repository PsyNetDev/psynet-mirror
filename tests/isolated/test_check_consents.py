import pytest

from psynet import deployment_info
from psynet.command_line import run_pre_checks
from psynet.pytest_psynet import path_to_demo_experiment


@pytest.mark.usefixtures("in_experiment_directory")
@pytest.mark.usefixtures("deployment_info")
@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("hello_world")], indirect=True
)
class TestCheckConsents:
    def test_check_consents(self):
        pre_check_args = {
            "local_": True,
            "heroku": False,
            "docker": False,
            "app": "test_app",
        }

        deployment_info.write(mode="debug", is_local_deployment=True)
        run_pre_checks(mode="debug", **pre_check_args)

        deployment_info.write(mode="live")
        with pytest.raises(
            RuntimeError,
            match="It looks like your experiment is missing a consent page.",
        ):
            run_pre_checks(mode="live", **pre_check_args)

    def test_pre_checks_check_background_recording_pages(self, monkeypatch):
        """Static background pages are checked before launch, not on first visit."""
        from psynet.experiment import Experiment

        calls = []
        monkeypatch.setattr(
            Experiment,
            "_check_background_recording_pages",
            lambda self: calls.append(self),
        )
        deployment_info.write(mode="debug", is_local_deployment=True)
        run_pre_checks(
            mode="debug", local_=True, heroku=False, docker=False, app="test_app"
        )
        assert len(calls) == 1

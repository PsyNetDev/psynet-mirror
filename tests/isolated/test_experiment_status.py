from contextlib import nullcontext
from unittest.mock import Mock, patch

from psynet.experiment import Experiment


def test_status_and_backups_skips_before_launch_finished():
    with (
        patch("psynet.db.transaction", return_value=nullcontext()),
        patch("psynet.experiment.is_experiment_launched", return_value=False),
        patch("psynet.experiment.get_experiment") as get_experiment,
    ):
        Experiment.status_and_backups()

    get_experiment.assert_not_called()


def test_record_experiment_status_keeps_secret_out_of_database():
    status = {"secret": "launch-secret", "requests_per_minute": 3}

    class Exp:
        automatic_backups = True
        artifact_storage = Mock()
        deployment_id = "deployment"
        get_status = Mock(return_value=status)

    with (
        patch("psynet.experiment.ExperimentStatus") as status_model,
        patch("psynet.experiment.db.session.add") as add,
    ):
        Experiment.record_experiment_status.__func__(Exp)

    status_model.assert_called_once_with(requests_per_minute=3, isOffline=False)
    add.assert_called_once_with(status_model.return_value)
    Exp.artifact_storage.write_experiment_status.assert_called_once_with(
        {**status, "isOffline": False},
        "deployment",
    )

from contextlib import nullcontext
from unittest.mock import patch

from psynet.experiment import Experiment


def test_status_and_backups_skips_before_launch_finished():
    with (
        patch("psynet.db.transaction", return_value=nullcontext()),
        patch("psynet.experiment.is_experiment_launched", return_value=False),
        patch("psynet.experiment.get_experiment") as get_experiment,
    ):
        Experiment.status_and_backups()

    get_experiment.assert_not_called()


def test_recorded_status_does_not_store_dashboard_password():
    status = {
        "cpu_usage_pct": 1.0,
        "basic_data_url": "http://x/basic_data?dashboard_user=admin&dashboard_password=s3cret",
    }
    with (
        patch.object(Experiment, "get_status", return_value=status),
        patch.object(Experiment, "automatic_backups", False),
        patch("psynet.experiment.db.session.add") as add,
    ):
        Experiment.record_experiment_status()

    (row,) = add.call_args.args
    assert row.cpu_usage_pct == 1.0
    assert "s3cret" not in repr(row.to_dict())

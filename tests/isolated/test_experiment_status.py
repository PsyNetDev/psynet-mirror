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

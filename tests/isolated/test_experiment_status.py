import datetime
import uuid
from contextlib import nullcontext
from unittest.mock import Mock, patch

import pytest
from dallinger import db

from psynet.experiment import Experiment, get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment


def test_status_and_backups_skips_before_launch_finished():
    with (
        patch("psynet.db.transaction", return_value=nullcontext()),
        patch("psynet.experiment.is_experiment_launched", return_value=False),
        patch("psynet.experiment.get_experiment") as get_experiment,
    ):
        Experiment.status_and_backups()

    get_experiment.assert_not_called()


def test_record_experiment_status_keeps_credentials_out_of_database():
    status = {
        "basic_data_url": "http://x/basic_data?dashboard_password=s3cret",
        "secret": "launch-secret",
        "requests_per_minute": 3,
    }

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


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_participant_status_summarizes_statuses_cost_and_time(db_session):
    start = datetime.datetime(2026, 1, 1)
    for status, complete, minutes in [
        ("working", False, None),
        ("approved", True, 10),
        ("approved", True, 30),
        ("returned", False, None),
    ]:
        participant = Participant(
            experiment=get_experiment(),
            recruiter_id="hotair",
            worker_id=str(uuid.uuid4()),
            hit_id="hit",
            assignment_id=str(uuid.uuid4()),
            mode="debug",
        )
        participant.status = status
        participant.complete = complete
        participant.performance_reward = 1.0
        participant.creation_time = start
        if minutes is not None:
            participant.end_time = start + datetime.timedelta(minutes=minutes)
        db.session.add(participant)
    db.session.flush()

    status = Experiment.get_participant_status()

    assert status["participant_statuses"] == {
        "working": 1,
        "approved": 2,
        "returned": 1,
    }
    assert status["median_time_taken"] == 20 * 60
    assert status["total_cost"] == 2.0

import sys
import zipfile

import pytest

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("timeline")],
    indirect=True,
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_database_snapshot_round_trip(db_session, tmp_path, monkeypatch):
    # Importing the experiment appends its directory to sys.path, which would
    # otherwise change how later tests resolve the name ``experiment``.
    monkeypatch.setattr(sys, "path", list(sys.path))

    from dallinger import db

    from psynet import deployment_info
    from psynet.data import ingest_zip, init_db
    from psynet.experiment import ExperimentConfig, get_experiment
    from psynet.local_deployment import export_database_snapshot

    deployment_info.init(
        redeploying_from_archive=False,
        mode="live",
        is_local_deployment=True,
        is_ssh_deployment=False,
        server=None,
        app=None,
        local_id="gibbs",
        local_experiment_path=str(tmp_path),
    )
    experiment = get_experiment()
    experiment.setup_experiment_config()
    experiment.var.local_deployment_id = "gibbs"
    experiment.var.local_experiment_path = str(tmp_path)
    experiment.var.deployment_id = "launch-1"
    db.session.commit()

    archive_path = tmp_path / "snapshot.zip"
    exported = export_database_snapshot(archive_path)
    assert exported.participant_count == 0
    assert exported.max_response_id == 0
    with zipfile.ZipFile(archive_path) as archive:
        assert "data/experiment.csv" in archive.namelist()
        assert archive.testzip() is None

    init_db(drop_all=True)
    ingest_zip(archive_path, engine=db.engine)

    restored = ExperimentConfig.query.one()
    assert restored.var.local_deployment_id == "gibbs"
    assert restored.var.deployment_id == "launch-1"

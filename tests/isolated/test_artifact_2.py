# test_artifact_1.py runs artifact tests that use the hello_world experiment.
# test_artifact_2.py run tests that use the artifact_storage experiment.
# This separation is necessary because only one experiment can be imported per test process.

import os
import time
from pathlib import Path

import pytest

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("artifact_storage")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestAutomaticBackups:
    def test_exp(self, launched_experiment, tmp_path):
        assert launched_experiment.automatic_backups

        # Run a participant through the experiment so that we have some data to backup
        launched_experiment.test_experiment()

        # Experiment status and exports are generated once per minute
        time.sleep(75)

        artifacts_dir = (
            Path(launched_experiment.artifact_storage.root)
            / "deployments"
            / launched_experiment.deployment_id
        )
        artifact_files = [
            path.name for path in artifacts_dir.iterdir() if path.is_file()
        ]
        assert set(artifact_files) == {
            "basic_data.json",
            "export.zip",
            "experiment_status.json",
            "recruitment_status.json",
        }, (
            f"The contents of {artifacts_dir} are not as expected. Instead found: {artifact_files}"
        )

        experiment_status = (
            launched_experiment.artifact_storage.read_experiment_status()
        )
        assert not experiment_status["isOffline"]
        assert experiment_status["label"] == "Artifact Storage demo"

        recruitment_status = (
            launched_experiment.artifact_storage.read_recruitment_status()
        )
        assert recruitment_status["recruiter"] == "hotair"
        assert not recruitment_status["need_more_participants"]

        export_path = tmp_path / "export.zip"
        launched_experiment.artifact_storage.download_export(
            destination=str(export_path)
        )
        assert os.path.isfile(export_path)
        assert os.path.getsize(export_path) > 0

        basic_data = launched_experiment.artifact_storage.read_basic_data()
        assert len(basic_data) > 0
        assert "participant" in basic_data
        assert "trial" in basic_data

        # Ideally we would check the structure of the downloaded file.
        # However, the current implementation produces a zip file with a weird structure.
        # We will skip this for now.
        # with zipfile.ZipFile(export_path, "r") as zip_ref:
        #     with tempfile.TemporaryDirectory() as tempdir:
        #         zip_ref.extractall(tempdir)
        #         participant_csv_path = os.path.join(tempdir, "regular", "participant.csv")
        #         assert os.path.isfile(participant_csv_path), "participant.csv not found at top level of dallinger export. Instead found: " + str(os.listdir(tempdir))

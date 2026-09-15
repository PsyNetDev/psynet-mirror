from unittest.mock import MagicMock, patch

from psynet.experiment import Experiment


class MockExperiment(Experiment):
    def __init__(self):
        super().__init__()
        self.assets = MagicMock()
        self.timeline = MagicMock()
        self.timeline.modules = {}
        self.pre_deploy_routines = []


def test_pre_deploy_normal_deployment():
    """Test that pre_deploy runs all operations for normal deployment."""
    experiment = MockExperiment()

    # Mock all the methods that pre_deploy calls
    with (
        patch.object(experiment, "update_deployment_id"),
        patch.object(experiment, "setup_experiment_config"),
        patch.object(experiment, "setup_experiment_variables"),
        patch("psynet.experiment._write_pre_deploy_constant_registry"),
        patch.object(experiment, "assets") as mock_assets,
        patch.object(experiment, "create_database_snapshot") as mock_db,
    ):
        experiment.pre_deploy(redeploying_from_archive=False)

        # Verify that asset preparation and database snapshot are called
        mock_assets.prepare_for_deployment.assert_called_once()
        mock_db.assert_called_once()


def test_pre_deploy_archive_deployment():
    """Test that pre_deploy skips asset and database operations for archive deployment."""
    experiment = MockExperiment()

    # Mock all the methods that pre_deploy calls
    with (
        patch.object(experiment, "update_deployment_id"),
        patch.object(experiment, "setup_experiment_config"),
        patch.object(experiment, "setup_experiment_variables"),
        patch("psynet.experiment._write_pre_deploy_constant_registry"),
        patch.object(experiment, "assets") as mock_assets,
        patch.object(experiment, "create_database_snapshot") as mock_db,
    ):
        experiment.pre_deploy(redeploying_from_archive=True)

        # Verify that asset preparation and database snapshot are NOT called
        mock_assets.prepare_for_deployment.assert_not_called()
        mock_db.assert_not_called()


def test_source_code_archive_functionality_is_removed():
    assert not hasattr(Experiment, "create_source_code_zip_file")
    import psynet.command_line as command_line

    assert not hasattr(command_line, "_export_source_code")

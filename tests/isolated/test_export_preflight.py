import pytest

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory", "db_session", "deployment_info")
def test_export_preflight_reports_the_commit_of_the_running_image():
    """After ``--update``, the image's commit wins over the one recorded at launch."""
    from psynet import deployment_info
    from psynet.experiment import get_experiment
    from psynet.export.identity import server_project_identity

    experiment = get_experiment()
    experiment.setup_experiment_config()
    experiment.setup_experiment_variables()
    experiment.var.git_commit_sha = "launched"
    deployment_info.write(git_commit_sha="updated")

    assert server_project_identity()["git_commit_sha"] == "updated"

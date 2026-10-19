import pytest
import requests
from dallinger.utils import get_base_url

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.usefixtures("launched_experiment")
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
def test_source_download_is_removed_and_git_provenance_is_recorded(
    launched_experiment,
):
    response = requests.get(
        f"{get_base_url()}/download_source",
        auth=("test_admin", "test_password"),
    )

    assert response.status_code == 404
    assert launched_experiment.var.git_commit_sha
    assert isinstance(launched_experiment.var.git_dirty, bool)

import pytest

from psynet.experiment import get_experiment
from psynet.pytest_psynet import path_to_test_experiment

pytest_plugins = ["pytest_dallinger", "pytest_psynet"]


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("local_module")],
    indirect=True,
)
def test_relative_import_of_experiment_sibling_module(in_experiment_directory):
    exp = get_experiment()
    assert exp.helper_value == 7

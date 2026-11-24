import pytest

from psynet.pytest_psynet import path_to_test_experiment


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("grouper_waiting_logic")],
    indirect=True,
)
def test_parallel_bots_on_waiting_logic_pages_get_grouped(launched_experiment):
    """Unpaced bots answering ``waiting_logic`` pages still form their group."""
    launched_experiment.test_experiment()

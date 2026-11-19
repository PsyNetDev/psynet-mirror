import importlib

import pytest

from psynet.experiment_scaffold import scaffold_missing_files
from psynet.pytest_psynet import path_to_test_experiment
from psynet.testing.locks import experiment_directory_lock
from psynet.utils import working_directory


@pytest.fixture(scope="class")
def experiment_class_imported_before_pytest(experiment_directory):
    """Import the experiment before the fixtures run, as ``psynet test local`` does."""
    from psynet.experiment import import_local_experiment

    with (
        experiment_directory_lock(experiment_directory),
        working_directory(experiment_directory),
        scaffold_missing_files(),
    ):
        return import_local_experiment()["class"]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
class TestExperimentImportedBeforePytestStaysImported:
    def test_importing_the_experiment_module_reuses_its_classes(
        self, experiment_class_imported_before_pytest, in_experiment_directory
    ):
        """A lazy import of the experiment, for example by Dallinger's socket
        server, must not execute experiment.py again."""
        from psynet.experiment import import_local_experiment

        experiment_class = experiment_class_imported_before_pytest
        assert import_local_experiment()["class"] is experiment_class
        module = importlib.import_module(experiment_class.__module__)
        assert getattr(module, experiment_class.__name__) is experiment_class

import re
import warnings

import pytest

from psynet.pytest_psynet import path_to_test_experiment
from psynet.utils import get_config

get_config


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
)
@pytest.mark.usefixtures("launched_experiment")
class TestExp:
    def test_warnings_during_launch(self, debug_experiment):
        pattern = r"[^\n]*Warning: [^\n\r]*"
        warnings = re.findall(pattern, debug_experiment.before)
        # Filter out known external service warnings (npm, Heroku CLI, etc.)
        external_warning_patterns = [
            r"terms of service",
            # PsyNet's legacy local-debug path goes through the Heroku CLI and can emit
            # external Node warnings (for example with Heroku CLI v11) that are not caused
            # by PsyNet.
            r"Closing file descriptor .* on garbage collection",
            r"DeprecationWarning:",
            r"\[DEP0137\].*FileHandle object on garbage collection is deprecated",
            r"\[DEP0060\].*util\._extend.*deprecated",
        ]
        warnings = [
            w
            for w in warnings
            if not any(
                re.search(p, w, re.IGNORECASE) for p in external_warning_patterns
            )
        ]
        if len(warnings) > 0:
            raise AssertionError(
                f"Encountered a warning in experiment launch: {warnings[0]}"
            )

    def test_warnings_during_experiment(self, launched_experiment):
        with warnings.catch_warnings():
            warnings.simplefilter("error", Warning)
            launched_experiment.test_experiment()

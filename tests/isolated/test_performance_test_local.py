import json
import os
import re
import subprocess

import pytest

from psynet.pytest_psynet import path_to_demo_experiment


@pytest.mark.parametrize(
    "experiment_directory", [path_to_demo_experiment("static")], indirect=True
)
@pytest.mark.usefixtures("in_experiment_directory")
def test_performance_test_local(tmp_path):
    """Run ``psynet performance-test local`` on the static demo and check its report."""
    json_output = tmp_path / "out.json"
    result = subprocess.run(
        [
            "psynet",
            "performance-test",
            "local",
            "--n-bots",
            "2",
            "--duration-minutes",
            "0.5",
            "--json-output",
            str(json_output),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        # Keeps the run's logs out of the real ~/psynet-data.
        env={**os.environ, "HOME": str(tmp_path)},
    )
    print(result.stdout, result.stderr, sep="\n")
    assert result.returncode == 0

    [run] = json.loads(json_output.read_text())["results"]
    assert run["n_bots"] == 2
    # A bot that finishes within the test is replaced, so more may start.
    assert run["total_bots_started"] >= 2
    assert run["bots_failed"] == 0
    # Busy CI runners can exceed the p95 limit, so either verdict will do.
    verdict = r"^(Largest passing test: 2 bots at once|No test passed\. At 2, )"
    assert re.search(verdict, result.stdout, re.MULTILINE)

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUITES = sorted((ROOT / "tests" / "javascript").glob("*.test.mjs"))


@pytest.mark.parametrize("suite", SUITES, ids=lambda path: path.name)
def test_node_suite(suite):
    """Include every browser-independent Node suite in the isolated CI job."""
    node = shutil.which("node")
    assert node, "node is required to run the JavaScript tests"
    result = subprocess.run(
        [node, "--test", str(suite.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

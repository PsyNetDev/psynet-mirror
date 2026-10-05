import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "suite",
    ["chatroom-history-merge", "timeline-hold-overlay", "media-upload-queue"],
)
def test_node_suite(suite):
    """Include browser-independent Node suites in the isolated CI job."""
    root = Path(__file__).resolve().parents[2]
    node = shutil.which("node")
    assert node, "node is required to run the JavaScript tests"
    result = subprocess.run(
        [node, "--test", f"tests/javascript/{suite}.test.mjs"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "lucid-termination.test.mjs"


def test_lucid_screening_controls_can_terminate_the_participant():
    """``LucidTerminateControl`` calls ``psynet.terminateParticipant``."""
    node = shutil.which("node")
    assert node, "node is required to run the Lucid termination tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

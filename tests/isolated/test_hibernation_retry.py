import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "hibernation-retry.test.mjs"


def test_submissions_retry_while_a_docker_ssh_app_wakes():
    """A sleeping app's 503 is retried; other failures keep their handling."""
    node = shutil.which("node")
    assert node, "node is required to run the hibernation retry tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

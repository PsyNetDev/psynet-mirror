import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "unknown-participant.test.mjs"


def test_pages_recognise_an_unknown_session():
    """The 'session no longer available' 404 is told apart from other failures."""
    node = shutil.which("node")
    assert node, "node is required to run the unknown-participant tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

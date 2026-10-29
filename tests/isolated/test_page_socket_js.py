import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "page-socket.test.mjs"


def test_page_socket():
    """psynet.websocket wraps the page's /experiment-socket connection."""
    node = shutil.which("node")
    assert node, "node is required to run the page socket tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

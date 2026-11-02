import shutil
import subprocess
from pathlib import Path

from psynet.timeline import PAGE_ENDED_MESSAGE_TYPE

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "page-socket.test.mjs"
SCRIPT = ROOT / "psynet" / "resources" / "scripts" / "page-socket.js"


def test_the_page_ended_type_matches_the_server_s():
    source = SCRIPT.read_text()

    assert f'const PAGE_ENDED = "{PAGE_ENDED_MESSAGE_TYPE}";' in source


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

import shutil
import subprocess
from pathlib import Path

from psynet.live_session import Ready
from psynet.timeline import PAGE_ENDED_MESSAGE_TYPE

ROOT = Path(__file__).resolve().parents[2]
TESTS = [
    ROOT / "tests" / "javascript" / "page-socket.test.mjs",
    ROOT / "tests" / "javascript" / "live-session.test.mjs",
]
SCRIPTS = ROOT / "psynet" / "resources" / "scripts"


def test_the_page_ended_and_ready_types_match_the_server_s():
    page_socket = (SCRIPTS / "page-socket.js").read_text()
    live_session = (SCRIPTS / "live-session.js").read_text()

    assert f'const PAGE_ENDED = "{PAGE_ENDED_MESSAGE_TYPE}";' in page_socket
    assert f'const READY = "{Ready.type}";' in live_session


def test_page_socket_and_live_session():
    """psynet.websocket and psynet.liveSession wrap the page's
    /experiment-socket connections."""
    node = shutil.which("node")
    assert node, "node is required to run the page socket tests"
    result = subprocess.run(
        [node, "--test", *map(str, TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

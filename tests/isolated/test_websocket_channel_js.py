import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "websocket-channel.test.mjs"


def test_websocket_channel_routes_frames():
    """Frames reach the right callbacks, and a refused channel stops reconnecting."""
    node = shutil.which("node")
    assert node, "node is required to run the websocket-channel tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

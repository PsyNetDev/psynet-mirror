import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "chatroom-history-merge.test.mjs"


def test_leftover_live_after_history_counts_duplicate_lines():
    """Pending identical lines use snapshot counts, not existence."""
    node = shutil.which("node")
    assert node, "node is required to run the chat history merge tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

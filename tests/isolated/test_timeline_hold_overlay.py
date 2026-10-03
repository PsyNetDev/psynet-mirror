import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "javascript" / "timeline-hold-overlay.test.mjs"


def test_reused_hold_overlay_stays_inert():
    """Dynamic overlay reuse must keep the preserved page inert."""
    node = shutil.which("node")
    assert node, "node is required to run the timeline-hold overlay tests"
    result = subprocess.run(
        [node, "--test", str(TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

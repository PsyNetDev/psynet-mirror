import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ci" / "ensure-dallinger-docker-network.sh"


def _run_with_failing_docker(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", "-c", f'. "{SCRIPT}"'],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ensure_dallinger_docker_network_aborts_when_docker_fails(tmp_path):
    result = _run_with_failing_docker(tmp_path)

    assert result.returncode != 0
    assert "Confirming that dallinger_postgres is running" not in result.stdout

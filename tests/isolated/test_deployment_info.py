import subprocess
import tempfile
from pathlib import Path

import pytest

from psynet import deployment_info
from psynet.utils import working_directory


def test_deployment_info():
    with tempfile.TemporaryDirectory() as tempdir:
        with working_directory(tempdir):
            with pytest.raises(FileNotFoundError):
                deployment_info.read("x")

            deployment_info.reset()

            deployment_info.write(x=3)
            assert deployment_info.read("x") == 3

            deployment_info.reset()

            with pytest.raises(KeyError):
                deployment_info.read("x")


def _git(*args):
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _initialize_deployment_info():
    deployment_info.init(
        redeploying_from_archive=False,
        mode="debug",
        is_local_deployment=True,
        is_ssh_deployment=False,
        server=None,
        app=None,
    )


def test_deployment_info_records_git_provenance(tmp_path):
    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        tracked_file = Path("experiment.py")
        tracked_file.write_text("content")
        _git("add", "experiment.py")
        _git("commit", "--quiet", "-m", "Initial commit")

        _initialize_deployment_info()

        assert deployment_info.read("git_commit_sha") == _git("rev-parse", "HEAD")
        assert deployment_info.read("git_dirty") is False

        tracked_file.write_text("changed")
        _initialize_deployment_info()

        assert deployment_info.read("git_dirty") is True


def test_git_dirty_is_scoped_to_experiment_directory(tmp_path):
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    sibling = tmp_path / "notes.txt"
    sibling.write_text("clean")
    (experiment_dir / "experiment.py").write_text("clean")
    (experiment_dir / "deploy.toml").write_text(
        'version = 1\n[exclude]\npaths = [".deploy"]\n'
    )

    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        _git("add", ".")
        _git("commit", "--quiet", "-m", "Initial commit")
        sibling.write_text("dirty")

    with working_directory(experiment_dir):
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is False

        Path("experiment.py").write_text("dirty")
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is True

        Path("experiment.py").write_text("clean")
        Path("experiment.py").unlink()
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is True


def test_git_dirty_is_scoped_to_deployment_plan(tmp_path):
    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        Path("experiment.py").write_text("content")
        Path(".gitignore").write_text("secret.txt\ndata/\n")
        Path("deploy.toml").write_text(
            'version = 1\n[exclude]\npaths = [".deploy", "data"]\n'
        )
        data = Path("data")
        data.mkdir()
        excluded_tracked = data / "tracked.txt"
        excluded_tracked.write_text("original")
        _git("add", ".")
        _git("add", "--force", "data/tracked.txt")
        _git("commit", "--quiet", "-m", "Initial commit")

        excluded_tracked.write_text("changed")
        (data / "untracked.txt").write_text("excluded")
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is False

        Path("experiment.py").write_text("changed")
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is True
        Path("experiment.py").write_text("content")

        Path("secret.txt").write_text("ignored but selected")
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is True

        Path("secret.txt").unlink()
        Path("notes.txt").write_text("untracked and selected")
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is True

        Path("notes.txt").unlink()
        Path("experiment.py").write_text("content")
        excluded_tracked.unlink()
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is False

        Path("experiment.py").unlink()
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is True


def test_git_dirty_ignores_deletions_excluded_by_name(tmp_path):
    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        Path("experiment.py").write_text("content")
        Path("deploy.toml").write_text(
            'version = 1\n[exclude]\npaths = [".deploy"]\nnames = [".idea"]\n'
        )
        idea = Path(".idea")
        idea.mkdir()
        workspace = idea / "workspace.xml"
        workspace.write_text("local")
        _git("add", ".")
        _git("add", "--force", ".idea/workspace.xml")
        _git("commit", "--quiet", "-m", "Initial commit")

        workspace.unlink()
        _initialize_deployment_info()
        assert deployment_info.read("git_dirty") is False


def test_deployment_info_handles_missing_git_repository(tmp_path):
    with working_directory(tmp_path):
        _initialize_deployment_info()

        assert deployment_info.read("git_commit_sha") is None
        assert deployment_info.read("git_dirty") is None

import os
import subprocess
import tempfile
from pathlib import Path

import click
import jsonpickle
import pytest

from psynet import deployment_info
from psynet.experiment_scaffold import _template_contents
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


def test_deployment_info_reads_see_external_writes_and_return_copies(tmp_path):
    with working_directory(tmp_path):
        deployment_info.reset()
        deployment_info.write(x=[1])

        deployment_info.read("x").append(2)
        deployment_info.read_all()["x"].append(2)
        assert deployment_info.read("x") == [1]

        external_write = Path(deployment_info.path).with_suffix(".external")
        external_write.write_text(jsonpickle.encode({"x": [2]}, keys=True))
        os.replace(external_write, deployment_info.path)
        assert deployment_info.read("x") == [2]


def test_failed_deployment_info_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    with working_directory(tmp_path):
        deployment_info.reset()
        deployment_info.write(x=1)

        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", fail)
        with pytest.raises(OSError, match="disk full"):
            deployment_info.write(x=2)

        assert os.listdir(".deploy") == ["deployment_info.json"]
        assert deployment_info.read("x") == 1


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
        assert "experiment.py" in deployment_info.read("git_dirty_paths")


def test_deploy_warns_about_uncommitted_files(tmp_path, capsys):
    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        Path("deploy.toml").write_text('version = 1\n[exclude]\nnames = [".env"]\n')
        _git("add", ".")
        _git("commit", "--quiet", "-m", "Initial commit")
        deployment_info.warn_about_uncommitted_deployment_changes(confirm=None)
        assert "uncommitted" not in capsys.readouterr().err

        Path(".env").write_text("excluded")
        for i in range(12):
            Path(f"stimulus_{i:02}.txt").write_text("new")
        deployment_info.warn_about_uncommitted_deployment_changes(confirm=None)
        err = capsys.readouterr().err
        assert "  stimulus_00.txt" in err and "... and 2 more" in err
        assert ".env" not in err

        with pytest.raises(click.Abort):
            deployment_info.warn_about_uncommitted_deployment_changes(
                confirm=lambda question: False
            )


def test_git_ignored_scaffold_files_are_not_uncommitted_changes(tmp_path):
    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        Path(".gitignore").write_text("Dockerfile\nAGENTS.md\nREADME.md\nstimuli.csv\n")
        Path("deploy.toml").write_text("version = 1\n[exclude]\nnames = []\n")
        _git("add", ".")
        _git("commit", "--quiet", "-m", "Initial commit")
        for name in ("Dockerfile", "AGENTS.md", "stimuli.csv"):
            Path(name).write_text("generated")
        Path("README.md").write_bytes(_template_contents("README.md"))
        assert deployment_info.uncommitted_deployment_paths() == ["stimuli.csv"]

        # README.md is the author's own once it differs from its template.
        Path("README.md").write_text("My experiment")
        assert deployment_info.uncommitted_deployment_paths() == [
            "README.md",
            "stimuli.csv",
        ]


@pytest.mark.parametrize(
    "mode, tty, prompted",
    [("live", True, True), ("live", False, False), ("sandbox", True, False)],
)
def test_uncommitted_files_prompt_only_interactive_live_deploys(
    tmp_path, monkeypatch, capsys, mode, tty, prompted
):
    from psynet import command_line

    questions = []
    monkeypatch.setenv("SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(command_line, "_stdin_is_interactive", lambda: tty)
    monkeypatch.setattr(
        command_line, "user_confirms", lambda q: questions.append(q) or True
    )
    with working_directory(tmp_path):
        _git("init", "--quiet")
        _git("config", "user.email", "test@example.com")
        _git("config", "user.name", "Test User")
        Path("requirements.txt").write_text("psynet[experiment]==14.0.0\n")
        Path("deploy.toml").write_text("version = 1\n[exclude]\n")
        _git("add", ".")
        _git("commit", "--quiet", "-m", "Initial commit")
        Path("experiment.py").write_text("uncommitted")

        if mode == "live":
            command_line.run_pre_checks_deploy(local_=False, recruiter=None)
        else:
            command_line.run_pre_checks_sandbox()

    assert bool(questions) == prompted
    assert ("  experiment.py" in capsys.readouterr().err) == (mode == "live")


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

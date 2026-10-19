import os
import tempfile
from pathlib import Path

import pytest

from psynet.command_line import (
    check_psynet_requirement_includes_experiment_extra,
    check_psynet_requirement_is_unambiguous,
)
from psynet.experiment_scaffold import (
    get_psynet_requirement,
    is_unambiguous_psynet_requirement,
    requirement_includes_experiment_extra,
)
from psynet.utils import working_directory


@pytest.mark.parametrize(
    "requirement, expected",
    [
        ("psynet", False),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet", False),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet@master#egg=psynet", False),
        ("psynet==10.1.0", True),
        ("psynet == 10.1.0", True),
        (
            "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@"
            "45f317688af59350f9a6f3052fd73076318f2775#egg=psynet",
            True,
        ),
        (
            "psynet@git+ssh://git@git.example.com/alice/PsyNet@"
            "45f317688af59350f9a6f3052fd73076318f2775#egg=psynet",
            True,
        ),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet@45f31768#egg=psynet", True),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.1.0#egg=psynet", True),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.1.0rc1#egg=psynet", True),
    ],
)
def test_is_unambiguous_psynet_requirement(requirement, expected):
    assert is_unambiguous_psynet_requirement(requirement) is expected


def test_get_psynet_requirement_finds_name_and_git_egg_forms():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("requirements.txt").write_text(
                "# comment\nother-package==1.0\npsynet==10.1.0\n"
            )
            assert get_psynet_requirement() == "psynet==10.1.0"

            Path("requirements.txt").write_text(
                "git+https://gitlab.com/PsyNetDev/PsyNet@"
                "45f317688af59350f9a6f3052fd73076318f2775#egg=psynet\n"
            )
            assert get_psynet_requirement().endswith("#egg=psynet")


def test_get_psynet_requirement_rejects_multiple_entries():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("requirements.txt").write_text("psynet==10.1.0\npsynet==10.2.0\n")
            with pytest.raises(ValueError, match="multiple PsyNet requirements"):
                get_psynet_requirement()


def test_check_psynet_requirement_is_unambiguous_missing_version():
    try:
        del os.environ["SKIP_CHECK_PSYNET_VERSION_REQUIREMENT"]
    except KeyError:
        pass

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write("psynet\n")
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="When deploying an experiment, you need to specify PsyNet in an unambiguous way. "
                    "This means you can't just give a branch name, e.g. master; you have to specify a particular version "
                    "or a commit hash.",
                ):
                    check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_extension():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            os.environ["SKIP_CHECK_PSYNET_VERSION_REQUIREMENT"] = "1"
            check_psynet_requirement_is_unambiguous()
            del os.environ["SKIP_CHECK_PSYNET_VERSION_REQUIREMENT"]

            for extension in ["", ".git"]:
                with open("requirements.txt", "w") as file:
                    file.write(
                        f"psynet@git+https://gitlab.com/PsyNetDev/PsyNet{extension}\n"
                    )
                    file.flush()

                    with pytest.raises(
                        ValueError,
                        match="When deploying an experiment, you need to specify PsyNet in an unambiguous way. "
                        "This means you can't just give a branch name, e.g. master; you have to specify a particular version "
                        "or a commit hash.",
                    ):
                        check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_master_branch():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            for extension in ["", ".git"]:
                for egg in ["", "#egg=psynet"]:
                    with open("requirements.txt", "w") as file:
                        file.write(
                            f"psynet@git+https://gitlab.com/PsyNetDev/PsyNet{extension}@master{egg}\n"
                        )
                        file.flush()

                    with pytest.raises(
                        ValueError,
                        match="When deploying an experiment, you need to specify PsyNet in an unambiguous way. "
                        "This means you can't just give a branch name, e.g. master; you have to specify a particular version "
                        "or a commit hash.",
                    ):
                        check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_commit_hash():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            for extension in ["", ".git"]:
                for egg in ["", "#egg=psynet"]:
                    with open("requirements.txt", "w") as file:
                        file.write(
                            f"psynet@git+https://gitlab.com/PsyNetDev/PsyNet{extension}@45f317688af59350f9a6f3052fd73076318f2775{egg}\n"
                        )
                        file.flush()

                        check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_fork_commit_hash():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/alice/PsyNet@"
                    "45f317688af59350f9a6f3052fd73076318f2775#egg=psynet\n"
                )
                file.flush()
                check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_ssh_commit_hash():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+ssh://git@git.example.com/alice/PsyNet@"
                    "45f317688af59350f9a6f3052fd73076318f2775#egg=psynet\n"
                )
                file.flush()
                check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_short_commit_hash():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            for extension in ["", ".git"]:
                for egg in ["", "#egg=psynet"]:
                    with open("requirements.txt", "w") as file:
                        file.write(
                            f"psynet@git+https://gitlab.com/PsyNetDev/PsyNet{extension}@45f31768{egg}\n"
                        )
                        file.flush()

                        check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_version_tag():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            for extension in ["", ".git"]:
                for egg in ["", "#egg=psynet"]:
                    for space in ["", " "]:
                        for prerelease in ["", "rc0", "rc1", "a0", "a1"]:
                            with open("requirements.txt", "w") as file:
                                file.write(
                                    f"psynet{space}@{space}git+https://gitlab.com/PsyNetDev/PsyNet{extension}@v10.1.0{prerelease}{egg}\n"
                                )
                                file.flush()

                                check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_name_based():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write("psynet==10.1.0\n")
                file.flush()

                check_psynet_requirement_is_unambiguous()


def test_check_psynet_requirement_is_unambiguous_name_based_with_spaces():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write("psynet == 10.1.0\n")
                file.flush()

                check_psynet_requirement_is_unambiguous()


@pytest.mark.parametrize(
    "requirement",
    [
        "psynet[experiment] @ file:///home/frank/projects/PsyNet",
        "-e file:///home/frank/projects/PsyNet#egg=psynet[experiment]",
        "psynet[experiment] @ file:///tmp/psynet-14.0.0-py3-none-any.whl",
    ],
)
def test_check_psynet_requirement_is_unambiguous_local_path_suggests_commit_pin(
    requirement,
):
    try:
        del os.environ["SKIP_CHECK_PSYNET_VERSION_REQUIREMENT"]
    except KeyError:
        pass

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            Path("requirements.txt").write_text(f"{requirement}\n")
            with pytest.raises(ValueError, match="psynet setup --psynet-source commit"):
                check_psynet_requirement_is_unambiguous()


@pytest.mark.parametrize(
    "requirement, expected",
    [
        ("psynet[experiment]==14.0.0", True),
        (
            "psynet[experiment] @ git+https://gitlab.com/PsyNetDev/PsyNet.git@v14.0.0rc2",
            True,
        ),
        ("PsyNet[Experiment]==14.0.0", True),
        ("psynet[docs, experiment]==14.0.0", True),
        ("-e file:///tmp/PsyNet#egg=psynet[experiment]", True),
        ("psynet==14.0.0", False),
        ("psynet @ git+https://gitlab.com/PsyNetDev/PsyNet.git@v14.0.0rc2", False),
        ("psynet[docs]==14.0.0", False),
        ("psynet[experimental]==14.0.0", False),
        ("-e file:///tmp/PsyNet#egg=psynet", False),
    ],
)
def test_requirement_includes_experiment_extra(requirement, expected):
    assert requirement_includes_experiment_extra(requirement) is expected


def test_deploy_rejects_psynet_pin_without_experiment_extra():
    try:
        del os.environ["SKIP_CHECK_PSYNET_EXPERIMENT_EXTRA"]
    except KeyError:
        pass

    with tempfile.TemporaryDirectory() as directory:
        with working_directory(directory):
            Path("requirements.txt").write_text(
                "psynet @ git+https://gitlab.com/PsyNetDev/PsyNet.git@v14.0.0rc2\n"
            )
            with pytest.raises(ValueError, match=r"psynet\[experiment\]") as error:
                check_psynet_requirement_includes_experiment_extra()
            message = str(error.value)
            assert "clock process fails to start" in message
            assert (
                "psynet[experiment] @ git+https://gitlab.com/PsyNetDev/PsyNet.git@v14.0.0rc2"
                in message
            )

            Path("requirements.txt").write_text("psynet[experiment]==14.0.0\n")
            check_psynet_requirement_includes_experiment_extra()

            os.environ["SKIP_CHECK_PSYNET_EXPERIMENT_EXTRA"] = "1"
            Path("requirements.txt").write_text("psynet==14.0.0\n")
            check_psynet_requirement_includes_experiment_extra()
            del os.environ["SKIP_CHECK_PSYNET_EXPERIMENT_EXTRA"]


@pytest.mark.parametrize(
    "requirement, suggested",
    [
        ("psynet==14.0.0", "psynet[experiment]==14.0.0"),
        ("psynet[docs]==14.0.0", "psynet[docs,experiment]==14.0.0"),
        (
            "-e file:///tmp/PsyNet#egg=psynet[docs]",
            "-e file:///tmp/PsyNet#egg=psynet[docs,experiment]",
        ),
    ],
)
def test_experiment_extra_error_suggests_pin_that_passes(
    requirement, suggested, monkeypatch, tmp_path
):
    monkeypatch.delenv("SKIP_CHECK_PSYNET_EXPERIMENT_EXTRA", raising=False)
    monkeypatch.chdir(tmp_path)
    requirements = tmp_path / "requirements.txt"

    requirements.write_text(f"{requirement}\n")
    with pytest.raises(ValueError) as error:
        check_psynet_requirement_includes_experiment_extra()
    assert f"Change it to:\n  {suggested}\n" in str(error.value)

    requirements.write_text(f"{suggested}\n")
    check_psynet_requirement_includes_experiment_extra()


@pytest.mark.parametrize(
    "requirement, is_release",
    [
        ("psynet[experiment]==14.0.0", True),
        ("psynet[experiment]==14.0.0rc1", True),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v14.0.0#egg=psynet", True),
        ("psynet @ git+https://gitlab.com/alice/my-fork.git@v14.0.0", True),
        ("psynet@git+ssh://git@gitlab.com/alice/PsyNet.git@v14.0.0rc2", True),
        ("psynet == 14.0.0", True),
        ("psynet[experiment]==14.1.0a2", False),
        ("psynet@git+https://gitlab.com/PsyNetDev/PsyNet@45f31768#egg=psynet", False),
        ("psynet[experiment]", False),
    ],
)
def test_live_deploys_ask_before_installing_a_development_psynet(
    tmp_path, monkeypatch, capsys, requirement, is_release
):
    import click

    from psynet import command_line

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SKIP_CHECK_PSYNET_VERSION_REQUIREMENT", raising=False)
    Path("requirements.txt").write_text(f"{requirement}\n")
    questions = []
    monkeypatch.setattr(
        command_line, "user_confirms", lambda q: questions.append(q) or False
    )

    if is_release:
        command_line.confirm_deploying_development_psynet()
        assert not questions
        return

    with pytest.raises(click.Abort):
        command_line.confirm_deploying_development_psynet()
    assert requirement in questions[0]

    monkeypatch.setenv("SKIP_CHECK_PSYNET_VERSION_REQUIREMENT", "1")
    command_line.confirm_deploying_development_psynet()
    assert len(questions) == 1
    assert "development version of PsyNet" in capsys.readouterr().err

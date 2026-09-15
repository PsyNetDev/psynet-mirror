import os
import tempfile
from pathlib import Path

import pytest

from psynet.command_line import check_psynet_requirement_is_unambiguous
from psynet.experiment_scaffold import (
    get_psynet_requirement,
    is_unambiguous_psynet_requirement,
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

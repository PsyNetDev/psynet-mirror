import os
import tempfile
from unittest.mock import patch

import pytest

from psynet.utils import working_directory
from psynet.version import check_core_dependency_versions_match_requirements


# PsyNet tests
def test_skip_version_check_key_error():
    with pytest.raises(KeyError, match="'SKIP_VERSION_CHECK'"):
        del os.environ["SKIP_VERSION_CHECK"]

    os.environ["SKIP_VERSION_CHECK"] = "1"
    check_core_dependency_versions_match_requirements()
    del os.environ["SKIP_VERSION_CHECK"]


@patch("psynet.__version__", "10.0.0")
def test_check_core_dependency_versions_psynet_editable_version_tag_with_egg():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if versions specified and installed differ
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v9.9.9#egg=psynet"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The PsyNet versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: 10.0.0[\\n\\r\\s]+"
                    "Version specified in requirements.txt: 9.9.9",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
def test_check_core_dependency_versions_psynet_editable_version_tag_without_egg():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if versions specified and installed differ
            with open("requirements.txt", "w") as file:
                file.write("psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@v9.9.9")
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The PsyNet versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: 10.0.0[\\n\\r\\s]+"
                    "Version specified in requirements.txt: 9.9.9",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_requirement_line_from_pip_freeze")
def test_check_core_dependency_versions_psynet_editable_commit_hash(
    mock_get_requirement,
):
    mock_get_requirement.return_value = "-e git+ssh://git@gitlab.com/PsyNetDev/PsyNet@COMMIT_HASH_FROM_PIP_FREEEZE#egg=psynet"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if commit hashes specified and installed differ
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@COMMIT_HASH_FROM_REQUIREMENTS#egg=psynet\n"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The PsyNet versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: COMMIT_HASH_FROM_PIP_FREEEZE[\\n\\r\\s]+"
                    "Version specified in requirements.txt: COMMIT_HASH_FROM_REQUIREMENTS",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_requirement_line_from_pip_freeze")
def test_check_core_dependency_versions_psynet_pip_install_requirement(
    mock_get_requirement,
):
    mock_get_requirement.return_value = "psynet==10.0.0"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if versions specified (psynet==X.Y.Z) and installed differ
            with open("requirements.txt", "w") as file:
                file.write("psynet==9.9.9")
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The PsyNet versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: 10.0.0[\\n\\r\\s]+"
                    "Version specified in requirements.txt: 9.9.9",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0rc1")
@patch("psynet.version.get_requirement_line_from_pip_freeze")
def test_check_core_dependency_versions_psynet_pip_install_requirement_rc(
    mock_get_requirement,
):
    mock_get_requirement.return_value = "PsyNet==10.0.0rc1"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Do not NOT raise an error if versions specified (psynet==X.Y.ZrcN) and installed are the same
            with open("requirements.txt", "w") as file:
                file.write("psynet==10.0.0rc1")
                file.flush()
            check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_requirement_line_from_pip_freeze")
def test_check_core_dependency_versions_psynet_pip_install_commit_hash(
    mock_get_requirement,
):
    mock_get_requirement.return_value = "psynet==10.0.0"

    for extension in ["", ".git"]:
        with tempfile.TemporaryDirectory() as dir:
            with working_directory(dir):
                # Raise an error if commit hash specified and version installed differ
                with open("requirements.txt", "w") as file:
                    file.write(
                        f"psynet@git+https://gitlab.com/PsyNetDev/PsyNet{extension}@a4d0d6153150deaae1b456f7dd5c081c5ef04b1d#egg=psynet\n"
                    )
                    file.flush()

                    with pytest.raises(
                        ValueError,
                        match="The PsyNet versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                        "Version installed locally: 10.0.0[\\n\\r\\s]+"
                        "Version specified in requirements.txt: a4d0d6153150deaae1b456f7dd5c081c5ef04b1d",
                    ):
                        check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
def test_check_core_dependency_versions_psynet_commented():
    for extension in ["", ".git"]:
        with tempfile.TemporaryDirectory() as dir:
            with working_directory(dir):
                # In a former PsyNet version, the comments were not respected, so
                # the following requirements would produce an inconsistent versions error
                with open("requirements.txt", "w") as file:
                    file.write("# psynet==9.9.9\n")
                    file.write("psynet==10.0.0\n")
                    file.flush()

                    check_core_dependency_versions_match_requirements()


# Dallinger tests
@patch("psynet.__version__", "10.0.0")
@patch("psynet.version._get_dallinger_version", new=lambda: "9.0.0")
def test_check_core_dependency_versions_dallinger_editable_requirement():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if dallinger version specified and installed differ
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0#egg=psynet\n"
                    "dallinger==8.8.8"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The Dallinger versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: 9.0.0[\\n\\r\\s]+"
                    "Version specified in requirements.txt: 8.8.8",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version._get_dallinger_version", new=lambda: "9.0.0")
def test_check_core_dependency_versions_dallinger_unspecified_requirement():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Do NOT raise an error if dallinger requirement is just specified with its package name
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0#egg=psynet\n"
                    "dallinger"
                )
                file.flush()

                check_core_dependency_versions_match_requirements()

            # Do NOT raise an error if dallinger requirement is not specified
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0#egg=psynet"
                )
                file.flush()

                check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_requirement_line_from_pip_freeze")
def test_check_core_dependency_versions_dallinger_editable_commit_hash_with_egg(
    mock_get_requirement,
):
    mock_get_requirement.return_value = "-e git+https://github.com/Dallinger/Dallinger@COMMIT_HASH_FROM_PIP_FREEEZE#egg=dallinger"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if commit hashes specified and installed differ
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0#egg=psynet\n"
                    "dallinger@git+https://github.com/Dallinger/Dallinger@COMMIT_HASH_FROM_REQUIREMENTS#egg=dallinger"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The Dallinger versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: COMMIT_HASH_FROM_PIP_FREEEZE[\\n\\r\\s]+"
                    "Version specified in requirements.txt: COMMIT_HASH_FROM_REQUIREMENTS",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_requirement_line_from_pip_freeze")
def test_check_core_dependency_versions_dallinger_editable_commit_hash_without_egg(
    mock_get_requirement,
):
    mock_get_requirement.return_value = (
        "-e git+https://github.com/Dallinger/Dallinger@COMMIT_HASH_FROM_PIP_FREEEZE"
    )

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Raise an error if commit hashes specified and installed differ
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0\n"
                    "dallinger@git+https://github.com/Dallinger/Dallinger@COMMIT_HASH_FROM_REQUIREMENTS"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The Dallinger versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: COMMIT_HASH_FROM_PIP_FREEEZE[\\n\\r\\s]+"
                    "Version specified in requirements.txt: COMMIT_HASH_FROM_REQUIREMENTS",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version._get_dallinger_version", new=lambda: "9.0.0")
def test_check_dallinger_versions_pip_install():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Do NOT raise an error if dallinger version specified and installed are the same
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.0.0#egg=psynet\n"
                    "dallinger==9.0.0"
                )
                file.flush()

                check_core_dependency_versions_match_requirements()

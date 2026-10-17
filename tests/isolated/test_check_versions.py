import json
import os
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from psynet.utils import working_directory
from psynet.version import (
    check_core_dependency_versions_match_requirements,
    get_installed_commit_or_version,
)


def _install_fake_distribution(
    tmp_path, monkeypatch, direct_url=None, name="fakepkg", version="1.2.3"
):
    """Make a distribution visible to ``importlib.metadata``, ahead of real ones."""
    dist_info = tmp_path / "site-packages" / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n")
    if direct_url is not None:
        (dist_info / "direct_url.json").write_text(json.dumps(direct_url))
    monkeypatch.syspath_prepend(str(dist_info.parent))


def _git(path, *args):
    """Run git in ``path`` and return its stripped output."""
    return subprocess.check_output(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com"]
        + ["-C", str(path), *args],
        text=True,
    ).strip()


def _editable(path):
    return {"url": path.as_uri(), "dir_info": {"editable": True}}


def test_installed_commit_of_editable_git_worktree(tmp_path, monkeypatch):
    repo, worktree = tmp_path / "repo", tmp_path / "worktree"
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a")
    _git(repo, "worktree", "add", "-q", "-b", "wt", str(worktree))
    _git(worktree, "commit", "-q", "--allow-empty", "-m", "b")
    _install_fake_distribution(tmp_path, monkeypatch, _editable(worktree))

    assert get_installed_commit_or_version("fakepkg") == _git(
        worktree, "rev-parse", "HEAD"
    )


@pytest.mark.parametrize(
    "direct_url, expected",
    [
        (
            {
                "url": "https://gitlab.com/PsyNetDev/PsyNet.git",
                "vcs_info": {"vcs": "git", "commit_id": "a" * 40},
            },
            "a" * 40,
        ),
        (None, "1.2.3"),
    ],
    ids=["vcs", "index"],
)
def test_installed_commit_or_version_from_metadata(
    tmp_path, monkeypatch, direct_url, expected
):
    _install_fake_distribution(tmp_path, monkeypatch, direct_url)

    assert get_installed_commit_or_version("fakepkg") == expected


def test_installed_commit_or_version_of_missing_package():
    with pytest.raises(ValueError, match="'no-such-package' is not installed"):
        get_installed_commit_or_version("no-such-package")


@pytest.mark.parametrize("inside_repo", [False, True])
def test_commit_pin_fails_for_editable_install_without_own_checkout(
    tmp_path, monkeypatch, inside_repo
):
    source = tmp_path / "repo" / "PsyNet"
    source.mkdir(parents=True)
    if inside_repo:
        _git(tmp_path / "repo", "init", "-q")
    _install_fake_distribution(
        tmp_path, monkeypatch, _editable(source), name="psynet", version="14.0.0a0"
    )

    with working_directory(tmp_path):
        (tmp_path / "requirements.txt").write_text(
            f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{'a' * 40}"
        )
        with pytest.raises(ValueError, match="Git commit cannot be determined"):
            check_core_dependency_versions_match_requirements()


@pytest.mark.parametrize(
    "change, warns", [("tracked", True), ("untracked", False), (None, False)]
)
def test_commit_pin_warns_about_uncommitted_editable_changes(
    tmp_path, monkeypatch, capsys, change, warns
):
    source = tmp_path / "PsyNet"
    _git(tmp_path, "init", "-q", str(source))
    (source / "tracked.py").write_text("a = 1\n")
    _git(source, "add", "tracked.py")
    _git(source, "commit", "-q", "-m", "a")
    if change:
        (source / f"{change}.py").write_text("a = 2\n")
    _install_fake_distribution(
        tmp_path, monkeypatch, _editable(source), name="psynet", version="14.0.0a0"
    )
    (tmp_path / "requirements.txt").write_text(
        f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{_git(source, 'rev-parse', 'HEAD')}"
    )

    with working_directory(tmp_path):
        check_core_dependency_versions_match_requirements()

    assert ("uncommitted changes" in capsys.readouterr().err) == warns


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
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_psynet_editable_commit_hash(
    mock_installed,
):
    mock_installed.return_value = "INSTALLED_COMMIT_HASH"

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
                    "Version installed locally: INSTALLED_COMMIT_HASH[\\n\\r\\s]+"
                    "Version specified in requirements.txt: COMMIT_HASH_FROM_REQUIREMENTS",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_psynet_pip_install_requirement(
    mock_installed,
):
    mock_installed.return_value = "10.0.0"

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


@patch("psynet.__version__", "13.4.0a0")
def test_check_core_dependency_versions_release_pin_rejects_development_install():
    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write(
                    "psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@v14.0.0rc2"
                )

            with pytest.raises(
                ValueError,
                match="Version installed locally: 13.4.0a0[\\n\\r\\s]+"
                "Version specified in requirements.txt: 14.0.0rc2",
            ):
                check_core_dependency_versions_match_requirements()


@pytest.mark.parametrize(
    "pinned_commit, matches",
    [
        ("2da1cc662d0db5969a14f20f18a2e1834187ff8b", True),
        ("2da1cc66", True),
        ("2DA1CC66", True),
        ("45f31768", False),
    ],
)
@pytest.mark.parametrize("repo", ["PsyNetDev/PsyNet", "alice/my-fork"])
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_commit_pin_matches_installed_commit(
    mock_installed, repo, pinned_commit, matches
):
    mock_installed.return_value = "2da1cc662d0db5969a14f20f18a2e1834187ff8b"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write(
                    f"psynet[experiment] @ git+https://gitlab.com/{repo}.git"
                    f"@{pinned_commit}"
                )

            if matches:
                check_core_dependency_versions_match_requirements()
            else:
                with pytest.raises(ValueError, match="do not match"):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_branch_pin_skips_development_install(
    mock_installed, capsys
):
    mock_installed.return_value = "13.4.0a0"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write("psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@master")

            check_core_dependency_versions_match_requirements()

    assert "Skipped version check for PsyNet" in capsys.readouterr().out


@patch("psynet.__version__", "10.0.0rc1")
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_psynet_pip_install_requirement_rc(
    mock_installed,
):
    mock_installed.return_value = "10.0.0rc1"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            # Do not NOT raise an error if versions specified (psynet==X.Y.ZrcN) and installed are the same
            with open("requirements.txt", "w") as file:
                file.write("psynet==10.0.0rc1")
                file.flush()
            check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_psynet_pip_install_commit_hash(
    mock_installed,
):
    mock_installed.return_value = "10.0.0"

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
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_dallinger_editable_commit_hash_with_egg(
    mock_installed,
):
    mock_installed.return_value = "INSTALLED_COMMIT_HASH"

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
                    "Version installed locally: INSTALLED_COMMIT_HASH[\\n\\r\\s]+"
                    "Version specified in requirements.txt: COMMIT_HASH_FROM_REQUIREMENTS",
                ):
                    check_core_dependency_versions_match_requirements()


@patch("psynet.__version__", "10.0.0")
@patch("psynet.version.get_installed_commit_or_version")
def test_check_core_dependency_versions_dallinger_editable_commit_hash_without_egg(
    mock_installed,
):
    mock_installed.return_value = "INSTALLED_COMMIT_HASH"

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
                    "Version installed locally: INSTALLED_COMMIT_HASH[\\n\\r\\s]+"
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

import json
import os
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from psynet.utils import working_directory
from psynet.version import (
    check_core_dependency_versions_match_requirements,
    collect_core_dependency_version_info_from_requirements,
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
        _git(tmp_path / "repo", "commit", "-q", "--allow-empty", "-m", "a")
    _install_fake_distribution(
        tmp_path, monkeypatch, _editable(source), name="psynet", version="14.0.0a0"
    )

    with working_directory(tmp_path):
        (tmp_path / "requirements.txt").write_text(
            f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{'a' * 40}"
        )
        with pytest.raises(ValueError, match="Git commit cannot be determined"):
            check_core_dependency_versions_match_requirements()


def test_skipped_editable_package_without_own_checkout_is_not_looked_up(
    tmp_path, monkeypatch
):
    source = tmp_path / "PsyNet"
    source.mkdir()
    _install_fake_distribution(
        tmp_path, monkeypatch, _editable(source), name="psynet", version="14.0.0a0"
    )

    with working_directory(tmp_path):
        (tmp_path / "requirements.txt").write_text(
            f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{'a' * 40}"
        )
        check_core_dependency_versions_match_requirements(skip=("psynet",))


@pytest.mark.parametrize(
    "change, experiment_dir, warns",
    [
        ("tracked.py", ".", True),
        ("untracked.py", ".", False),
        (None, ".", False),
        ("tracked.py", "PsyNet/demo", True),
        ("demo/experiment.py", "PsyNet/demo", False),
        ("tracked.py", "PsyNet", True),
        ("demo/experiment.py", "PsyNet/de*", True),
    ],
)
def test_commit_pin_warns_about_uncommitted_editable_changes(
    tmp_path, monkeypatch, capsys, change, experiment_dir, warns
):
    source = tmp_path / "PsyNet"
    _git(tmp_path, "init", "-q", str(source))
    (source / "demo").mkdir()
    for path in ["tracked.py", "demo/experiment.py"]:
        (source / path).write_text("a = 1\n")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "a")
    if change:
        (source / change).write_text("a = 2\n")
    _install_fake_distribution(
        tmp_path, monkeypatch, _editable(source), name="psynet", version="14.0.0a0"
    )
    experiment_dir = tmp_path / experiment_dir
    experiment_dir.mkdir(exist_ok=True)
    (experiment_dir / "requirements.txt").write_text(
        f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{_git(source, 'rev-parse', 'HEAD')}"
    )

    with working_directory(experiment_dir):
        check_core_dependency_versions_match_requirements()

    assert ("uncommitted changes" in capsys.readouterr().err) == warns


@pytest.mark.parametrize("pin_matches", [True, False])
def test_dallinger_is_compared_with_constraints_pin(
    tmp_path, monkeypatch, capsys, pin_matches
):
    source = tmp_path / "Dallinger"
    _git(tmp_path, "init", "-q", str(source))
    _git(source, "commit", "-q", "--allow-empty", "-m", "a")
    installed = _git(source, "rev-parse", "HEAD")
    _install_fake_distribution(
        tmp_path, monkeypatch, _editable(source), name="dallinger", version="12.5.0a1"
    )
    pinned = installed if pin_matches else "406f3c147354477fc11d1247403b65577c7a349f"
    (tmp_path / "requirements.txt").write_text("dallinger~=12.4\n")
    (tmp_path / "constraints.txt").write_text(
        f"dallinger[docker] @ git+https://github.com/Dallinger/Dallinger.git@{pinned}\n"
        "    # via psynet\n"
    )

    with working_directory(tmp_path):
        if pin_matches:
            check_core_dependency_versions_match_requirements(skip=("psynet",))
            assert (
                f"✔ Dallinger: installed commit {installed[:12]} matches "
                f"constraints.txt (commit {installed[:12]})"
            ) in capsys.readouterr().out
        else:
            with pytest.raises(ValueError) as error:
                check_core_dependency_versions_match_requirements(skip=("psynet",))
            assert "specified in constraints.txt do not match" in str(error.value)
            assert f"editable Dallinger at commit {installed[:12]} ({source})" in str(
                error.value
            )
            assert "--use-local-dallinger" in str(error.value)


@patch("psynet.experiment_scaffold.get_editable_source", new=lambda name: None)
@patch("psynet.version._get_dallinger_version", new=lambda: "12.3.0")
def test_non_editable_mismatch_hint_names_the_pin_file(tmp_path):
    (tmp_path / "requirements.txt").write_text("dallinger\n")
    (tmp_path / "constraints.txt").write_text("dallinger==12.4.0\n")

    with working_directory(tmp_path), pytest.raises(ValueError) as error:
        check_core_dependency_versions_match_requirements(skip=("psynet",))
    assert (
        "Install the Dallinger version pinned in constraints.txt with `psynet setup`."
        in str(error.value)
    )


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
                    "psynet@git+https://gitlab.com/PsyNetDev/PsyNet@c0ffee0c0ffee0c0ffee#egg=psynet\n"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The PsyNet versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: INSTALLED_COMMIT_HASH[\\n\\r\\s]+"
                    "Version specified in requirements.txt: c0ffee0c0ffee0c0ffee",
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
def test_check_core_dependency_versions_commit_pin_skips_development_install(
    mock_installed, capsys
):
    mock_installed.return_value = "13.4.0a0"

    with tempfile.TemporaryDirectory() as dir:
        with working_directory(dir):
            with open("requirements.txt", "w") as file:
                file.write(
                    f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{'a' * 40}"
                )

            check_core_dependency_versions_match_requirements()

    assert "Skipped version check for PsyNet" in capsys.readouterr().out


def test_branch_pin_defers_to_constraints_commit():
    commit = "a" * 40
    versions = collect_core_dependency_version_info_from_requirements(
        "psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@master\n",
        skip=("dallinger",),
        constraints_content=f"psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@{commit}\n",
    )
    assert versions["PsyNet"]["source"] == "constraints.txt"
    assert versions["PsyNet"]["specified"] == commit


@pytest.mark.parametrize(
    "constraint",
    [
        "dallinger==12.4.0",
        "dallinger[docker]==12.4 \\",
        "dallinger==12.4.0    # via psynet",
    ],
)
@patch("psynet.version._get_dallinger_version", new=lambda: "12.4.0")
def test_constraints_version_pin_matching_installed_dallinger_passes(
    tmp_path, capsys, constraint
):
    (tmp_path / "requirements.txt").write_text("dallinger\n")
    (tmp_path / "constraints.txt").write_text(f"{constraint}\n    # via psynet\n")

    with working_directory(tmp_path):
        check_core_dependency_versions_match_requirements(skip=("psynet",))

    assert "✔ Dallinger: installed 12.4.0 matches constraints.txt" in (
        capsys.readouterr().out
    )


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
                    "dallinger@git+https://github.com/Dallinger/Dallinger@c0ffee0c0ffee0c0ffee#egg=dallinger"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The Dallinger versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: INSTALLED_COMMIT_HASH[\\n\\r\\s]+"
                    "Version specified in requirements.txt: c0ffee0c0ffee0c0ffee",
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
                    "dallinger@git+https://github.com/Dallinger/Dallinger@c0ffee0c0ffee0c0ffee"
                )
                file.flush()

                with pytest.raises(
                    ValueError,
                    match="The Dallinger versions installed on your local computer and specified in requirements.txt do not match.[\\n\\r\\s]+"
                    "Version installed locally: INSTALLED_COMMIT_HASH[\\n\\r\\s]+"
                    "Version specified in requirements.txt: c0ffee0c0ffee0c0ffee",
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

"""Tests for PsyNet requirement pinning helpers."""

import subprocess
from pathlib import Path

import pytest

from psynet.experiment_scaffold import (
    _default_psynet_requirement,
    _normalize_git_remote_to_pip_base,
    commit_psynet_requirement,
    editable_psynet_requirement,
    is_unambiguous_psynet_requirement,
)


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        (
            "https://gitlab.com/PsyNetDev/PsyNet.git",
            "git+https://gitlab.com/PsyNetDev/PsyNet",
        ),
        (
            "https://gitlab.com/PsyNetDev/PsyNet.git/",
            "git+https://gitlab.com/PsyNetDev/PsyNet",
        ),
        (
            "https://gitlab.com/alice/PsyNet.git",
            "git+https://gitlab.com/alice/PsyNet",
        ),
        (
            "git@gitlab.com:alice/PsyNet.git",
            "git+https://gitlab.com/alice/PsyNet",
        ),
        (
            "git@gitlab.com:alice/PsyNet.git/",
            "git+https://gitlab.com/alice/PsyNet",
        ),
        (
            "ssh://git@gitlab.com/alice/PsyNet.git",
            "git+https://gitlab.com/alice/PsyNet",
        ),
        (
            "ssh://git@gitlab.com/alice/PsyNet.git/",
            "git+https://gitlab.com/alice/PsyNet",
        ),
        (
            "git@github.com:alice/PsyNet.git",
            "git+https://github.com/alice/PsyNet",
        ),
        (
            "git@git.example.com:alice/PsyNet.git",
            "git+ssh://git@git.example.com/alice/PsyNet",
        ),
        (
            "ssh://git@git.example.com/alice/PsyNet.git",
            "git+ssh://git@git.example.com/alice/PsyNet",
        ),
        (
            "ssh://git@git.example.com/alice/PsyNet.git/",
            "git+ssh://git@git.example.com/alice/PsyNet",
        ),
    ],
)
def test_normalize_git_remote_to_pip_base(remote, expected):
    assert _normalize_git_remote_to_pip_base(remote) == expected


def test_normalize_git_remote_rejects_unknown_urls():
    with pytest.raises(ValueError, match="Unrecognized git remote URL"):
        _normalize_git_remote_to_pip_base("not-a-remote")


def test_commit_psynet_requirement_uses_origin_remote(tmp_path, monkeypatch):
    source = tmp_path / "psynet"
    source.mkdir()
    commit = "b" * 40
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._git_remote_url",
        lambda _source, remote="origin": "git@gitlab.com:alice/PsyNet.git",
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._remote_contains_commit",
        lambda _source, _commit, remote="origin": True,
    )

    assert commit_psynet_requirement(source) == (
        f"psynet[experiment]@git+https://gitlab.com/alice/PsyNet@{commit}#egg=psynet"
    )


def test_commit_psynet_requirement_strips_trailing_slash_from_origin(
    tmp_path, monkeypatch
):
    from psynet.experiment_scaffold import is_unambiguous_psynet_requirement

    source = tmp_path / "psynet"
    source.mkdir()
    commit = "b" * 40
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._git_remote_url",
        lambda _source, remote="origin": "ssh://git@gitlab.com/alice/PsyNet.git/",
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._remote_contains_commit",
        lambda _source, _commit, remote="origin": True,
    )

    requirement = commit_psynet_requirement(source)
    assert requirement == (
        f"psynet[experiment]@git+https://gitlab.com/alice/PsyNet@{commit}#egg=psynet"
    )
    assert is_unambiguous_psynet_requirement(requirement)


def test_commit_psynet_requirement_requires_pushed_commit(tmp_path, monkeypatch):
    source = tmp_path / "psynet"
    source.mkdir()
    commit = "c" * 40
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._git_remote_url",
        lambda _source, remote="origin": "https://gitlab.com/alice/PsyNet.git",
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._remote_contains_commit",
        lambda _source, _commit, remote="origin": False,
    )

    with pytest.raises(ValueError, match="not available on git remote 'origin'"):
        commit_psynet_requirement(source)


def test_remote_contains_commit_uses_remote_advertisement(tmp_path, monkeypatch):
    from psynet.experiment_scaffold import _remote_contains_commit

    source = tmp_path / "psynet"
    source.mkdir()
    commit = "a" * 40
    monkeypatch.setattr(
        "psynet.experiment_scaffold._remote_advertises_commit",
        lambda _source, _commit, remote="origin": True,
    )

    assert _remote_contains_commit(source, commit) is True


def _git_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote and a clone configured for empty commits."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.check_call(["git", "init", "--bare", str(remote)])
    subprocess.check_call(["git", "clone", str(remote), str(work)])
    subprocess.check_call(["git", "-C", str(work), "config", "user.email", "a@b.c"])
    subprocess.check_call(["git", "-C", str(work), "config", "user.name", "Test"])
    return remote, work


def _empty_commit(work: Path, message: str) -> str:
    subprocess.check_call(
        ["git", "-C", str(work), "commit", "--allow-empty", "-m", message]
    )
    return subprocess.check_output(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def test_remote_advertises_commit_rejects_unpushed_local_sha(tmp_path):
    """Local-only SHAs must not satisfy the remote availability check."""
    from psynet.experiment_scaffold import _remote_advertises_commit

    _remote, work = _git_repo_with_remote(tmp_path)
    pushed = _empty_commit(work, "pushed")
    subprocess.check_call(["git", "-C", str(work), "push", "origin", "HEAD:master"])
    unpushed = _empty_commit(work, "local only")

    # The old ``git fetch --dry-run origin <sha>`` check returned success here.
    dry_run = subprocess.run(
        ["git", "-C", str(work), "fetch", "--dry-run", "origin", unpushed],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dry_run.returncode == 0

    assert _remote_advertises_commit(work, unpushed) is False
    assert _remote_advertises_commit(work, pushed) is True


def test_remote_advertises_commit_without_remote_tracking_refs(tmp_path):
    """CI-style checkouts without origin/<branch> still detect pushed commits."""
    from psynet.experiment_scaffold import _remote_advertises_commit

    _remote, work = _git_repo_with_remote(tmp_path)
    older = _empty_commit(work, "older")
    subprocess.check_call(["git", "-C", str(work), "push", "origin", "HEAD:master"])
    tip = _empty_commit(work, "tip")
    subprocess.check_call(["git", "-C", str(work), "push", "origin", "HEAD:master"])
    subprocess.check_call(
        ["git", "-C", str(work), "update-ref", "-d", "refs/remotes/origin/master"]
    )

    assert _remote_advertises_commit(work, tip) is True
    assert _remote_advertises_commit(work, older) is True


def test_remote_contains_commit_rejects_stale_remote_tracking_ref(tmp_path):
    """A deleted remote branch must not remain deployable via a stale local ref."""
    from psynet.experiment_scaffold import _remote_contains_commit

    _remote, work = _git_repo_with_remote(tmp_path)
    commit = _empty_commit(work, "temporary remote branch")
    subprocess.check_call(["git", "-C", str(work), "push", "origin", "HEAD:stale"])
    subprocess.check_call(
        ["git", "-C", str(work), "push", "origin", "--delete", "stale"]
    )
    subprocess.check_call(
        [
            "git",
            "-C",
            str(work),
            "update-ref",
            "refs/remotes/origin/stale",
            commit,
        ]
    )

    containing_refs = subprocess.check_output(
        ["git", "-C", str(work), "branch", "-r", "--contains", commit],
        text=True,
    )
    assert "origin/stale" in containing_refs
    assert _remote_contains_commit(work, commit) is False


def test_commit_psynet_requirement_requires_origin_remote(tmp_path, monkeypatch):
    source = tmp_path / "psynet"
    source.mkdir()
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: "d" * 40,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._git_remote_url",
        lambda _source, remote="origin": None,
    )

    with pytest.raises(ValueError, match="Could not determine git remote 'origin'"):
        commit_psynet_requirement(source)


def test_default_psynet_requirement_degrades_when_commit_is_unservable(
    monkeypatch, capsys
):
    """Unservable commits degrade to an editable pin instead of failing setup.

    An alpha checkout whose HEAD cannot be served by ``origin`` (unpushed work,
    or a CI merged-result commit) must still scaffold, and must not invent a
    PsyNetDev URL.
    """
    commit = "e" * 40
    source = Path("/tmp/fake-psynet-editable")
    monkeypatch.setattr("psynet.experiment_scaffold.psynet_version", "13.4.0a0")
    monkeypatch.setattr(
        "psynet.experiment_scaffold.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )

    def _fail(_source: Path) -> str:
        raise ValueError(
            f"Commit {commit[:12]} is not available on git remote 'origin' "
            "(https://gitlab.com/alice/PsyNet.git). Push your PsyNet commits first "
            "(`git push origin HEAD`), then retry, or use "
            "--psynet-source editable."
        )

    monkeypatch.setattr(
        "psynet.experiment_scaffold.commit_psynet_requirement",
        _fail,
    )

    requirement = _default_psynet_requirement()

    assert requirement == editable_psynet_requirement(source)
    assert "PsyNetDev/PsyNet" not in requirement
    warning = capsys.readouterr().err
    assert "not available on git remote 'origin'" in warning
    assert "--psynet-source commit" in warning


def test_default_psynet_requirement_uses_origin_commit_pin(monkeypatch):
    commit = "f" * 40
    source = Path("/tmp/fake-psynet-editable")
    monkeypatch.setattr("psynet.experiment_scaffold.psynet_version", "13.4.0a0")
    monkeypatch.setattr(
        "psynet.experiment_scaffold.get_editable_psynet_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._current_source_commit",
        lambda _source=None: commit,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold.commit_psynet_requirement",
        lambda _source: (
            f"psynet[experiment]@git+https://gitlab.com/alice/PsyNet@{commit}#egg=psynet"
        ),
    )

    assert _default_psynet_requirement() == (
        f"psynet[experiment]@git+https://gitlab.com/alice/PsyNet@{commit}#egg=psynet"
    )


def test_default_psynet_requirement_falls_back_to_version_without_git(monkeypatch):
    monkeypatch.setattr("psynet.experiment_scaffold.psynet_version", "13.4.0a0")
    monkeypatch.setattr(
        "psynet.experiment_scaffold.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._installed_psynet_file_path",
        lambda: None,
    )

    assert _default_psynet_requirement() == "psynet[experiment]==13.4.0a0"


def test_default_psynet_requirement_uses_vcs_install_for_unpublished_alpha(
    monkeypatch,
):
    """Git installs must not become ``psynet[experiment]==<alpha>``.

    That pin is unsatisfiable on PyPI and is what ``psynet setup`` hit when
    PsyNet was installed from a GitLab branch.
    """
    commit = "a" * 40
    monkeypatch.setattr("psynet.experiment_scaffold.psynet_version", "13.4.0a0")
    monkeypatch.setattr(
        "psynet.experiment_scaffold.get_editable_psynet_source",
        lambda: None,
    )
    monkeypatch.setattr(
        "psynet.experiment_scaffold._psynet_direct_url_info",
        lambda: {
            "url": "https://gitlab.com/PsyNetDev/PsyNet.git",
            "vcs_info": {"vcs": "git", "commit_id": commit},
        },
    )

    requirement = _default_psynet_requirement()
    assert requirement == (
        f"psynet[experiment] @ git+https://gitlab.com/PsyNetDev/PsyNet.git@{commit}"
    )
    assert is_unambiguous_psynet_requirement(requirement)

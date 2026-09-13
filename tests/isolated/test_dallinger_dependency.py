"""Tests for Dallinger lower-bound resolution from pyproject / metadata."""

import re
import tomllib
from pathlib import Path

import pytest

from psynet.dallinger_dependency import (
    dallinger_constraints_github_ref,
    dallinger_lower_bound_from_pyproject,
)

ROOT = Path(__file__).resolve().parents[2]


def test_github_ref_tracks_declared_dallinger_dependency():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = next(
        dep
        for dep in pyproject["project"]["optional-dependencies"]["experiment"]
        if dep.startswith("dallinger[")
    )
    ref = dallinger_constraints_github_ref()
    sha = re.search(r"Dallinger\.git@([0-9a-f]{40})", declared)
    if sha:
        assert ref == sha.group(1)
        with pytest.raises(ValueError, match="lower-bound version"):
            dallinger_lower_bound_from_pyproject(ROOT / "pyproject.toml")
        return
    version = dallinger_lower_bound_from_pyproject(ROOT / "pyproject.toml")
    assert ref == f"v{version}"
    assert version in declared


def test_github_ref_uses_git_sha_pin(tmp_path, monkeypatch):
    from psynet import dallinger_dependency

    sha = "0123456789abcdef0123456789abcdef01234567"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f"""
[project]
dependencies = []
[project.optional-dependencies]
experiment = ["dallinger[docker] @ git+https://github.com/Dallinger/Dallinger.git@{sha}"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dallinger_dependency, "_default_pyproject_path", lambda: pyproject
    )
    assert dallinger_constraints_github_ref() == sha
    assert dallinger_constraints_github_ref(pyproject) == sha
    with pytest.raises(ValueError, match="lower-bound version"):
        dallinger_lower_bound_from_pyproject(pyproject)


def test_github_ref_uses_git_sha_from_installed_metadata(tmp_path, monkeypatch):
    """Wheels have no pyproject.toml; SHA pins must still come from Requires-Dist."""
    from psynet import dallinger_dependency

    sha = "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setattr(
        dallinger_dependency,
        "_default_pyproject_path",
        lambda: tmp_path / "missing.toml",
    )
    monkeypatch.setattr(
        dallinger_dependency,
        "requires",
        lambda name: [
            "click",
            (
                "dallinger[docker] @ "
                f"git+https://github.com/Dallinger/Dallinger.git@{sha} "
                "; extra == 'experiment'"
            ),
        ],
    )
    assert dallinger_constraints_github_ref() == sha


def test_github_ref_uses_version_bound_from_installed_metadata(tmp_path, monkeypatch):
    from psynet import dallinger_dependency

    monkeypatch.setattr(
        dallinger_dependency,
        "_default_pyproject_path",
        lambda: tmp_path / "missing.toml",
    )
    monkeypatch.setattr(
        dallinger_dependency,
        "requires",
        lambda name: [
            'dallinger[docker] (>=12.2.0,<13) ; extra == "experiment"',
        ],
    )
    assert dallinger_constraints_github_ref() == "v12.2.0"


def test_lower_bound_from_pyproject_rejects_git_url(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
dependencies = []
[project.optional-dependencies]
experiment = ["dallinger[docker] @ git+https://github.com/Dallinger/Dallinger.git@some-branch"]
""",
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError, match="Could not find a Dallinger lower-bound version"
    ):
        dallinger_lower_bound_from_pyproject(pyproject)


def test_lower_bound_from_pyproject_rejects_missing_dallinger(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
dependencies = ["click"]
[project.optional-dependencies]
experiment = ["pandas"]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Could not find a Dallinger dependency"):
        dallinger_lower_bound_from_pyproject(pyproject)


def test_lower_bound_parses_pep508_metadata_style(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
dependencies = []
[project.optional-dependencies]
experiment = ['dallinger[docker] (>=9.1.0,<10) ; python_version >= "3.10"']
""",
        encoding="utf-8",
    )
    assert dallinger_lower_bound_from_pyproject(pyproject) == "9.1.0"


def test_source_pyproject_takes_priority_over_installed_metadata(tmp_path, monkeypatch):
    """Editable source declarations must not be shadowed by stale dist-info."""
    from psynet import dallinger_dependency

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
dependencies = []
[project.optional-dependencies]
experiment = ["dallinger[docker]>=12.3.0,<13"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dallinger_dependency, "_default_pyproject_path", lambda: pyproject
    )
    monkeypatch.setattr(
        dallinger_dependency,
        "requires",
        lambda name: pytest.fail("source checkout should not consult stale metadata"),
    )
    assert dallinger_constraints_github_ref() == "v12.3.0"


def test_requirement_match_does_not_accept_similarly_named_distribution(tmp_path):
    """A dallinger-plugin dependency must not masquerade as Dallinger."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
dependencies = ["dallinger-plugin>=99.0.0"]
[project.optional-dependencies]
experiment = []
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Could not find a Dallinger dependency"):
        dallinger_lower_bound_from_pyproject(pyproject)

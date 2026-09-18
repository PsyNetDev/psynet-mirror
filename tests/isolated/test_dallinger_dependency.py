"""Tests for Dallinger lower-bound resolution from pyproject / metadata."""

import re
from pathlib import Path

import pytest
import tomllib

from psynet.dallinger_dependency import (
    dallinger_constraints_github_ref,
    dallinger_lower_bound_from_pyproject,
    supported_dallinger_lower_bound,
)

ROOT = Path(__file__).resolve().parents[2]


def test_lower_bound_from_pyproject_matches_experiment_extra():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = next(
        dep
        for dep in pyproject["project"]["optional-dependencies"]["experiment"]
        if dep.startswith("dallinger[")
    )
    expected = re.search(r">=(\d+\.\d+\.\d+)", declared).group(1)

    version = dallinger_lower_bound_from_pyproject(ROOT / "pyproject.toml")
    assert version == expected
    assert dallinger_constraints_github_ref() == f"v{expected}"
    assert supported_dallinger_lower_bound() == version


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
        "_lower_bound_from_installed_metadata",
        lambda: pytest.fail("source checkout should not consult stale metadata"),
    )
    assert supported_dallinger_lower_bound() == "12.3.0"


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

"""Resolve PsyNet's declared Dallinger dependency for bootstrap and CI.

Thin-bootstrap paths need a GitHub ref when Dallinger is not installed (for
example fetching ``dallinger.constraints``). That ref must track the same
declaration in ``pyproject.toml`` under ``psynet[experiment]``, not a
hand-maintained duplicate constant.

Version pins become ``v<lower-bound>``. Direct git pins to
``github.com/Dallinger/Dallinger`` use the declared commit SHA.

Resolution order:

1. The repository ``pyproject.toml`` next to the ``psynet`` package (editable /
   source checkouts and CI helpers).
2. Installed package metadata (``Requires-Dist`` for the ``experiment`` extra)
   for wheels, which do not contain the repository ``pyproject.toml``. Both
   version bounds and direct git SHA pins are read from that metadata.
"""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import PackageNotFoundError, requires
from pathlib import Path

_LOWER_BOUND_PATTERN = re.compile(r">=\s*(\d+\.\d+\.\d+)")
_GIT_SHA_PIN_PATTERN = re.compile(
    r"git\+https://github\.com/Dallinger/Dallinger\.git@([0-9a-f]{40})",
    re.IGNORECASE,
)
_DALLINGER_REQUIREMENT_PATTERN = re.compile(
    r"^\s*dallinger(?:\[[^\]]+\])?\s*(?:\(|[<>=!~;@\s]|$)", re.IGNORECASE
)


def dallinger_constraints_github_ref(pyproject_path: Path | None = None) -> str:
    """Return the GitHub ref for constraints-script and CI snapshot fetches.

    Version pins become ``v<lower-bound>``. Direct git pins use the SHA.
    """
    requirement, source = _dallinger_requirement(pyproject_path)
    sha = _git_sha_from_requirement(requirement)
    if sha is not None:
        return sha
    version = _lower_bound_from_requirement_strings([requirement], source=source)
    return f"v{version}"


def _dallinger_requirement(
    pyproject_path: Path | None,
) -> tuple[str, str]:
    """Return the Dallinger requirement string and a source label."""
    if pyproject_path is None:
        pyproject_path = _default_pyproject_path()
        if not pyproject_path.is_file():
            return (
                _dallinger_requirement_from_installed_metadata(),
                "psynet metadata",
            )
    return (
        _dallinger_requirement_from_pyproject(pyproject_path),
        str(pyproject_path),
    )


def _dallinger_requirement_from_installed_metadata() -> str:
    """Return the Dallinger requirement from installed ``psynet`` metadata."""
    try:
        reqs = requires("psynet")
    except PackageNotFoundError:
        reqs = None
    if not reqs:
        raise ValueError(
            "Could not determine PsyNet's Dallinger dependency from "
            "pyproject.toml or installed package metadata."
        )
    return _dallinger_requirement_from_strings(reqs, source="psynet metadata")


def dallinger_lower_bound_from_pyproject(pyproject_path: Path) -> str:
    """Return the Dallinger lower bound declared in ``pyproject_path``."""
    requirement = _dallinger_requirement_from_pyproject(pyproject_path)
    return _lower_bound_from_requirement_strings(
        [requirement], source=str(pyproject_path)
    )


def _dallinger_requirement_from_pyproject(pyproject_path: Path) -> str:
    """Return the Dallinger requirement string declared in ``pyproject_path``."""
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    candidates = list(
        pyproject.get("project", {})
        .get("optional-dependencies", {})
        .get("experiment", [])
    )
    candidates.extend(pyproject.get("project", {}).get("dependencies", []))
    return _dallinger_requirement_from_strings(candidates, source=str(pyproject_path))


def _dallinger_requirement_from_strings(requirements: list[str], *, source: str) -> str:
    """Return the first Dallinger requirement string from ``requirements``."""
    dependency = next(
        (
            requirement
            for requirement in requirements
            if _DALLINGER_REQUIREMENT_PATTERN.match(requirement)
        ),
        None,
    )
    if dependency is None:
        raise ValueError(f"Could not find a Dallinger dependency in {source}.")
    return dependency


def _git_sha_from_requirement(requirement: str) -> str | None:
    """Return a Dallinger git SHA pin, or ``None`` for version-style pins."""
    match = _GIT_SHA_PIN_PATTERN.search(requirement)
    return match.group(1) if match else None


def _lower_bound_from_requirement_strings(
    requirements: list[str], *, source: str
) -> str:
    """Extract ``>=X.Y.Z`` from a Dallinger requirement string."""
    dependency = _dallinger_requirement_from_strings(requirements, source=source)
    match = _LOWER_BOUND_PATTERN.search(dependency)
    if match is None:
        raise ValueError(
            f"Could not find a Dallinger lower-bound version in {source}: {dependency!r}."
        )
    return match.group(1)


def _default_pyproject_path() -> Path:
    """Return the repository ``pyproject.toml`` beside the ``psynet`` package."""
    return Path(__file__).resolve().parents[1] / "pyproject.toml"

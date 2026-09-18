"""Resolve PsyNet's declared Dallinger version lower bound.

Thin-bootstrap paths need a Dallinger release tag when the package is not
installed (for example fetching ``dallinger.constraints`` from GitHub). That
tag must track the same lower bound declared in ``pyproject.toml`` under
``psynet[experiment]``, not a hand-maintained duplicate constant.

Resolution order:

1. The repository ``pyproject.toml`` next to the ``psynet`` package (editable /
   source checkouts and CI helpers).
2. Installed package metadata (``Requires-Dist`` for the ``experiment`` extra)
   for wheels, which do not contain the repository ``pyproject.toml``.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, requires
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

_LOWER_BOUND_PATTERN = re.compile(r">=\s*(\d+\.\d+\.\d+)")
_DALLINGER_REQUIREMENT_PATTERN = re.compile(
    r"^\s*dallinger(?:\[[^\]]+\])?\s*(?:\(|[<>=!~;@\s]|$)", re.IGNORECASE
)


def supported_dallinger_lower_bound() -> str:
    """Return PsyNet's supported Dallinger lower-bound version (e.g. ``12.2.0``)."""
    pyproject_path = _default_pyproject_path()
    if pyproject_path.is_file():
        return dallinger_lower_bound_from_pyproject(pyproject_path)
    from_metadata = _lower_bound_from_installed_metadata()
    if from_metadata is not None:
        return from_metadata
    raise ValueError(
        "Could not determine PsyNet's supported Dallinger version from "
        "pyproject.toml or installed package metadata."
    )


def dallinger_constraints_github_ref() -> str:
    """Return the GitHub ref for the constraints-script fallback (e.g. ``v12.2.0``)."""
    return f"v{supported_dallinger_lower_bound()}"


def dallinger_lower_bound_from_pyproject(pyproject_path: Path) -> str:
    """Return the Dallinger lower bound declared in ``pyproject_path``."""
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    candidates = list(
        pyproject.get("project", {})
        .get("optional-dependencies", {})
        .get("experiment", [])
    )
    candidates.extend(pyproject.get("project", {}).get("dependencies", []))
    return _lower_bound_from_requirement_strings(candidates, source=str(pyproject_path))


def _lower_bound_from_installed_metadata() -> str | None:
    """Return the Dallinger lower bound from installed ``psynet`` metadata."""
    try:
        reqs = requires("psynet")
    except PackageNotFoundError:
        return None
    if not reqs:
        return None
    try:
        return _lower_bound_from_requirement_strings(reqs, source="psynet metadata")
    except ValueError:
        return None


def _lower_bound_from_requirement_strings(
    requirements: list[str], *, source: str
) -> str:
    """Extract ``>=X.Y.Z`` from a Dallinger requirement string."""
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
    match = _LOWER_BOUND_PATTERN.search(dependency)
    if match is None:
        raise ValueError(
            f"Could not find a Dallinger lower-bound version in {source}: {dependency!r}."
        )
    return match.group(1)


def _default_pyproject_path() -> Path:
    """Return the repository ``pyproject.toml`` beside the ``psynet`` package."""
    return Path(__file__).resolve().parents[1] / "pyproject.toml"

"""Bootstrap-safe utility helpers for PsyNet.

This module provides a small set of utilities that can be imported without
triggering the heavy dependency chain (dallinger, flask, sqlalchemy, etc.)
that ``psynet.utils`` pulls in. It is used by ``psynet.bootstrap_cli``,
``psynet.experiment_setup``, and ``psynet.experiment_scaffold`` so those
modules remain importable when only the minimal ``psynet`` package (without
the ``[experiment]`` extra) is installed.

All symbols exposed here are also re-exported from ``psynet.utils`` for
backwards compatibility. Code that already imports from ``psynet.utils``
continues to work unchanged.

Design constraints
------------------
- **Stdlib only** (plus ``click`` for the error class and ``pathlib``).
  Never import dallinger, flask, sqlalchemy, or other heavy deps here.
- Keep the module small; only add helpers that are genuinely needed in
  bootstrap paths.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
from typing import Union


class ExperimentDirectoryNameError(ValueError):
    """Raised when an experiment directory name collides with a non-package module."""


# ---------------------------------------------------------------------------
# MD5 directory hashing
# (copied from psynet.utils to avoid importing that module in bootstrap paths)
# ---------------------------------------------------------------------------


def _md5_update_from_file(filename: Union[str, Path], hash_obj) -> None:
    """Update *hash_obj* with the contents of *filename*."""
    if not Path(filename).is_file():
        raise FileNotFoundError(f"File not found: {filename}")
    with open(str(filename), "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_obj.update(chunk)


def _md5_update_from_dir(directory: Union[str, Path], hash_obj) -> None:
    """Recursively update *hash_obj* with all files under *directory*."""
    assert Path(directory).is_dir()
    for path in sorted(Path(directory).iterdir(), key=lambda p: str(p).lower()):
        if path.name.startswith("."):
            continue
        hash_obj.update(path.name.encode())
        if path.is_file():
            _md5_update_from_file(path, hash_obj)
        elif path.is_dir():
            _md5_update_from_dir(path, hash_obj)


def md5_directory(directory: Union[str, Path]) -> str:
    """Return the MD5 hex digest of all non-hidden files under *directory*."""
    h = hashlib.md5()
    _md5_update_from_dir(directory, h)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Git repository detection
# ---------------------------------------------------------------------------


def git_command_available() -> bool:
    """Return whether the ``git`` executable is on ``PATH``."""
    return shutil.which("git") is not None


def git_repository_available() -> bool:
    """Return whether the current directory is inside a git work tree.

    Requires ``git`` to be installed and on ``PATH``. Used by bootstrap
    commands (``psynet setup``) and by local launch checks.
    """
    if not git_command_available():
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# PsyNet root and in-repo experiment detection
# ---------------------------------------------------------------------------


def get_psynet_root() -> Path:
    """Return the root directory of the PsyNet checkout or installed package."""
    import psynet

    return Path(psynet.__file__).parent.parent


def _find_psynet_checkout_root(start: Path) -> Path | None:
    """Walk parents of *start* for a PsyNet ``pyproject.toml`` checkout."""
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if re.search(r'(?m)^name\s*=\s*["\']psynet["\']', text):
            return candidate
    return None


_IN_REPO_EXPERIMENT_ROOTS = (
    "demos",
    "tests/experiments",
    "tests/playwright/experiments",
    "tests/deployment",
)


def is_in_repo_experiment(path=".", *, roots=None) -> bool:
    """Return whether *path* is a PsyNet in-repo experiment (demo or test).

    In-repo experiments use the shared development environment and omit
    checked-in scaffold/constraints files; local/CI flows auto-prepare
    ignored boilerplate.

    Detection prefers a PsyNet checkout containing *path* (so wheel/ASV
    installs still recognize demos under a source tree). Falls back to the
    installed package location for editable checkouts.

    Parameters
    ----------
    path :
        Experiment directory to check.
    roots :
        Optional iterable of in-repo roots relative to the PsyNet checkout.
        Defaults to :data:`_IN_REPO_EXPERIMENT_ROOTS`. Pass ``("demos",)``
        to restrict to bundled demos only.
    """
    path = Path(path).resolve()
    if not (path / "experiment.py").is_file():
        return False
    root = _find_psynet_checkout_root(path)
    if root is None:
        root = get_psynet_root().resolve()
    else:
        root = root.resolve()
    relative_roots = _IN_REPO_EXPERIMENT_ROOTS if roots is None else roots
    return any(
        path.is_relative_to((root / relative).resolve()) for relative in relative_roots
    )


# ---------------------------------------------------------------------------
# Experiment directory name conflict detection
# ---------------------------------------------------------------------------


def ensure_experiment_directory_name_does_not_conflict(path=".") -> None:
    """Check that the experiment directory basename is safe for Dallinger imports.

    Dallinger imports a local experiment as ``<directory_name>.experiment``.
    A directory named like an existing non-package module, for example
    ``code``, can resolve to the standard library module instead of the
    local experiment directory.

    Parameters
    ----------
    path : str or Path, optional
        Path to the experiment directory.

    Raises
    ------
    ExperimentDirectoryNameError
        If Python resolves the directory name to an unrelated non-package module.
    """
    path = Path(path).resolve()
    module_name = path.name
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError) as exc:
        raise ExperimentDirectoryNameError(
            f"The current experiment directory is named '{module_name}', which "
            "Python cannot import as a top-level package. Dallinger imports "
            "experiments by directory name, so it cannot import this experiment "
            "reliably. Rename the directory to a valid top-level package name."
        ) from exc
    if spec is None:
        return
    # A package resolution can still support ``<name>.experiment``. The
    # problematic case is a plain module such as the standard-library
    # ``code.py``, which has no submodule search path and cannot contain
    # ``code.experiment``.
    if spec.submodule_search_locations is not None:
        return

    candidate_paths = []
    if spec.origin not in (None, "built-in"):
        candidate_paths.append(Path(spec.origin))

    # If Python resolves the name back into the experiment directory, the
    # import machinery will see the local experiment rather than an unrelated
    # module.
    if any(
        candidate_path.resolve().is_relative_to(path)
        for candidate_path in candidate_paths
    ):
        return

    module_path = spec.origin if spec.origin is not None else module_name
    raise ExperimentDirectoryNameError(
        f"The current experiment directory is named '{module_name}', but Python's "
        f"module '{module_name}' resolves to '{module_path}' instead of "
        "this directory. Dallinger imports experiments by directory name, so it "
        "cannot import this experiment reliably. Rename the directory or move the "
        "runnable experiment into a nested non-conflicting directory, for example "
        f"'{module_name}/<experiment_slug>/'."
    )

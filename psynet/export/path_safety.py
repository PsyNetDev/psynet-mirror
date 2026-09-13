"""Strict relative-path and archive-layout checks for PsyNet exports.

Export archives, asset trees, and audit artifact copies all need the same
guarantees: a caller-supplied path must stay inside a known root, and a zip
member that looks like a table CSV must actually be one. Divergent ad-hoc
checks previously accepted nested lookalikes such as ``assets/database/`` and
``ZipFile.extractall`` paths that escape the destination.

This module is the single policy. Callers should not reimplement containment
or archive-layout classification.
"""

from __future__ import annotations

import posixpath
import shutil
import zipfile
from pathlib import Path
from typing import Optional

DATABASE_LAYOUT = "database"
LEGACY_DATA_LAYOUT = "data"
_TABLE_LAYOUTS = (DATABASE_LAYOUT, LEGACY_DATA_LAYOUT)


class UnsafePathError(ValueError):
    """Raised when a path is absolute, empty, or escapes its intended root."""


class AmbiguousArchiveLayoutError(ValueError):
    """Raised when an archive mixes or duplicates table-CSV layouts."""


def normalize_relative_path(path: str, *, strip_leading_slash: bool = False) -> str:
    """Return a POSIX relative path, or raise :class:`UnsafePathError`.

    Parameters
    ----------
    path :
        Candidate relative path. Backslashes, NUL bytes, and ``..`` segments
        are rejected rather than rewritten.
    strip_leading_slash :
        When true, a single leading ``/`` is removed before validation. Asset
        HTTP subpaths historically arrive this way; export semantic paths
        must leave this false so absolute paths stay rejected.
    """
    if path is None:
        raise UnsafePathError("Path is missing.")
    if not isinstance(path, str):
        raise UnsafePathError(f"Path must be a string, not {type(path).__name__}.")
    if "\x00" in path:
        raise UnsafePathError(f"Path contains a NUL byte: {path!r}.")
    candidate = path.replace("\\", "/")
    if strip_leading_slash:
        candidate = candidate.lstrip("/")
    if not candidate or candidate in (".",):
        raise UnsafePathError(f"Path is empty: {path!r}.")
    if candidate.startswith("/") or (len(candidate) >= 2 and candidate[1] == ":"):
        raise UnsafePathError(f"Path must be relative: {path!r}.")
    parts = [part for part in candidate.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise UnsafePathError(f"Path escapes its root: {path!r}.")
    normalized = posixpath.normpath("/".join(parts))
    if (
        normalized in (".", "..")
        or normalized.startswith("../")
        or normalized.startswith("/")
    ):
        raise UnsafePathError(f"Path escapes its root: {path!r}.")
    return normalized


def contained_path(root: Path, relative: str) -> Optional[Path]:
    """Resolve ``relative`` under ``root``, or return None if it is unsafe."""
    try:
        return contained_destination(root, relative)
    except UnsafePathError:
        return None


def contained_destination(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``, raising if it would escape."""
    normalized = normalize_relative_path(relative)
    root = Path(root).resolve()
    candidate = (root / Path(*normalized.split("/"))).resolve()
    if not candidate.is_relative_to(root):
        raise UnsafePathError(f"Path {relative!r} is not contained in {root}.")
    return candidate


def zip_member_path(name: str) -> str:
    """Return a normalized zip member path, rejecting traversal."""
    if name.endswith("/"):
        body = name.rstrip("/")
        if not body:
            return ""
        return normalize_relative_path(body) + "/"
    return normalize_relative_path(name)


def classify_table_csv_member(name: str) -> Optional[tuple[str, str]]:
    """Return ``(layout, table)`` for an exact root table CSV, else None.

    Only ``database/<table>.csv`` and legacy ``data/<table>.csv`` count.
    Nested lookalikes such as ``assets/database/private.csv`` are ignored.
    Traversal in the member name is an error, not a miss.
    """
    relative = zip_member_path(name)
    if relative.endswith("/"):
        return None
    parts = relative.split("/")
    if len(parts) != 2:
        return None
    layout, filename = parts
    if layout not in _TABLE_LAYOUTS:
        return None
    if not filename.endswith(".csv") or filename == ".csv":
        return None
    table = filename[:-4]
    if table in (".", "..") or "/" in table:
        return None
    return layout, table


def table_csv_members(archive: zipfile.ZipFile) -> list[str]:
    """Return exact table-CSV members, preferring the canonical layout.

    Raises
    ------
    AmbiguousArchiveLayoutError
        If both ``database/`` and ``data/`` table CSVs are present, a table
        appears twice, or a member name is duplicated.
    UnsafePathError
        If any member path traverses out of the archive root.
    """
    classified = _classified_table_members(archive)
    return [member for _layout, _table, member in classified]


def table_csv_member_map(archive: zipfile.ZipFile) -> dict[str, str]:
    """Return ``table -> member`` after validating the archive layout once."""
    return {
        table: member for _layout, table, member in _classified_table_members(archive)
    }


def find_table_member(archive: zipfile.ZipFile, table: str) -> Optional[str]:
    """Return the exact zip member for ``table``, preferring ``database/``."""
    return table_csv_member_map(archive).get(table)


def _classified_table_members(
    archive: zipfile.ZipFile,
) -> list[tuple[str, str, str]]:
    names = list(archive.namelist())
    if len(names) != len(set(names)):
        raise AmbiguousArchiveLayoutError(
            "The archive lists the same member more than once, so its table "
            "CSVs cannot be chosen safely."
        )

    found: list[tuple[str, str, str]] = []
    tables_by_layout: dict[str, set[str]] = {
        DATABASE_LAYOUT: set(),
        LEGACY_DATA_LAYOUT: set(),
    }
    for name in names:
        classified = classify_table_csv_member(name)
        if classified is None:
            continue
        layout, table = classified
        if table in tables_by_layout[layout]:
            raise AmbiguousArchiveLayoutError(
                f"The archive contains more than one {layout}/{table}.csv."
            )
        tables_by_layout[layout].add(table)
        found.append((layout, table, name))

    has_canonical = bool(tables_by_layout[DATABASE_LAYOUT])
    has_legacy = bool(tables_by_layout[LEGACY_DATA_LAYOUT])
    if has_canonical and has_legacy:
        raise AmbiguousArchiveLayoutError(
            "The archive mixes database/ and data/ table CSVs. Use one layout."
        )
    preferred = DATABASE_LAYOUT if has_canonical else LEGACY_DATA_LAYOUT
    return sorted(
        [item for item in found if item[0] == preferred],
        key=lambda item: item[2],
    )


def extract_zip_contained(archive: zipfile.ZipFile, destination: str) -> None:
    """Extract ``archive`` into ``destination`` without leaving that directory."""
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    members = []
    seen = {}
    for info in archive.infolist():
        name = info.filename
        if not name or name.endswith("/"):
            continue
        relative = zip_member_path(name)
        if relative.endswith("/"):
            continue
        key = relative.casefold()
        if key in seen:
            raise AmbiguousArchiveLayoutError(
                f"Archive members {seen[key]!r} and {name!r} resolve to the "
                f"same path ({relative!r})."
            )
        seen[key] = name
        members.append((info, relative))

    for info, relative in members:
        target = contained_destination(dest, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, open(target, "wb") as handle:
            shutil.copyfileobj(source, handle)


def assert_semantic_asset_path(path: str) -> str:
    """Validate a semantic asset path used in manifests and export trees."""
    return normalize_relative_path(path)

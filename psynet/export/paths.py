"""Export archive path resolution.

Export packaging uses a single product (``export.zip`` / extracted export
directory) with table CSVs under ``database/``. Archive ingestion and analysis
helpers accept three equivalent inputs:

* an ``export.zip`` file;
* a ``database/`` directory of table CSVs;
* an extracted export directory that contains ``database/``.

Legacy zips that store members as ``data/<table>.csv`` (old ``database.zip``)
are still accepted for ``--archive`` and analysis.
"""

from __future__ import annotations

import os

from .path_safety import find_table_member as find_table_member_in_zip
from .path_safety import table_csv_member_map as table_csv_members_by_table
from .path_safety import table_csv_members

__all__ = [
    "DATABASE_DIRNAME",
    "EXPORT_FORMAT_VERSION",
    "EXPORT_ZIP_NAME",
    "dashboard_export_zip_path",
    "find_table_member_in_zip",
    "is_zip_path",
    "resolve_database_dir",
    "table_csv_members",
    "table_csv_members_by_table",
    "table_csv_path",
]

DATABASE_DIRNAME = "database"
EXPORT_ZIP_NAME = "export.zip"

#: Version of the canonical export product, and the contract between the
#: server that builds an export and the client that reads it. Bump it only for
#: changes an older client cannot read. It is recorded in ``manifest.json`` so
#: a client can refuse an archive it does not understand. This lives here,
#: rather than in :mod:`psynet.export.service`, because both sides of the wire
#: need it and the client must not import server-side code.
EXPORT_FORMAT_VERSION = 1


def dashboard_export_zip_path(export_dir: str) -> str:
    """Return the ``export.zip`` path beside a dashboard/backup export tree.

    The zip is written in the parent of ``export_dir`` so it is not included
    in the archive and is not left in the process working directory. Callers
    must nest ``export_dir`` under a disposable parent (for example
    ``<tempdir>/export``).
    """
    zip_path = os.path.join(
        os.path.dirname(os.path.abspath(export_dir)), EXPORT_ZIP_NAME
    )
    if zip_path == os.path.abspath(EXPORT_ZIP_NAME):
        raise ValueError(
            "Dashboard export.zip must be written under a temporary directory, "
            "not the process working directory."
        )
    return zip_path


def is_zip_path(path: str) -> bool:
    """Return whether ``path`` looks like a zip archive."""
    return os.path.isfile(path) and path.lower().endswith(".zip")


def resolve_database_dir(path: str) -> str:
    """Resolve ``path`` to a directory containing ``<table>.csv`` files.

    Parameters
    ----------
    path :
        An ``export.zip``, a ``database/`` directory, or an extracted export
        directory that contains ``database/``.

    Returns
    -------
    str
        Absolute path to the directory of table CSVs.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If ``path`` is an ``export.zip`` (use :func:`table_csv_members`
        / zip-aware loaders) or the layout cannot be resolved on disk.
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    if is_zip_path(path):
        raise ValueError(
            f"{path} is a zip archive; use zip-aware loaders rather than "
            "resolve_database_dir."
        )

    if os.path.isdir(path):
        nested = os.path.join(path, DATABASE_DIRNAME)
        legacy = os.path.join(path, "data")
        if (
            os.path.isdir(nested)
            and _dir_has_csv(nested)
            and os.path.isdir(legacy)
            and _dir_has_csv(legacy)
        ):
            raise ValueError(
                f"{path} mixes database/ and data/ table CSVs. Use one layout."
            )
        if os.path.isdir(nested) and _dir_has_csv(nested):
            return nested
        if _dir_has_csv(path):
            return path
        raise ValueError(
            f"Could not find table CSVs at {path} or {nested}. "
            "Pass export.zip, a database/ directory, or an extracted export "
            "directory containing database/."
        )

    raise ValueError(f"Unsupported archive path: {path}")


def _dir_has_csv(directory: str) -> bool:
    try:
        return any(name.endswith(".csv") for name in os.listdir(directory))
    except OSError:
        return False


def table_csv_path(database_dir: str, table: str) -> str:
    """Return ``database_dir/<table>.csv``."""
    return os.path.join(database_dir, f"{table}.csv")

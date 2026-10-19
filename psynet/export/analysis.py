"""Helpers for analysing canonical PsyNet export archives."""

from __future__ import annotations

import json
import os
import zipfile
from typing import Optional, Union

import pandas as pd

from .paths import (
    find_table_member_in_zip,
    is_zip_path,
    resolve_database_dir,
    table_csv_path,
)

# Current exports spell booleans True/False inside COPY. Older archives still
# use PostgreSQL's t/f, so loaders accept both.
_CSV_TRUE_VALUES = ["True", "true", "TRUE", "t", "T"]
_CSV_FALSE_VALUES = ["False", "false", "FALSE", "f", "F"]


def _read_table_csv(handle) -> pd.DataFrame:
    """Read a table CSV, treating COPY and Python boolean spellings as bool."""
    return pd.read_csv(
        handle,
        true_values=_CSV_TRUE_VALUES,
        false_values=_CSV_FALSE_VALUES,
    )


def load_export_table(
    archive: str,
    table: str,
) -> pd.DataFrame:
    """Load a physical table CSV from an export archive.

    Parameters
    ----------
    archive :
        Path to ``export.zip``, a ``database/`` directory, or an extracted
        export directory containing ``database/``. Legacy zips that store
        members as ``data/<table>.csv`` are also accepted.
    table :
        Physical table name (for example ``trial`` or ``participant``).

    Notes
    -----
    Boolean cells are parsed as bool, whether the CSV uses ``True`` / ``False``
    (current exports) or PostgreSQL COPY's ``t`` / ``f`` (archives from PsyNet
    14 and earlier). Accepting the short spellings means a *text* column whose
    every value happens to be ``t`` or ``f`` is also read as boolean; pass such
    a column through :func:`pandas.read_csv` yourself if that matters.
    """
    archive = os.path.expanduser(archive)
    if is_zip_path(archive):
        with zipfile.ZipFile(archive, "r") as zip_file:
            member = find_table_member_in_zip(zip_file, table)
            if member is None:
                raise KeyError(f"Table CSV for {table!r} not found in {archive}")
            with zip_file.open(member) as handle:
                return _read_table_csv(handle)

    database_dir = resolve_database_dir(archive)
    path = table_csv_path(database_dir, table)
    if not os.path.exists(path):
        raise KeyError(f"Table CSV for {table!r} not found in {database_dir}")
    return _read_table_csv(path)


def unpack_json_column(
    data_frame: pd.DataFrame,
    column: str,
    *,
    prefix: Optional[str] = None,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Unpack a JSON text column into ordinary columns.

    Nested objects are left as Python objects after ``json.loads``. Existing
    columns are never overwritten unless ``overwrite`` is true.
    """
    if column not in data_frame.columns:
        raise KeyError(column)

    parsed = []
    for value in data_frame[column]:
        if isinstance(value, (dict, list)):
            parsed.append(value if isinstance(value, dict) else {"value": value})
            continue
        if pd.isna(value) or value == "":
            parsed.append({})
            continue
        try:
            loaded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed.append({})
            continue
        if isinstance(loaded, dict):
            parsed.append(loaded)
        else:
            parsed.append({"value": loaded})

    unpacked = pd.json_normalize(parsed)
    if prefix:
        unpacked = unpacked.add_prefix(prefix)

    result = data_frame.copy()
    for col in unpacked.columns:
        if col in result.columns and not overwrite:
            continue
        result[col] = unpacked[col].values
    return result


def merge_participant_identifiers(
    data_frame: pd.DataFrame,
    identifiers: Union[str, os.PathLike, pd.DataFrame],
    *,
    on: str = "participant_id",
    suffixes: tuple[str, str] = ("", "_identifier"),
) -> pd.DataFrame:
    """Merge original participant identifiers onto an analysis frame.

    Parameters
    ----------
    data_frame :
        Table that contains ``participant_id`` (or another join key).
    identifiers :
        Path to ``participant_identifiers.csv`` (``str`` or :class:`pathlib.Path`)
        or an already-loaded frame.
    on :
        Join column name.
    """
    if not isinstance(identifiers, pd.DataFrame):
        identifiers = pd.read_csv(
            os.path.expanduser(os.fspath(identifiers)),
            dtype=str,
        )
        if on in identifiers and on in data_frame:
            identifiers[on] = identifiers[on].astype(data_frame[on].dtype)
    return data_frame.merge(identifiers, on=on, how="left", suffixes=suffixes)

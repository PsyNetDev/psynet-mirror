"""COPY-based database table export into a flat ``database/`` directory.

Every table is written by a single ``COPY (SELECT …) TO STDOUT WITH CSV HEADER``
that already applies both value transformations the export needs: boolean
columns are spelled ``True``/``False``, and recruiter identifiers are replaced
with pseudonyms by :mod:`psynet.export.identifiers`. Doing this in the query
rather than by rewriting the CSVs afterwards is deliberate — see that module for
why re-serializing a ``COPY`` CSV in Python silently corrupts empty strings.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Iterable, Optional

import psycopg2
from dallinger import db
from psycopg2 import sql
from sqlalchemy import Boolean
from sqlalchemy import inspect as sa_inspect

from psynet.utils import get_logger, make_parents, sha256_file

from .identifier_schema import validate_identifier_schema
from .identifiers import identifier_override, sidecar_specs
from .paths import DATABASE_DIRNAME, EXPORT_FORMAT_VERSION

logger = get_logger()


def _export_table_order(inspector=None) -> list[str]:
    """Return physical table names in a stable export order."""
    inspector = inspector if inspector is not None else sa_inspect(db.engine)
    names = sorted(inspector.get_table_names())
    preferred = [
        "network",
        "participant",
        "response",
        "node",
        "info",
        "trial",
        "notification",
        "question",
        "transformation",
        "vector",
        "transmission",
        "asset",
        "lucid_rid",
        "lucid_status",
        "request",
        "error",
        "process",
    ]
    ordered = [name for name in preferred if name in names]
    ordered.extend(name for name in names if name not in ordered)
    return ordered


def _db_dsn() -> str:
    return db.db_url


def _boolean_expression(name: str) -> sql.Composable:
    """Spell a boolean as ``True`` / ``False`` rather than PostgreSQL's ``t`` / ``f``.

    Analysis tools read the long form as a logical value, and ``COPY FROM``
    still accepts it on reload. The explicit NULL branch matters because
    ``CASE WHEN col THEN … ELSE …`` would otherwise fold NULL into the false
    branch.
    """
    return sql.SQL(
        "CASE WHEN {col} IS NULL THEN NULL WHEN {col} THEN 'True' ELSE 'False' END"
    ).format(col=sql.Identifier(name))


def _select_column(
    table: str,
    column: dict,
    *,
    not_null: set,
    has_id: bool,
    kind: str,
    pseudonymize: bool,
) -> sql.Composable:
    """Return the SELECT expression used to export one column."""
    name = column["name"]
    expression = None
    if pseudonymize:
        expression = identifier_override(
            table, name, not_null=not_null, has_id=has_id, kind=kind
        )
    if expression is None:
        if not isinstance(column["type"], Boolean):
            return sql.Identifier(name)
        expression = _boolean_expression(name)
    return sql.SQL("{expression} AS {alias}").format(
        expression=expression, alias=sql.Identifier(name)
    )


def copy_database_to_csv_dir(
    csv_dir: str,
    table_names: Optional[Iterable[str]] = None,
    *,
    pseudonymize: bool = False,
    _connection=None,
) -> list[str]:
    """Copy each physical table to ``csv_dir/<table>.csv`` via PostgreSQL COPY.

    Parameters
    ----------
    pseudonymize :
        Replace recruiter identifiers with participant-id pseudonyms, as
        :mod:`psynet.export.identifiers` defines. Exports always do this; it is
        optional so that a caller can obtain the unmodified tables.

    Returns
    -------
    list[str]
        Table names that were copied from the database, including empty tables.
    """
    os.makedirs(csv_dir, exist_ok=True)
    inspector = sa_inspect(db.engine)
    tables = (
        list(table_names) if table_names is not None else _export_table_order(inspector)
    )
    schema = validate_identifier_schema(inspector, tables) if pseudonymize else None
    conn = _connection or psycopg2.connect(dsn=_db_dsn())
    try:
        cur = conn.cursor()
        for table in tables:
            columns = inspector.get_columns(table)
            not_null = {col["name"] for col in columns if not col["nullable"]}
            has_id = any(col["name"] == "id" for col in columns)
            fields = sql.SQL(", ").join(
                _select_column(
                    table,
                    column,
                    not_null=not_null,
                    has_id=has_id,
                    kind=(
                        schema.get(table, column["name"]).kind
                        if schema is not None and schema.get(table, column["name"])
                        else "text"
                    ),
                    pseudonymize=pseudonymize,
                )
                for column in columns
            )
            query = sql.SQL(
                "COPY (SELECT {fields} FROM {table}) TO STDOUT WITH CSV HEADER"
            ).format(fields=fields, table=sql.Identifier(table))
            path = os.path.join(csv_dir, f"{table}.csv")
            with open(path, "w", newline="") as handle:
                cur.copy_expert(query, handle)
    finally:
        if _connection is None:
            conn.close()
    return tables


def write_identifier_sidecars(
    export_path: str,
    table_names: Iterable[str],
    *,
    _connection=None,
) -> dict:
    """Write the recruiter-identifier sidecar CSVs beside ``database/``.

    Returns ``key -> path`` for the sidecars that were written. An empty Lucid
    sidecar is dropped, since it only applies to Lucid deployments.
    """
    os.makedirs(export_path, exist_ok=True)
    specs = sidecar_specs(set(table_names))
    paths = {}
    conn = _connection or psycopg2.connect(dsn=_db_dsn())
    try:
        cur = conn.cursor()
        for key, (filename, query) in specs.items():
            path = os.path.join(export_path, filename)
            with open(path, "w", newline="") as handle:
                cur.copy_expert(query, handle)
            if key == "lucid_entrant_identifiers" and _count_csv_rows(path) == 0:
                os.remove(path)
                continue
            paths[key] = path
    finally:
        if _connection is None:
            conn.close()
    return paths


def _count_csv_rows(path: str) -> int:
    with open(path, newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def omit_empty_table_csvs(csv_dir: str, table_names: Iterable[str]) -> dict[str, int]:
    """Remove header-only table CSVs so unused tables do not appear in the export.

    Parameters
    ----------
    csv_dir :
        Directory of ``<table>.csv`` files.
    table_names :
        Physical tables that were exported.

    Returns
    -------
    dict
        Row count per table, including the removed (zero-row) ones. Returning
        the counts here saves re-reading every CSV to build ``manifest.json``.
    """
    row_counts = {}
    for table in table_names:
        path = os.path.join(csv_dir, f"{table}.csv")
        if not os.path.exists(path):
            row_counts[table] = 0
            continue
        row_counts[table] = _count_csv_rows(path)
        if row_counts[table] == 0:
            os.remove(path)
    return row_counts


def _file_entry(path: str) -> dict:
    return {"sha256": sha256_file(path), "bytes": os.path.getsize(path)}


def _provenance_for_manifest() -> dict:
    """Return deployment, experiment label, and git provenance for ``manifest.json``.

    ``experiment_label`` lets a client verify after the fact that an export came
    from the experiment it thinks it did, without querying the experiment
    database separately.
    """
    provenance = {
        "deployment_id": None,
        "experiment_label": None,
        "git_commit_sha": None,
        "git_dirty": None,
    }
    try:
        from psynet.experiment import get_experiment

        experiment = get_experiment()
        provenance["deployment_id"] = experiment.deployment_id
        provenance["experiment_label"] = experiment.label
        provenance["git_commit_sha"] = experiment.var.get("git_commit_sha", None)
        provenance["git_dirty"] = experiment.var.get("git_dirty", None)
        return provenance
    except Exception:
        logger.warning(
            "Could not resolve experiment git provenance for export manifest.",
            exc_info=True,
        )
    try:
        from psynet import deployment_info

        if deployment_info.is_available():
            provenance["git_commit_sha"] = deployment_info.read("git_commit_sha")
            provenance["git_dirty"] = deployment_info.read("git_dirty")
    except Exception:
        logger.warning(
            "Could not read deployment_info git provenance for export manifest.",
            exc_info=True,
        )
    return provenance


def write_export_manifest(
    export_path: str,
    *,
    table_names: list[str],
    csv_dir: str,
    extra_files: Optional[dict[str, str]] = None,
    row_counts: Optional[dict[str, int]] = None,
) -> str:
    """Write ``manifest.json`` describing the export.

    The manifest records ``git_commit_sha`` and ``git_dirty`` from launch
    provenance. Exports do not bundle experiment source code. Empty table CSVs
    are omitted from ``database/``; ``table_row_counts`` still includes those
    tables with a count of ``0``.

    Parameters
    ----------
    row_counts :
        Row counts already computed by :func:`omit_empty_table_csvs`. When
        omitted, counts are read from the CSVs that are still present.
    """
    from psynet import __version__ as psynet_version

    try:
        from dallinger.version import __version__ as dallinger_version
    except Exception:
        logger.warning(
            "Could not determine the Dallinger version for the export manifest.",
            exc_info=True,
        )
        dallinger_version = None

    counts = dict(row_counts or {})
    files = {}
    for table in table_names:
        path = os.path.join(csv_dir, f"{table}.csv")
        if os.path.exists(path):
            counts.setdefault(table, _count_csv_rows(path))
            files[f"{DATABASE_DIRNAME}/{table}.csv"] = _file_entry(path)
        else:
            counts.setdefault(table, 0)

    if extra_files:
        for name, path in extra_files.items():
            if os.path.exists(path):
                files[name] = _file_entry(path)

    provenance = _provenance_for_manifest()

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "export_format_version": EXPORT_FORMAT_VERSION,
        "deployment_id": provenance["deployment_id"],
        "experiment_label": provenance["experiment_label"],
        "git_commit_sha": provenance["git_commit_sha"],
        "git_dirty": provenance["git_dirty"],
        "psynet_version": psynet_version,
        "dallinger_version": dallinger_version,
        "table_row_counts": counts,
        "files": files,
        "identifier_separation": True,
    }
    manifest_path = os.path.join(export_path, "manifest.json")
    with open(make_parents(manifest_path), "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest_path


def export_database_snapshot(export_path: str) -> dict:
    """Export pseudonymous table CSVs plus identifier sidecars.

    Parameters
    ----------
    export_path :
        Directory that will receive ``database/``, identifier CSVs, and
        ``manifest.json``.

    Returns
    -------
    dict
        Paths to the written artifacts.
    """
    os.makedirs(export_path, exist_ok=True)
    database_dir = os.path.join(export_path, DATABASE_DIRNAME)
    if os.path.exists(database_dir):
        shutil.rmtree(database_dir)

    conn = psycopg2.connect(dsn=_db_dsn())
    conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
    try:
        table_names = copy_database_to_csv_dir(
            database_dir,
            pseudonymize=True,
            _connection=conn,
        )
        sidecar_paths = write_identifier_sidecars(
            export_path,
            table_names,
            _connection=conn,
        )
    finally:
        conn.close()
    row_counts = omit_empty_table_csvs(database_dir, table_names)

    manifest_path = write_export_manifest(
        export_path,
        table_names=table_names,
        csv_dir=database_dir,
        extra_files=sidecar_paths,
        row_counts=row_counts,
    )

    return {
        "database_dir": database_dir,
        "manifest": manifest_path,
        **sidecar_paths,
    }

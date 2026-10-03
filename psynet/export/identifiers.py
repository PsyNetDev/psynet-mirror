"""Identifier separation for exported database snapshots.

Live tables keep recruiter identifiers on ``Participant`` (and ``LucidRID`` for
Lucid ghost entrants). Export writes those values to sidecar CSVs and replaces
them with participant-id pseudonyms in ``database/`` so the archive stays
loadable.

Why this module builds SQL rather than rewriting CSVs
----------------------------------------------------
Separation is expressed as SQL expressions that :mod:`psynet.export.database`
splices into its ``COPY (SELECT …)`` queries. It used to work by exporting raw
CSVs and rewriting them in Python, which was wrong in a way that was hard to
see: PostgreSQL's ``COPY`` writes an empty string as ``""`` and NULL as an
empty field, and Python's ``csv`` reader maps both to ``''``. Re-serializing a
table therefore turned every empty string into NULL, which made the archive
unloadable wherever the column was ``NOT NULL``. Doing the work in the query
removes that failure mode entirely, and removes a full-table Python pass.

Design constraints
------------------
* A redacted column must never become NULL when the schema says ``NOT NULL``,
  or the export cannot be reloaded with ``psynet load``. Nullability is read
  from the live schema rather than hard-coded, so a new ``NOT NULL`` recruiter
  column cannot reintroduce that bug.
* An identifier that belongs to no exported participant cannot be
  pseudonymized. It is replaced by a stable, non-identifying placeholder rather
  than leaked or blanked.
* Every literal goes through :class:`psycopg2.sql.Literal`, so table and column
  names from the live schema cannot be spliced into SQL unsafely.
"""

from __future__ import annotations

from typing import Optional

from psycopg2 import sql

from psynet.identifiers import (
    LUCID_ENTRANT_IDENTIFIER_FIELDS,
    PARTICIPANT_IDENTIFIER_FIELDS,
)

#: Recruiter identifiers that are mapped to a participant pseudonym wherever
#: they appear on a table other than ``participant``.
MAPPED_IDENTIFIER_FIELDS = ("unique_id", "worker_id", "assignment_id")

#: Recruiter columns that carry no analysable information and are redacted.
REDACTED_IDENTIFIER_FIELDS = ("client_ip_address", "entry_information", "hit_id")

#: Columns whose redacted placeholder must remain valid JSON.
_JSON_IDENTIFIER_FIELDS = frozenset({"entry_information", "params"})

_PARTICIPANT_TABLE = "participant"
_LUCID_TABLE = "lucid_rid"
_PARTICIPANT_PSEUDONYM_FIELDS = frozenset(
    {"worker_id", "assignment_id", "hit_id", "unique_id"}
)
_LUCID_PSEUDONYM_FIELDS = frozenset({"rid"})
_LUCID_REDACTED_FIELDS = frozenset({"lucid_panelist_id", "lucid_respondent_id"})


def identifier_role(table: str, column: str) -> Optional[str]:
    """Return ``pseudonym`` or ``redact`` when ``table.column`` is rewritten.

    Returns ``None`` when the column is exported unchanged. The schema
    validator uses this so unsupported custom columns fail closed before COPY.
    """
    if table == _PARTICIPANT_TABLE:
        if column in _PARTICIPANT_PSEUDONYM_FIELDS:
            return "pseudonym"
        if column in REDACTED_IDENTIFIER_FIELDS:
            return "redact"
        return None
    if table == _LUCID_TABLE:
        if column in _LUCID_PSEUDONYM_FIELDS:
            return "pseudonym"
        if column in _LUCID_REDACTED_FIELDS:
            return "redact"
        return None
    if column in MAPPED_IDENTIFIER_FIELDS:
        return "pseudonym"
    if column in REDACTED_IDENTIFIER_FIELDS:
        return "redact"
    if table == "request" and column == "params":
        return "redact"
    return None


def _participant_id_text() -> sql.Composable:
    return sql.SQL("{}::text").format(sql.Identifier("id"))


def _redaction(
    table: str, column: str, not_null: set, has_id: bool, *, kind: str = "text"
) -> sql.Composable:
    """Return the expression used when a recruiter identifier must be removed.

    Nullable columns become NULL. ``NOT NULL`` columns get a stable,
    non-identifying placeholder, because NULL would violate the constraint when
    the archive is reloaded.
    """
    if column not in not_null:
        return sql.SQL("NULL")
    if kind == "json" or column in _JSON_IDENTIFIER_FIELDS:
        return sql.Literal("{}")
    if not has_id:
        return sql.Literal(f"redacted-{table}")
    return sql.SQL("{prefix} || {id}").format(
        prefix=sql.Literal(f"redacted-{table}-"), id=_participant_id_text()
    )


def _pseudonym_lookup(table: str, column: str) -> sql.Composable:
    """Return a scalar subquery mapping a recruiter identifier to a pseudonym.

    ``worker_id`` is not unique (one worker may hold several assignments), so
    the lookup takes the lowest matching participant id to stay deterministic.
    """
    pseudonym = (
        sql.SQL("{id} || ':' || {id}").format(id=sql.SQL("p.id::text"))
        if column == "unique_id"
        else sql.SQL("p.id::text")
    )
    return sql.SQL(
        "(SELECT {pseudonym} FROM {participant} p "
        "WHERE p.{column} = {qualified} ORDER BY p.id LIMIT 1)"
    ).format(
        pseudonym=pseudonym,
        participant=sql.Identifier(_PARTICIPANT_TABLE),
        column=sql.Identifier(column),
        qualified=sql.Identifier(table, column),
    )


def identifier_override(
    table: str,
    column: str,
    *,
    not_null: set,
    has_id: bool,
    kind: str = "text",
) -> Optional[sql.Composable]:
    """Return the SELECT expression that pseudonymizes ``table.column``.

    ``kind`` is the validated storage class from
    :mod:`psynet.export.identifier_schema` (``text`` or ``json``). Returns
    ``None`` when the column carries no recruiter identifier and should be
    exported unchanged. Callers must validate the schema first so an
    unsupported type is never left as an ambiguous same-named column.
    """
    role = identifier_role(table, column)
    if role is None:
        return None
    if table == _PARTICIPANT_TABLE:
        if column == "unique_id":
            return sql.SQL("{id} || ':' || {id}").format(id=_participant_id_text())
        if column in _PARTICIPANT_PSEUDONYM_FIELDS:
            return _participant_id_text()
        return _redaction(_PARTICIPANT_TABLE, column, not_null, has_id=True, kind=kind)
    if table == _LUCID_TABLE:
        if column in _LUCID_PSEUDONYM_FIELDS:
            return sql.SQL("COALESCE({participant}::text, {prefix} || {id})").format(
                participant=sql.Identifier("participant_id"),
                prefix=sql.Literal("entrant-"),
                id=_participant_id_text(),
            )
        return _redaction(_LUCID_TABLE, column, not_null, has_id=True, kind=kind)
    if role == "pseudonym":
        return sql.SQL("COALESCE({lookup}, {fallback})").format(
            lookup=_pseudonym_lookup(table, column),
            fallback=_redaction(table, column, not_null, has_id, kind=kind),
        )
    return _redaction(table, column, not_null, has_id, kind=kind)


def _sidecar_query(table: str, fields: tuple, id_alias: str) -> sql.Composable:
    """Build a COPY query for one identifier sidecar."""
    selected = []
    for field in fields:
        source = "id" if field == id_alias else field
        selected.append(
            sql.SQL("{col} AS {alias}").format(
                col=sql.Identifier(source), alias=sql.Identifier(field)
            )
        )
    return sql.SQL(
        "COPY (SELECT {fields} FROM {table}) TO STDOUT WITH CSV HEADER"
    ).format(fields=sql.SQL(", ").join(selected), table=sql.Identifier(table))


def sidecar_specs(available_tables: set) -> dict[str, tuple[str, sql.Composable]]:
    """Return ``key -> (filename, copy_query)`` for the identifier sidecars.

    The Lucid sidecar is only meaningful for Lucid deployments; callers drop it
    when the table turns out to be empty.
    """
    specs = {}
    if _PARTICIPANT_TABLE in available_tables:
        specs["participant_identifiers"] = (
            "participant_identifiers.csv",
            _sidecar_query(
                _PARTICIPANT_TABLE, PARTICIPANT_IDENTIFIER_FIELDS, "participant_id"
            ),
        )
    if _LUCID_TABLE in available_tables:
        specs["lucid_entrant_identifiers"] = (
            "lucid_entrant_identifiers.csv",
            _sidecar_query(
                _LUCID_TABLE,
                # participant_id is not a recruiter identifier, but including it
                # makes the sidecar joinable to the pseudonymous tables.
                LUCID_ENTRANT_IDENTIFIER_FIELDS + ("participant_id",),
                "lucid_rid_id",
            ),
        )
    return specs

"""Fail-closed classification of identifier columns before COPY export.

Identifier separation is expressed as SQL that writes text pseudonyms and
placeholders into the same column names the live schema uses. That is only
safe when those columns can actually store the rewritten values. Name-only
matching previously left integer, UUID, enum, short ``VARCHAR``, and no-``id``
tables unchanged or produced archives that PostgreSQL would refuse to reload.

This module inspects the live schema once, before any table is copied, and
either records the metadata the SQL builder needs or raises a single
actionable error. Custom columns that share a recruiter-identifier name but
not a supported type are rejected rather than leaked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import String, Text, Unicode, UnicodeText
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql.sqltypes import JSON as SA_JSON

from .identifiers import identifier_role

#: Conservative width for a 64-bit integer spelled as text.
_ID_TEXT_WIDTH = 20


class UnsupportedIdentifierSchemaError(ValueError):
    """Raised when identifier separation cannot be applied to the live schema."""


@dataclass(frozen=True)
class IdentifierColumn:
    """Reflected metadata for one identifier-bearing column."""

    table: str
    name: str
    kind: str
    nullable: bool
    max_length: Optional[int]
    has_id: bool
    unique: bool
    sa_type: Any


@dataclass(frozen=True)
class IdentifierSchema:
    """Validated identifier columns keyed by ``(table, column)``."""

    columns: dict[tuple[str, str], IdentifierColumn]

    def get(self, table: str, name: str) -> Optional[IdentifierColumn]:
        """Return the policy for ``table.name``, if it is an identifier."""
        return self.columns.get((table, name))


def classify_identifier_type(sa_type: Any) -> str:
    """Return ``text``, ``json``, or ``unsupported`` for a reflected type."""
    type_name = type(sa_type).__name__.lower()
    if isinstance(sa_type, SA_JSON) or type_name in {"json", "jsonb"}:
        return "json"
    if isinstance(sa_type, (Text, UnicodeText)):
        return "text"
    if isinstance(sa_type, (String, Unicode)):
        return "text"
    if "varchar" in type_name or type_name in {"text", "citext"}:
        return "text"
    return "unsupported"


def _type_length(sa_type: Any) -> Optional[int]:
    length = getattr(sa_type, "length", None)
    return int(length) if isinstance(length, int) and length > 0 else None


def _table_has_id(columns: list[dict]) -> bool:
    return any(column["name"] == "id" for column in columns)


def _unique_column_names(inspector, table: str) -> set[str]:
    unique: set[str] = set()
    pk = inspector.get_pk_constraint(table) or {}
    constrained = pk.get("constrained_columns") or []
    if len(constrained) == 1:
        unique.add(constrained[0])
    for item in inspector.get_unique_constraints(table) or []:
        cols = item.get("column_names") or []
        if len(cols) == 1:
            unique.add(cols[0])
    for item in inspector.get_indexes(table) or []:
        if not item.get("unique"):
            continue
        cols = item.get("column_names") or []
        if len(cols) == 1:
            unique.add(cols[0])
    return unique


def _required_text_width(info: IdentifierColumn, role: str) -> int:
    """Return the longest text value identifier separation can write."""
    table = info.table
    column = info.name
    if info.kind == "json":
        return 0
    if role == "redact" and info.nullable:
        return 0
    if table == "participant" and column == "unique_id":
        return _ID_TEXT_WIDTH * 2 + 1
    if table == "participant" and column in {"worker_id", "assignment_id", "hit_id"}:
        return _ID_TEXT_WIDTH
    if table == "lucid_rid" and column == "rid":
        return max(_ID_TEXT_WIDTH, len("entrant-") + _ID_TEXT_WIDTH)
    if role == "pseudonym":
        pseudonym_width = (
            _ID_TEXT_WIDTH * 2 + 1 if column == "unique_id" else _ID_TEXT_WIDTH
        )
        if info.nullable:
            return pseudonym_width
        return max(pseudonym_width, len(f"redacted-{table}-") + _ID_TEXT_WIDTH)
    if info.has_id:
        return len(f"redacted-{table}-") + _ID_TEXT_WIDTH
    return len(f"redacted-{table}")


def validate_identifier_schema(
    inspector=None,
    table_names: Optional[Iterable[str]] = None,
) -> IdentifierSchema:
    """Inspect identifier columns and reject schemas that cannot be rewritten.

    Parameters
    ----------
    inspector :
        SQLAlchemy inspector. Created from the live engine when omitted.
    table_names :
        Physical tables that will be copied. Defaults to every table.

    Returns
    -------
    IdentifierSchema
        Metadata for every identifier column that will be transformed.

    Raises
    ------
    UnsupportedIdentifierSchemaError
        If any identifier column cannot store the rewritten value, or if
        leaving it unchanged would leak a recruiter identifier.
    """
    from dallinger import db

    inspector = inspector if inspector is not None else sa_inspect(db.engine)
    tables = (
        list(table_names)
        if table_names is not None
        else sorted(inspector.get_table_names())
    )
    columns: dict[tuple[str, str], IdentifierColumn] = {}
    problems: list[str] = []

    for table in tables:
        reflected = inspector.get_columns(table)
        has_id = _table_has_id(reflected)
        unique_names = _unique_column_names(inspector, table)
        not_null = {column["name"] for column in reflected if not column["nullable"]}

        for column in reflected:
            name = column["name"]
            role = identifier_role(table, name)
            if role is None:
                continue
            kind = classify_identifier_type(column["type"])
            info = IdentifierColumn(
                table=table,
                name=name,
                kind=kind,
                nullable=column["nullable"],
                max_length=_type_length(column["type"]),
                has_id=has_id,
                unique=name in unique_names,
                sa_type=column["type"],
            )
            problem = _column_problem(info, role, not_null)
            if problem:
                problems.append(problem)
            else:
                columns[(table, name)] = info

    if problems:
        details = " ".join(problems)
        raise UnsupportedIdentifierSchemaError(
            "This experiment's database schema cannot be exported with "
            "identifier separation. Recruiter-identifier columns must be "
            f"unconstrained text or JSON. {details}"
        )
    return IdentifierSchema(columns=columns)


def _column_problem(
    info: IdentifierColumn, role: str, not_null: set[str]
) -> Optional[str]:
    location = f"{info.table}.{info.name}"
    if role == "pseudonym" and info.kind != "text":
        return (
            f"{location} is a recruiter identifier but has type "
            f"{info.sa_type}, which cannot store a text pseudonym."
        )
    if info.kind == "unsupported":
        return (
            f"{location} is a recruiter identifier but has type "
            f"{info.sa_type}, which cannot store a text or JSON placeholder."
        )
    if info.kind == "json" and info.name not in {"entry_information", "params"}:
        return (
            f"{location} is JSON; identifier separation only rewrites "
            "entry_information and request.params as JSON."
        )
    if not info.has_id and info.name in not_null:
        return (
            f"{location} is NOT NULL on a table with no id column, so a "
            "stable per-row placeholder cannot be generated."
        )
    if not info.has_id and info.unique:
        return (
            f"{location} is unique on a table with no id column, so a "
            "shared placeholder would violate uniqueness."
        )
    needed = _required_text_width(info, role)
    if info.max_length is not None and info.max_length < needed:
        return (
            f"{location} is VARCHAR({info.max_length}), which is shorter than "
            f"the {needed}-character value identifier separation can write."
        )
    return None

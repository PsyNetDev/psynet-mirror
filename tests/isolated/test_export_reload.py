"""Database-backed tests for the canonical export's value handling.

Identifier separation and boolean formatting both happen inside the ``COPY``
query, so they can only be tested against a real database. That is deliberate:
the previous CSV-rewriting implementation passed file-based unit tests while
producing archives that could not be reloaded. Each test here therefore exports
from live tables and, where it matters, loads the result straight back.
"""

import csv
import uuid

import pytest
from dallinger import db
from sqlalchemy import Boolean, Column, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from psynet.data import SQLBase, ingest_to_model
from psynet.export.database import copy_database_to_csv_dir, write_identifier_sidecars
from psynet.export.identifier_schema import UnsupportedIdentifierSchemaError
from psynet.pytest_psynet import path_to_test_experiment

SCRATCH_TABLE = "export_reload_model"

in_consents_experiment = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)


class ExportReloadModel(SQLBase):
    __tablename__ = SCRATCH_TABLE

    id = Column(Integer, primary_key=True)
    failed = Column(Boolean, nullable=False)
    optional_flag = Column(Boolean, nullable=True)
    note = Column(Text, nullable=False)
    assignment_id = Column(Text, nullable=False)


def _read_rows(path, key: str = "id") -> dict:
    with open(path, newline="") as handle:
        return {row[key]: row for row in csv.DictReader(handle)}


@pytest.fixture
def scratch_table(db_session):
    # The table is left in place afterwards; the db_session fixture drops every
    # table before each test, and dropping it here would need a second
    # connection and deadlock against this session's own locks.
    ExportReloadModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    db_session.add_all(
        [
            ExportReloadModel(
                id=1, failed=False, optional_flag=True, note="hello", assignment_id="a1"
            ),
            # A blank NOT NULL text value and a NULL boolean: COPY writes these
            # differently, and the export must preserve the difference.
            ExportReloadModel(
                id=2, failed=True, optional_flag=None, note="", assignment_id="a2"
            ),
        ]
    )
    db_session.commit()
    return db_session


def _insert(db_session, table: str, rows: list[dict]) -> None:
    """Insert rows through Core so SQLAlchemy fills in the column defaults."""
    db_session.execute(SQLBase.metadata.tables[table].insert().values(rows))


@pytest.fixture
def recruiter_rows(db_session):
    """Insert a participant, its notifications, and two Lucid entrants."""
    _insert(
        db_session,
        "participant",
        [
            {
                "id": 7,
                "type": "participant",
                "worker_id": "worker-abc",
                "assignment_id": "assignment-1",
                "unique_id": "worker-abc:assignment-1",
                "hit_id": "hit-1",
                "mode": "debug",
                "client_ip_address": "1.2.3.4",
                "entry_information": {"email": "a@b.c"},
            }
        ],
    )
    _insert(
        db_session,
        "notification",
        [
            {
                "id": 1,
                "assignment_id": "assignment-1",
                "event_type": "AssignmentAccepted",
            },
            # Dallinger records errors against an assignment that may belong to
            # no participant, e.g. the literal 'unknown'.
            {"id": 2, "assignment_id": "unknown", "event_type": "ExperimentError"},
        ],
    )
    _insert(
        db_session,
        "lucid_rid",
        [
            {
                "id": 3,
                "rid": "lucid-rid",
                "participant_id": 7,
                "lucid_panelist_id": "p1",
            },
            {
                "id": 4,
                "rid": "ghost-rid",
                "participant_id": None,
                "lucid_panelist_id": "p2",
            },
        ],
    )
    db_session.commit()
    return db_session


@in_consents_experiment
def test_exported_booleans_and_blank_strings_reload_unchanged(scratch_table, tmp_path):
    copy_database_to_csv_dir(str(tmp_path), [SCRATCH_TABLE])
    csv_path = tmp_path / f"{SCRATCH_TABLE}.csv"

    exported = csv_path.read_text()
    # Booleans read as logicals in pandas/R/Excel rather than as "t"/"f".
    assert "False" in exported and "True" in exported
    assert ",t," not in exported and ",f," not in exported
    # An empty string stays quoted; only NULL is a bare empty field.
    assert '""' in exported

    scratch_table.query(ExportReloadModel).delete()
    scratch_table.commit()
    with open(csv_path, encoding="utf8", newline="") as handle:
        ingest_to_model(handle, ExportReloadModel, db.engine)

    reloaded = {row.id: row for row in scratch_table.query(ExportReloadModel).all()}
    assert reloaded[1].failed is False
    assert reloaded[1].optional_flag is True
    assert reloaded[2].failed is True
    assert reloaded[2].optional_flag is None
    assert reloaded[2].note == ""


@in_consents_experiment
def test_identifier_separation_pseudonymizes_and_reloads(recruiter_rows, tmp_path):
    tables = ["participant", "notification", "lucid_rid"]
    copy_database_to_csv_dir(str(tmp_path), tables, pseudonymize=True)

    participant = _read_rows(tmp_path / "participant.csv")["7"]
    assert participant["worker_id"] == "7"
    assert participant["assignment_id"] == "7"
    assert participant["hit_id"] == "7"
    assert participant["unique_id"] == "7:7"
    assert participant["client_ip_address"] == ""
    # NOT NULL, so it must be an empty JSON object rather than a blank field.
    assert participant["entry_information"] == "{}"

    notification = _read_rows(tmp_path / "notification.csv")
    assert notification["1"]["assignment_id"] == "7"
    # assignment_id is NOT NULL, so an identifier belonging to no exported
    # participant must be redacted to a placeholder rather than blanked.
    assert notification["2"]["assignment_id"] == "redacted-notification-2"

    lucid = _read_rows(tmp_path / "lucid_rid.csv")
    assert lucid["3"]["rid"] == "7"
    assert lucid["4"]["rid"] == "entrant-4"
    assert lucid["3"]["lucid_panelist_id"] == ""

    # The pseudonymous tables must still load back into a fresh database.
    recruiter_rows.execute(text("DELETE FROM lucid_rid"))
    recruiter_rows.execute(text("DELETE FROM notification"))
    recruiter_rows.execute(text("DELETE FROM participant"))
    recruiter_rows.commit()
    from psynet.data import sql_base_classes

    models = sql_base_classes()
    for table in tables:
        with open(tmp_path / f"{table}.csv", encoding="utf8", newline="") as handle:
            ingest_to_model(handle, models[table], db.engine)

    reloaded = recruiter_rows.execute(
        text("SELECT worker_id, entry_information FROM participant WHERE id = 7")
    ).one()
    assert reloaded.worker_id == "7"
    assert reloaded.entry_information == {}


@in_consents_experiment
def test_identifier_sidecars_keep_the_original_values(recruiter_rows, tmp_path):
    paths = write_identifier_sidecars(
        str(tmp_path), ["participant", "notification", "lucid_rid"]
    )

    participant = _read_rows(paths["participant_identifiers"], "participant_id")["7"]
    assert list(participant) == [
        "participant_id",
        "worker_id",
        "assignment_id",
        "hit_id",
        "unique_id",
        "client_ip_address",
        "entry_information",
    ]
    assert participant["worker_id"] == "worker-abc"
    assert participant["entry_information"] == '{"email": "a@b.c"}'

    with open(paths["lucid_entrant_identifiers"], newline="") as handle:
        lucid = list(csv.DictReader(handle))
    assert {row["rid"] for row in lucid} == {"lucid-rid", "ghost-rid"}


@in_consents_experiment
def test_empty_lucid_table_omits_its_sidecar(db_session, tmp_path):
    paths = write_identifier_sidecars(str(tmp_path), ["participant", "lucid_rid"])

    assert "lucid_entrant_identifiers" not in paths
    assert not (tmp_path / "lucid_entrant_identifiers.csv").exists()
    assert (tmp_path / "participant_identifiers.csv").exists()


class IntegerIdentifierModel(SQLBase):
    __tablename__ = "export_int_ident"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(Integer, nullable=False)


class ShortIdentifierModel(SQLBase):
    __tablename__ = "export_short_ident"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(String(8), nullable=False)


class NullableShortIdentifierModel(SQLBase):
    __tablename__ = "export_nullable_short_ident"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(String(8), nullable=True)


class UUIDIdentifierModel(SQLBase):
    __tablename__ = "export_uuid_ident"

    id = Column(Integer, primary_key=True)
    assignment_id = Column(UUID(as_uuid=True), nullable=True)


class NullableShortRedactedModel(SQLBase):
    __tablename__ = "export_nullable_short_redacted"

    id = Column(Integer, primary_key=True)
    client_ip_address = Column(String(1), nullable=True)


class NoIdIdentifierModel(SQLBase):
    __tablename__ = "export_noid_ident"

    code = Column(Integer, primary_key=True)
    assignment_id = Column(Text, nullable=False)


@in_consents_experiment
def test_integer_identifier_columns_are_rejected(db_session, tmp_path):
    IntegerIdentifierModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    db_session.add(IntegerIdentifierModel(id=1, assignment_id=99))
    db_session.commit()

    with pytest.raises(UnsupportedIdentifierSchemaError, match="export_int_ident"):
        copy_database_to_csv_dir(str(tmp_path), ["export_int_ident"], pseudonymize=True)


@in_consents_experiment
def test_short_varchar_identifier_columns_are_rejected(db_session, tmp_path):
    ShortIdentifierModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    db_session.add(ShortIdentifierModel(id=1, assignment_id="abc"))
    db_session.commit()

    with pytest.raises(UnsupportedIdentifierSchemaError, match="VARCHAR"):
        copy_database_to_csv_dir(
            str(tmp_path), ["export_short_ident"], pseudonymize=True
        )


@in_consents_experiment
def test_nullable_short_varchar_identifier_columns_are_rejected(db_session, tmp_path):
    NullableShortIdentifierModel.__table__.create(
        bind=db_session.get_bind(), checkfirst=True
    )
    db_session.add(NullableShortIdentifierModel(id=1, assignment_id="abc"))
    db_session.commit()

    with pytest.raises(UnsupportedIdentifierSchemaError, match="VARCHAR"):
        copy_database_to_csv_dir(
            str(tmp_path), ["export_nullable_short_ident"], pseudonymize=True
        )


@in_consents_experiment
def test_uuid_identifier_columns_are_rejected(db_session, tmp_path):
    UUIDIdentifierModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    db_session.add(UUIDIdentifierModel(id=1, assignment_id=uuid.uuid4()))
    db_session.commit()

    with pytest.raises(UnsupportedIdentifierSchemaError, match="UUID"):
        copy_database_to_csv_dir(
            str(tmp_path), ["export_uuid_ident"], pseudonymize=True
        )


@in_consents_experiment
def test_nullable_short_redacted_columns_are_safe(db_session, tmp_path):
    NullableShortRedactedModel.__table__.create(
        bind=db_session.get_bind(), checkfirst=True
    )
    db_session.add(NullableShortRedactedModel(id=1, client_ip_address="x"))
    db_session.commit()

    copy_database_to_csv_dir(
        str(tmp_path), ["export_nullable_short_redacted"], pseudonymize=True
    )

    row = _read_rows(tmp_path / "export_nullable_short_redacted.csv")["1"]
    assert row["client_ip_address"] == ""


@in_consents_experiment
def test_identifier_tables_without_id_are_rejected(db_session, tmp_path):
    NoIdIdentifierModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    db_session.add(NoIdIdentifierModel(code=1, assignment_id="a1"))
    db_session.commit()

    with pytest.raises(UnsupportedIdentifierSchemaError, match="no id column"):
        copy_database_to_csv_dir(
            str(tmp_path), ["export_noid_ident"], pseudonymize=True
        )

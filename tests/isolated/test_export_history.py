"""Database-backed tests for the export history on the dashboard's Export tab."""

import csv

import pytest

from psynet.export.history import ExportRecord
from psynet.export.service import build_export_tree
from psynet.pytest_psynet import path_to_test_experiment

pytestmark = pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)


def _add_participants(db_session, completes):
    from psynet.data import SQLBase

    db_session.execute(
        SQLBase.metadata.tables["participant"]
        .insert()
        .values(
            [
                {
                    "id": i,
                    "type": "participant",
                    "worker_id": f"worker-{i}",
                    "assignment_id": f"assignment-{i}",
                    "unique_id": f"worker-{i}:assignment-{i}",
                    "hit_id": "hit",
                    "mode": "debug",
                    "complete": complete,
                }
                for i, complete in enumerate(completes, start=1)
            ]
        )
    )
    db_session.commit()


def test_each_requested_export_is_recorded_with_its_participant_counts(
    db_session, tmp_path
):
    _add_participants(db_session, completes=[True, False])

    # Scheduled backups pass no source and are not recorded.
    build_export_tree(str(tmp_path / "backup"), assets="none")
    assert db_session.query(ExportRecord).count() == 0

    build_export_tree(str(tmp_path / "first"), assets="none", source="dashboard")
    build_export_tree(str(tmp_path / "second"), assets="none", source="command_line")

    records = db_session.query(ExportRecord).order_by(ExportRecord.id).all()
    assert [
        (r.source, r.assets, r.n_participants, r.n_completed_participants)
        for r in records
    ] == [("dashboard", "none", 2, 1), ("command_line", "none", 2, 1)]

    # An export holds the history of the exports before it, not its own row.
    with open(tmp_path / "second" / "database" / "export_record.csv") as handle:
        exported = list(csv.DictReader(handle))
    assert [row["source"] for row in exported] == ["dashboard"]

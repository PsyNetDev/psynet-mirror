"""Identifier ownership lives on Participant (and LucidRID for ghosts)."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from dallinger import db
from sqlalchemy import inspect as sa_inspect

from psynet.error import ErrorRecord
from psynet.identifiers import (
    LUCID_ENTRANT_IDENTIFIER_FIELDS,
    PARTICIPANT_IDENTIFIER_FIELDS,
)
from psynet.recruiters import LucidRecruiter, LucidRID
from psynet.timeline import Response


def test_participant_identifier_fields():
    assert PARTICIPANT_IDENTIFIER_FIELDS == (
        "participant_id",
        "worker_id",
        "assignment_id",
        "hit_id",
        "unique_id",
        "client_ip_address",
        "entry_information",
    )


def test_lucid_entrant_identifier_fields():
    assert LUCID_ENTRANT_IDENTIFIER_FIELDS == (
        "lucid_rid_id",
        "rid",
        "lucid_panelist_id",
        "lucid_respondent_id",
    )


def test_error_record_has_no_worker_id_column():
    columns = {c.key for c in sa_inspect(ErrorRecord).columns}
    assert "worker_id" not in columns
    assert "participant_id" in columns


def test_response_has_no_client_ip_column():
    columns = {c.key for c in sa_inspect(Response).columns}
    assert "client_ip_address" not in columns
    assert "participant_id" in columns


def test_lucid_rid_uses_participant_id_fk():
    columns = {c.key: c for c in sa_inspect(LucidRID).columns}
    assert "participant_id" in columns
    assert "rid" in columns
    rid_fks = list(columns["rid"].foreign_keys)
    assert rid_fks == []
    participant_fks = list(columns["participant_id"].foreign_keys)
    assert len(participant_fks) == 1
    assert participant_fks[0].column.table.name == "participant"


def test_request_params_is_redacted_as_json():
    from psynet.export.identifiers import _JSON_IDENTIFIER_FIELDS, identifier_role

    assert identifier_role("request", "params") == "redact"
    assert "params" in _JSON_IDENTIFIER_FIELDS


def test_linking_lucid_participant_does_not_commit_the_request_transaction():
    entrant = SimpleNamespace(participant_id=None)
    entrant.link_participant = lambda participant: setattr(
        entrant, "participant_id", participant.id
    )
    query = Mock()
    query.filter_by.return_value.one.return_value = entrant
    participant = SimpleNamespace(id=42, worker_id="respondent-1")

    with (
        patch.object(LucidRID, "query", query),
        patch.object(db.session, "commit") as commit,
    ):
        LucidRecruiter.link_lucid_rid_to_participant(object(), participant)

    assert entrant.participant_id == participant.id
    commit.assert_not_called()

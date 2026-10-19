from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy.orm.exc

from psynet.experiment import Experiment
from psynet.participant import Participant
from psynet.recruiters import LucidRID, _latest_participant_for_worker_id


def _query_returning(participant):
    query = MagicMock()
    query.filter_by.return_value.order_by.return_value.first.return_value = participant
    return query


def test_lucid_rid_resolve_participant_returns_latest_unlinked_match():
    latest = SimpleNamespace(id=9)
    query = _query_returning(latest)
    entrant = SimpleNamespace(participant_id=None, rid="rid-1", participant=None)

    with patch.object(Participant, "query", query):
        assert LucidRID.resolve_participant(entrant) is latest

    query.filter_by.assert_called_once_with(worker_id="rid-1")


def test_lucid_rid_resolve_participant_uses_linked_participant():
    linked = SimpleNamespace(id=3)
    query = MagicMock()
    entrant = SimpleNamespace(participant_id=3, rid="rid-1", participant=linked)

    with patch.object(Participant, "query", query):
        assert LucidRID.resolve_participant(entrant) is linked

    query.filter_by.assert_not_called()


def test_get_participant_from_worker_id_returns_latest():
    latest = SimpleNamespace(id=12)
    query = _query_returning(latest)

    with patch.object(Participant, "query", query):
        assert Experiment.get_participant_from_worker_id("worker-1") is latest

    query.filter_by.assert_called_once_with(worker_id="worker-1")


def test_latest_participant_for_worker_id_skips_empty():
    query = MagicMock()
    with patch.object(Participant, "query", query):
        assert _latest_participant_for_worker_id("") is None
        assert _latest_participant_for_worker_id(None) is None
    query.filter_by.assert_not_called()


def test_dashboard_participants_opens_latest_worker():
    from flask import Flask

    participant = SimpleNamespace(id=12, recruiter=None)
    app = Flask("psynet_test")
    with app.test_request_context("/dashboard/participants?worker_id=worker-1"):
        with patch.object(
            Experiment,
            "get_participant_from_worker_id",
            return_value=participant,
        ) as lookup:
            with patch(
                "psynet.experiment.Participant.needing_payment_review",
                return_value=[],
            ):
                with patch(
                    "psynet.experiment.render_template", return_value="ok"
                ) as render:
                    with patch(
                        "psynet.experiment.get_experiment_url",
                        return_value="http://exp",
                    ):
                        with patch("psynet.experiment.get_config") as get_config:
                            get_config.return_value.currency = "$"
                            assert Experiment.dashboard_participants() == "ok"

    lookup.assert_called_once_with("worker-1", for_update=False)
    assert render.call_args.kwargs["participant"] is participant
    assert render.call_args.kwargs["message"] == ""


def test_get_participant_from_worker_id_raises_when_missing():
    query = _query_returning(None)

    with (
        patch.object(Participant, "query", query),
        pytest.raises(sqlalchemy.orm.exc.NoResultFound),
    ):
        Experiment.get_participant_from_worker_id("worker-1")

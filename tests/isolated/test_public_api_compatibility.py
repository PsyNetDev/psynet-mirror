"""Regression tests for public APIs retained during export refactoring."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest
from flask import Flask
from flask import Response as FlaskResponse

from psynet.artifact import ArtifactStorage
from psynet.experiment import Experiment, ResponseResult
from psynet.timeline import FailedValidation


@pytest.mark.parametrize(
    "args, expected_deployment",
    [
        (("psynet", "/tmp/export.zip"), "current-deployment"),
        (("database", "/tmp/export.zip", "older-deployment"), "older-deployment"),
    ],
)
def test_download_export_accepts_the_legacy_positional_order(args, expected_deployment):
    storage = object.__new__(ArtifactStorage)
    storage.prepare_path = Mock(return_value="/remote/export.zip")
    storage.download = Mock()

    with (
        patch.object(
            ArtifactStorage,
            "experiment",
            new_callable=PropertyMock,
            return_value=SimpleNamespace(deployment_id="current-deployment"),
        ),
        pytest.warns(DeprecationWarning),
    ):
        storage.download_export(*args)

    storage.prepare_path.assert_called_once_with(expected_deployment, "export.zip")
    storage.download.assert_called_once_with("/remote/export.zip", "/tmp/export.zip")


def _process_response_on(page, monkeypatch, client_ip_address="127.0.0.1"):
    participant = SimpleNamespace(id=1, page_uuid="page-1", client_ip_address=None)
    query = Mock()
    query.with_for_update.return_value.populate_existing.return_value.get.return_value = participant
    experiment = object.__new__(Experiment)
    experiment.timeline = Mock()
    experiment.timeline.get_current_elt.return_value = page
    monkeypatch.setenv("PASSTHROUGH_ERRORS", "1")
    with (
        patch.object(Experiment, "_participant_request_query", return_value=query),
        patch("psynet.media_upload._expire_participant_recordings"),
        patch("psynet.experiment.get_translator", return_value=lambda *args: args[-1]),
    ):
        return experiment.process_response(
            participant_id=1,
            raw_answer="answer",
            blobs={},
            metadata={},
            page_uuid="page-1",
            client_ip_address=client_ip_address,
        )


def test_experiment_passes_client_ip_to_legacy_page_response_override(monkeypatch):
    class ResponseReached(Exception):
        pass

    # Not a Page, so it has none of Page's other methods.
    class LegacyPage:
        is_timeline_hold = False

        def process_response(
            self,
            raw_answer,
            blobs,
            metadata,
            experiment,
            participant,
            client_ip_address,
            answer,
        ):
            assert client_ip_address == "203.0.113.5"
            raise ResponseReached

    with pytest.raises(ResponseReached):
        _process_response_on(LegacyPage(), monkeypatch, "203.0.113.5")


def test_validate_cannot_ask_the_page_to_resend_its_response(monkeypatch, caplog):
    class Page:
        is_timeline_hold = False

        def process_response(self, **kwargs):
            return SimpleNamespace(answer=kwargs["raw_answer"], metadata={})

        def _reject_impossible_answer(self, answer):
            return None

        def validate(self, response, **kwargs):
            return FailedValidation("Try again.", retry_after=2)

    with caplog.at_level(logging.WARNING):
        result = _process_response_on(Page(), monkeypatch)

    assert result.payload == {"submission": "rejected", "message": "Try again."}
    assert "only check_ready_for_response can use" in caplog.text


def test_an_override_of_response_rejected_without_retry_after_still_works():
    class LegacyExperiment:
        def process_response(self, *args, **kwargs):
            return ResponseResult(payload={"submission": "rejected", "message": "No."})

        def response_rejected(self, message):
            return FlaskResponse(json.dumps({"rejected": message}))

    with (
        Flask(__name__).test_request_context(
            "/response",
            method="POST",
            data={
                "json": json.dumps(
                    {"participant_id": 1, "page_uuid": "page-1", "metadata": {}}
                )
            },
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ),
        patch("psynet.experiment.get_experiment", return_value=LegacyExperiment()),
        patch("psynet.experiment._set_transaction_lock_timeout"),
        patch("psynet.experiment.get_config", return_value={}),
    ):
        response = Experiment.route_response()

    assert json.loads(response.get_data()) == {"rejected": "No."}

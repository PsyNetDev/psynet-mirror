"""Regression tests for public APIs retained during export refactoring."""

from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest

from psynet.artifact import ArtifactStorage
from psynet.experiment import Experiment


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


def test_experiment_passes_client_ip_to_legacy_page_response_override(monkeypatch):
    class ResponseReached(Exception):
        pass

    class LegacyPage:
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

    participant = SimpleNamespace(page_uuid="page-1", client_ip_address=None)
    query = Mock()
    query.with_for_update.return_value.populate_existing.return_value.get.return_value = participant
    experiment = object.__new__(Experiment)
    experiment.timeline = Mock()
    experiment.timeline.get_current_elt.return_value = LegacyPage()
    monkeypatch.setenv("PASSTHROUGH_ERRORS", "1")

    with (
        patch.object(Experiment, "_participant_request_query", return_value=query),
        patch("psynet.experiment.get_translator", return_value=lambda *args: args[-1]),
        pytest.raises(ResponseReached),
    ):
        experiment.process_response(
            participant_id=1,
            raw_answer="answer",
            blobs={},
            metadata={},
            page_uuid="page-1",
            client_ip_address="203.0.113.5",
        )

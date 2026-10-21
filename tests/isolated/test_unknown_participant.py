"""Requests from a participant session that the database doesn't know."""

import json
import logging

import pytest

from psynet.pytest_psynet import path_to_test_experiment

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("timeline")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def client(db_session, deployment_info):
    from dallinger.experiment_server.experiment_server import app

    return app.test_client()


@pytest.mark.parametrize(
    "method, path, data",
    [
        ("GET", "/timeline?unique_id=gone:gone&mode=json", None),
        (
            "POST",
            "/response",
            {
                "json": json.dumps(
                    {"participant_id": 999999, "page_uuid": "x", "metadata": {}}
                )
            },
        ),
        ("POST", "/log/info/gone:gone", {"message": "hello"}),
        ("POST", "/participant_opened_devtools/gone:gone", None),
        ("GET", "/timeline/progress_and_reward?participantId=999999", None),
    ],
)
def test_requests_of_an_unknown_session_get_a_404_and_one_warning(
    client, caplog, method, path, data
):
    with caplog.at_level(logging.WARNING):
        response = client.open(path, method=method, data=data)

    assert response.status_code == 404
    assert response.json["status"] == "unknown_participant"
    assert "no longer available" in response.json["message"]
    route = path.split("?")[0]
    assert [r.getMessage() for r in caplog.records] == [
        f"{method} {route}: unknown participant, answered 'session no longer "
        "available' (a browser tab from an earlier session?)."
    ]
    assert not any(r.exc_info for r in caplog.records)

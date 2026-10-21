"""Requests from a participant session that the database doesn't know."""

import json
import logging
from importlib import resources

import pytest
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

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
def client(db_session, deployment_info, monkeypatch):
    from dallinger.experiment_server.experiment_server import app

    # Deployments copy PsyNet's templates next to Dallinger's; tests don't.
    layout = (
        "<html>{% block title %}{% endblock %}{% block body %}{% endblock %}</html>"
    )
    loader = ChoiceLoader(
        [
            FileSystemLoader(str(resources.files("psynet") / "templates")),
            DictLoader({"base/layout.html": layout}),
            app.jinja_loader,
        ]
    )
    monkeypatch.setattr(app, "jinja_loader", loader)
    monkeypatch.setattr(app.jinja_env, "loader", loader)
    return app.test_client()


def test_a_browser_tab_of_an_unknown_session_gets_a_short_page(client):
    response = client.get(
        "/timeline?unique_id=gone:gone", headers={"Accept": "text/html"}
    )

    assert response.status_code == 404
    assert "This session is no longer available." in response.text
    assert "researcher" not in response.text
    assert "automatic-early-exit" not in response.text


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

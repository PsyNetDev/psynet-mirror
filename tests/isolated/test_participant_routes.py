"""Security properties of participant-facing routes."""

from importlib import resources
from unittest.mock import MagicMock

import pytest
from dallinger import db
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


def test_responses_send_security_headers(client):
    response = client.get("/start")

    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_a_logged_route_accepts_a_unique_id_that_names_no_participant(client):
    from psynet.experiment import Request

    response = client.get("/start?unique_id=nobody:nobody")

    assert response.status_code == 200
    assert Request.query.filter_by(endpoint="/start").one().unique_id == (
        "nobody:nobody"
    )


@pytest.fixture
def lucid(client, monkeypatch):
    """Make the experiment's recruiter a Lucid recruiter with a fake Lucid API."""
    from psynet.experiment import get_experiment
    from psynet.recruiters import BaseLucidRecruiter

    recruiter = object.__new__(BaseLucidRecruiter)
    recruiter.lucidservice = MagicMock()
    recruiter.lucidservice.generate_submit_url.return_value = "https://lucid.test/"
    monkeypatch.setitem(get_experiment().__dict__, "recruiter", recruiter)
    return recruiter.lucidservice


@pytest.mark.parametrize(
    "query, terminated",
    [
        ("RID=rid", False),
        ("unique_id=rid:rid", False),
        ("RID=rid&unique_id=worker:rid", True),
        ("unique_id=worker:rid", True),
    ],
)
def test_terminating_a_lucid_participant_needs_their_unique_id(
    client, lucid, query, terminated
):
    from psynet.experiment import get_experiment
    from psynet.participant import Participant

    participant = Participant(
        get_experiment(),
        recruiter_id="lucid-recruiter",
        worker_id="worker",
        assignment_id="rid",
        hit_id="rid",
        mode="debug",
    )
    db.session.add(participant)
    db.session.commit()
    response = client.get("/terminate_participant?reason=wrong-browser&" + query)

    assert response.status_code == (200 if terminated else 403)
    assert Participant.query.one().failed is terminated
    assert lucid.terminate_respondent.called is terminated


def test_a_lucid_rid_without_a_participant_can_be_terminated(client, lucid):
    response = client.get("/terminate_participant?reason=mobile-phone&RID=fresh")

    assert response.status_code == 200
    lucid.terminate_respondent.assert_called_once_with("fresh", "mobile-phone", None)

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


@pytest.mark.parametrize("path, status", [("/start", 200), ("/no-such-page", 404)])
def test_responses_send_security_headers(client, path, status):
    response = client.get(path)

    assert response.status_code == status
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_an_experiment_can_allow_framing_in_after_request(client, monkeypatch):
    """The recipe in the changelog works when Dallinger calls it on the class."""
    from dallinger.experiment_server import experiment_server

    import psynet.experiment

    class Exp(psynet.experiment.Experiment):
        @classmethod
        def after_request(cls, request, response):
            response = super().after_request(request, response)
            response.headers.pop("X-Frame-Options", None)
            return response

    monkeypatch.setattr(experiment_server, "exp_klass", Exp)
    response = client.get("/start")

    assert "X-Frame-Options" not in response.headers
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


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
        ("assignmentId=rid", False),
        ("unique_id=rid:rid", True),
        ("RID=rid&unique_id=rid:rid", True),
        ("assignmentId=rid&unique_id=rid:rid", True),
        ("RID=rid&unique_id=rid:missing", False),
        ("assignmentId=rid&RID=other&unique_id=rid:rid", False),
    ],
)
def test_terminating_a_lucid_participant_needs_their_unique_id(
    client, lucid, query, terminated
):
    from psynet.participant import Participant

    _add_lucid_participant()
    response = client.get("/terminate_participant?reason=wrong-browser&" + query)

    assert response.status_code == (200 if terminated else 403)
    assert Participant.query.one().failed is terminated
    assert lucid.terminate_respondent.called is terminated


def test_a_unique_id_with_another_worker_id_is_refused(client, lucid):
    from psynet.participant import Participant

    _add_lucid_participant(worker_id="worker")
    response = client.get("/terminate_participant?reason=wrong-browser&unique_id=x:rid")

    assert response.status_code == 403
    assert not Participant.query.one().failed
    assert not lucid.terminate_respondent.called


def _add_lucid_participant(worker_id=None, rid="rid", progress=0):
    """Add a Lucid participant; like Lucid, the worker ID defaults to the RID."""
    from psynet.experiment import get_experiment
    from psynet.participant import Participant

    participant = Participant(
        get_experiment(),
        recruiter_id="lucid-recruiter",
        worker_id=worker_id or rid,
        assignment_id=rid,
        hit_id=rid,
        mode="debug",
    )
    participant.progress = progress
    db.session.add(participant)
    db.session.commit()


@pytest.mark.parametrize(
    "query, verified", [("RID=rid", False), ("unique_id=rid:rid", True)]
)
def test_a_completed_lucid_participant_needs_their_unique_id(
    client, lucid, query, verified
):
    """A completed participant gets the exit page but is never terminated."""
    from psynet.participant import Participant

    _add_lucid_participant(progress=1)
    response = client.get("/terminate_participant?reason=wrong-browser&" + query)

    assert response.status_code == (200 if verified else 403)
    assert lucid.generate_submit_url.called is verified
    assert not lucid.terminate_respondent.called
    assert not Participant.query.one().failed


def test_a_lucid_rid_shared_by_two_participants_is_refused(client, lucid):
    from psynet.participant import Participant

    _add_lucid_participant()
    _add_lucid_participant(worker_id="other")
    response = client.get("/terminate_participant?reason=wrong-browser&RID=rid")

    assert response.status_code == 500
    assert not any(participant.failed for participant in Participant.query)
    assert not lucid.terminate_respondent.called


def test_terminate_participant_is_not_found_without_lucid(client):
    response = client.get("/terminate_participant?RID=rid")

    assert response.status_code == 404


def test_a_lucid_rid_without_a_participant_can_be_terminated(client, lucid):
    response = client.get("/terminate_participant?reason=mobile-phone&RID=fresh")

    assert response.status_code == 200
    lucid.terminate_respondent.assert_called_once_with("fresh", "mobile-phone", None)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "participant_id=1",
        "unique_id=no-colon",
        "unique_id=worker:",
        "RID=rid&unique_id=bad",
    ],
)
def test_terminating_needs_a_well_formed_lucid_rid(client, lucid, query):
    """The sequential ``participant_id`` cannot select a respondent either."""
    from psynet.participant import Participant

    _add_lucid_participant()
    response = client.get("/terminate_participant?reason=wrong-browser&" + query)

    assert response.status_code == 400
    assert not Participant.query.one().failed
    assert not lucid.terminate_respondent.called

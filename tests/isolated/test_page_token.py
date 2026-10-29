import json
import uuid

import pytest
from dallinger import db
from flask import Flask

from psynet.experiment import get_experiment
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import page_token

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("timeline")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def participant(db_session):
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    participant.page_uuid = str(uuid.uuid4())
    db.session.add(participant)
    db.session.commit()
    return participant


def test_the_participant_json_leaves_out_the_page_token(participant, monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "secret")
    token = page_token(participant.page_uuid)

    shown = json.dumps(participant.__json__(), default=str)

    assert participant.page_uuid in shown
    assert token not in shown


def test_the_page_token_needs_the_secret_key(monkeypatch):
    page_uuid = str(uuid.uuid4())
    monkeypatch.setenv("FLASK_SECRET_KEY", "secret")
    token = page_token(page_uuid)

    assert page_token(str(uuid.uuid4())) != token
    monkeypatch.setenv("FLASK_SECRET_KEY", "another secret")
    assert page_token(page_uuid) != token
    monkeypatch.setenv("FLASK_SECRET_KEY", "")
    assert page_token(page_uuid) is None


def test_a_page_gets_its_token(participant, monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "secret")
    rendered = {}

    def capture(template_string, **template_args):
        rendered.update(template_args)
        return ""

    monkeypatch.setattr("psynet.timeline.render_string_with_translations", capture)

    with Flask(__name__).test_request_context("/timeline"):
        InfoPage("Hello").render(get_experiment(), participant)

    assert rendered["js_vars"]["pageToken"] == page_token(participant.page_uuid)

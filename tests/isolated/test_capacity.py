import uuid
from datetime import datetime, timedelta

import pytest
from dallinger import db
from flask import Flask

from psynet import capacity
from psynet.experiment import Experiment, get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.timeline import Response

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory", [path_to_test_experiment("timeline")], indirect=True
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


def make_participant(joined_min_ago=0, responded_min_ago=None, **kwargs):
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="generic",
        worker_id=str(uuid.uuid4()),
        hit_id="hit",
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    participant.creation_time = datetime.now() - timedelta(minutes=joined_min_ago)
    for key, value in kwargs.items():
        setattr(participant, key, value)
    db.session.add(participant)
    db.session.flush()
    if responded_min_ago is not None:
        response = Response(participant, label="page", page_type="Page")
        response.creation_time = datetime.now() - timedelta(minutes=responded_min_ago)
        db.session.add(response)
        db.session.flush()
    return participant


def test_only_recently_active_working_participants_count(db_session):
    before = capacity.count_active_participants(idle_timeout_s=600)
    make_participant()
    make_participant(joined_min_ago=30, responded_min_ago=1)
    make_participant(joined_min_ago=30)
    make_participant(joined_min_ago=30, responded_min_ago=20)
    make_participant(status="approved")
    make_participant(failed=True)

    assert capacity.count_active_participants(idle_timeout_s=600) == before + 2


def test_newcomers_are_refused_only_while_the_study_is_full(db_session, monkeypatch):
    monkeypatch.setattr(capacity, "_full_until", 0.0)
    experiment = get_experiment()
    experiment.setup_experiment_config()
    experiment.setup_experiment_variables()
    app = Flask(__name__)

    def before_request(path="/participant"):
        with app.test_request_context(path, method="POST"):
            return Experiment.before_request()

    assert before_request() is None
    active = capacity.count_active_participants(idle_timeout_s=600)
    experiment.var.max_concurrent_participants = active + 1
    assert before_request() is None
    make_participant()

    refused = before_request()
    assert refused.status_code == 503
    assert refused.get_json()["error_code"] == "study_full"
    assert refused.headers["Retry-After"]
    assert before_request("/load-participant") is None

    monkeypatch.setattr(capacity, "_full_until", 0.0)
    experiment.var.max_concurrent_participants = active + 2
    assert before_request() is None


class _Limited(Experiment):
    variables = {"max_concurrent_participants": 100}


class _CustomRule(Experiment):
    def accepts_new_participants(self):
        return False


@pytest.mark.parametrize("experiment_class", [_Limited, _CustomRule])
@pytest.mark.parametrize(
    "recruiter, allowed",
    [("generic", True), ("hotair", True), ("prolific", False)],
)
def test_only_open_link_recruiters_accept_a_participant_limit(
    experiment_class, recruiter, allowed
):
    config = {"recruiter": recruiter}

    if allowed:
        experiment_class.check_max_concurrent_participants_support(config)
    else:
        with pytest.raises(RuntimeError, match="initial_recruitment_size"):
            experiment_class.check_max_concurrent_participants_support(config)

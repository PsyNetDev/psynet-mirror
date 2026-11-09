"""SQL budgets for grouped participant requests.

``test_barrier_arrival_queries`` pins the post-commit barrier check. These
tests pin the requests around it, such as arriving at a barrier from a page
(``POST /response``) and the hold poll while waiting. Each compares two group
sizes, so a statement that runs once per member fails. See "Grouped request
budgets" in ``docs/developer/sqlalchemy_performance.rst``.
"""

import json
import sys
from pathlib import Path

import pytest
from dallinger import db
from flask import Flask

from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage, PushButtonControl
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import sqlalchemy_profile
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_hold_helpers import _working_participants  # noqa: E402

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory", [path_to_test_experiment("consents")], indirect=True
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]

_APP = Flask(__name__)

# A request commits several times, and rows it drops from the weak identity
# map in between, such as its sync group, are loaded again on next use. That
# moves a count by a statement or two between runs, so "does not grow" allows
# this much; a statement per member adds at least four between sizes 3 and 7.
_JITTER = 2


def _get(participant_id):
    db.session.remove()
    unique_id = Participant.query.get(participant_id).unique_id
    db.session.remove()
    with _APP.test_request_context(
        f"/timeline?unique_id={unique_id}&mode=json",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert Experiment.route_timeline().status_code == 200


def _post(participant_id, raw_answer=None, *, resume=False):
    db.session.remove()
    page_uuid = Participant.query.get(participant_id).page_uuid
    db.session.remove()
    payload = {
        "participant_id": participant_id,
        "page_uuid": page_uuid,
        "raw_answer": raw_answer,
        "metadata": {"time_taken": 1},
        "include_timeline_fragment": False,
        "timeline_hold_resume": resume,
    }
    with _APP.test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert Experiment.route_response().status_code == 200


def _count(fn):
    db.session.remove()
    with sqlalchemy_profile(db.engine) as profiler:
        fn()
    db.session.remove()
    return profiler.total_count


@pytest.fixture
def exp(db_session, deployment_info):
    experiment = get_experiment()
    original = experiment.timeline
    yield experiment
    experiment.timeline = original


def test_barrier_requests_do_not_grow_with_group_size(exp):
    """Arriving from a page, polling the hold and the last arrival cost the same for 3 and 7."""
    counts = {}
    for group_size in (3, 7):
        db.session.remove()
        exp.timeline = Timeline(
            SimpleGrouper("room", initial_group_size=group_size),
            ModularPage(
                "choose", "Choose", PushButtonControl(["a", "b"]), time_estimate=1
            ),
            GroupBarrier(id_="room_gate", group_type="room"),
            ModularPage("result", "Result", time_estimate=1),
        )
        ids = [p.id for p in _working_participants(exp, group_size)]
        for participant_id in ids:
            _get(participant_id)
        for participant_id in ids[:-1]:
            _post(participant_id, resume=True)
        for participant_id in ids[:-2]:
            _post(participant_id, "a")
        counts[group_size] = {
            "arrival_post": _count(lambda: _post(ids[-2], "a")),
            "hold_poll_post": _count(lambda: _post(ids[0], resume=True)),
            "last_arrival_post": _count(lambda: _post(ids[-1], "a")),
            "released_poll_post": _count(lambda: _post(ids[0], resume=True)),
        }
    grown = {
        key: (counts[3][key], counts[7][key])
        for key in counts[3]
        if counts[7][key] > counts[3][key] + _JITTER
    }
    assert not grown, f"grew with group size: {grown}; all counts: {counts}"

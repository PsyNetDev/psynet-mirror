import json
import sys
import uuid
from pathlib import Path

import pytest
from dallinger import db
from flask import Flask

from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import SimpleGrouper, waiting_status_payload
from psynet.timeline import Response, Timeline

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import _json_timeline, _working_participants  # noqa: E402


def _post_response(participant, **fields):
    payload = {
        "participant_id": participant.id,
        "page_uuid": participant.page_uuid,
        "raw_answer": None,
        "metadata": {"time_taken": 1},
        "include_timeline_fragment": False,
        **fields,
    }
    with Flask(__name__).test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment.route_response()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_release_interrupts_a_waiting_page(in_experiment_directory, db_session):
    exp = get_experiment()
    original = exp.timeline
    exp.timeline = Timeline(
        SimpleGrouper(
            f"pair_{uuid.uuid4().hex[:8]}",
            initial_group_size=2,
            waiting_logic=ModularPage("filler", "A filler question", time_estimate=5),
        ),
        ModularPage("after", "Your partner is here", time_estimate=1),
    )
    try:
        first, last = _working_participants(exp, 2)
        first_id = first.id
        waiting = _json_timeline(exp, first).get_json()["attributes"]["waiting"]
        assert waiting["release_grace_ms"] == 3000
        assert not waiting_status_payload(first.unique_id, waiting["barrier_id"])[
            "released"
        ]

        _json_timeline(exp, last)
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert waiting_status_payload(first.unique_id, waiting["barrier_id"])[
            "released"
        ]

        _post_response(first, interrupted=True)
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert exp.timeline.get_current_elt(exp, first).label == "after"
        filler = Response.query.filter_by(participant_id=first_id, question="filler")
        assert filler.one().metadata["interrupted"] is True
    finally:
        exp.timeline = original

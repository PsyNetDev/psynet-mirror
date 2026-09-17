import json
import re
import uuid
from types import SimpleNamespace

import pytest
from dallinger import db
from flask import Flask
from sqlalchemy import inspect

from psynet.exit import (
    EarlyExitConfirmation,
    ExitContext,
    ExitPath,
    ExitPlan,
    PaymentState,
)
from psynet.experiment import Experiment, get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sqlalchemy_profiling import assert_query_count
from psynet.timeline import ModuleState

pytestmark = [
    pytest.mark.parametrize(
        "experiment_directory",
        [path_to_test_experiment("timeline")],
        indirect=True,
    ),
    pytest.mark.usefixtures("in_experiment_directory"),
]


@pytest.fixture
def participant_with_module_state(db_session):
    experiment = get_experiment()
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    state = ModuleState(SimpleNamespace(id="navigation"), participant)
    state.start()
    participant.module_state = state
    db.session.add_all([participant, state])
    db.session.commit()
    unique_id = participant.unique_id
    db.session.remove()
    return unique_id


def test_exit_plan_persists_and_rolls_back(db_session):
    experiment = get_experiment()
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    plan = ExitPlan.create(
        context=ExitContext.VOLUNTARY,
        path=ExitPath.END_SESSION,
        payment=None,
        payment_state=PaymentState.NOT_APPLICABLE,
        confirmation=EarlyExitConfirmation(
            title="Leave?",
            message="Responses saved.",
            confirm_label="Leave",
            cancel_label="Continue",
        ),
    )
    participant.exit_plan = plan.to_dict()
    db.session.add(participant)
    db.session.commit()
    participant_id = participant.id
    db.session.remove()

    reloaded = Participant.query.get(participant_id)
    assert ExitPlan.from_dict(reloaded.exit_plan) == plan

    reloaded.exit_plan = plan.mark_committed().to_dict()
    db.session.flush()
    db.session.rollback()
    db.session.remove()
    assert Participant.query.get(participant_id).exit_plan == plan.to_dict()


def test_participant_request_query_loads_relationships_only_when_used(
    db_session, participant_with_module_state
):
    experiment = get_experiment()

    with assert_query_count(min_queries=1, max_queries=1):
        participant = experiment._get_request_participant_from_unique_id(
            participant_with_module_state
        )

    # Request queries override collection-oriented select-in defaults. These
    # relationships remain available and each loads normally on first access.
    with assert_query_count(min_queries=1, max_queries=1):
        assert participant.module_state.module_id == "navigation"
    with assert_query_count(min_queries=1, max_queries=1):
        assert [state.module_id for state in participant._module_states] == [
            "navigation"
        ]
    with assert_query_count(min_queries=1, max_queries=1):
        assert participant.active_barriers == {}


def test_locked_request_query_keeps_relationships_unloaded(
    db_session, participant_with_module_state
):
    """Cover the locking participant load used by ``/response``."""
    experiment = get_experiment()
    participant_id = (
        experiment._get_request_participant_from_unique_id(
            participant_with_module_state
        )
    ).id

    # ``process_response`` combines the request query with row locking and
    # ``populate_existing()``. Loader options are not always honored by
    # ``Query.get()``, so assert this construct keeps them.
    with assert_query_count(min_queries=1, max_queries=1):
        participant = (
            experiment._participant_request_query()
            .with_for_update(of=Participant)
            .populate_existing()
            .get(participant_id)
        )

    unloaded = inspect(participant).unloaded
    assert {"module_state", "_module_states", "active_barriers"} <= unloaded

    with assert_query_count(min_queries=1, max_queries=1):
        assert participant.module_state.module_id == "navigation"


def test_locked_unique_id_request_query_keeps_relationships_unloaded(
    db_session, participant_with_module_state
):
    """Cover the locking unique-id load used by ``/timeline``."""
    experiment = get_experiment()
    with assert_query_count(min_queries=1, max_queries=1):
        participant = experiment._get_request_participant_from_unique_id(
            participant_with_module_state, for_update=True
        )

    unloaded = inspect(participant).unloaded
    assert {"module_state", "_module_states", "active_barriers"} <= unloaded

    with assert_query_count(min_queries=1, max_queries=1):
        assert participant.module_state.module_id == "navigation"


def test_public_participant_getter_retains_eager_relationships_when_detached(
    db_session, participant_with_module_state
):
    experiment = get_experiment()
    participant = experiment.get_participant_from_unique_id(
        participant_with_module_state
    )
    db.session.expunge(participant)

    # Public getters can be used outside request transactions, so preserve
    # their historical select-in loading behavior.
    with assert_query_count(max_queries=0):
        assert participant.module_state.module_id == "navigation"
        assert [state.module_id for state in participant._module_states] == [
            "navigation"
        ]
        assert participant.active_barriers == {}


@pytest.fixture
def request_participant(db_session):
    experiment = get_experiment()
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id=str(uuid.uuid4()),
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    db.session.commit()
    unique_id = participant.unique_id
    db.session.remove()
    return unique_id


_REQUEST_APP = Flask(__name__)


def _timeline_request(unique_id):
    return _REQUEST_APP.test_request_context(
        f"/timeline?unique_id={unique_id}&mode=json",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )


def _response_request(payload):
    return _REQUEST_APP.test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )


def _table_query_count(profiler, table):
    table_pattern = re.compile(
        rf'\b(?:from|join)\s+(?:"?\w+"?\.)?"?{re.escape(table)}"?\b',
        re.IGNORECASE,
    )
    return sum(
        stat.count
        for stat in profiler.get_stats(top_n=None)
        if table_pattern.search(stat.statement)
    )


def test_timeline_handler_skips_unused_participant_relationships(
    db_session, request_participant
):
    """Reload ``/timeline`` without select-in loading unused relationships.

    The first request advances onto consent and may create a module state.
    The reload is the regression check: a public participant getter would still
    issue select-in queries for barriers and the full module-state collection.
    """
    experiment = get_experiment()
    unique_id = request_participant

    with _timeline_request(unique_id):
        first = experiment.route_timeline()
    assert first.status_code == 200
    db.session.remove()

    with _timeline_request(unique_id):
        # Write/commit/read-only render plus SET LOCAL lock_timeout. The table
        # assertions below are the unused-relationship regression check.
        # One extra statement is the arrival-websocket membership EXISTS.
        with assert_query_count(min_queries=1, max_queries=7) as profiler:
            second = experiment.route_timeline()
    assert second.status_code == 200
    assert json.loads(second.get_data())["attributes"]["unique_id"] == unique_id
    assert _table_query_count(profiler, "participant_link_barrier") == 0
    assert _table_query_count(profiler, "participant_link_sync_group") <= 1
    assert _table_query_count(profiler, "module_state") == 0
    timing = second.headers.get("Server-Timing", "")
    assert "lock;dur=" in timing
    assert "page;dur=" in timing
    assert "barriers;dur=" in timing
    assert "render;dur=" in timing
    assert "app;dur=" in timing


def test_response_handler_skips_unused_participant_relationships(
    db_session, request_participant
):
    """POST ``/response`` should keep unused participant relationships lazy."""
    experiment = get_experiment()
    unique_id = request_participant

    with _timeline_request(unique_id):
        first = experiment.route_timeline()
    assert first.status_code == 200

    participant = Participant.query.filter_by(unique_id=unique_id).one()
    payload = {
        "participant_id": participant.id,
        "page_uuid": participant.page_uuid,
        "raw_answer": True,
        "metadata": {"time_taken": 1},
        "include_timeline_fragment": False,
    }
    db.session.remove()

    with _response_request(payload):
        # One extra statement is the memoized arrival-websocket membership EXISTS.
        with assert_query_count(max_queries=13) as profiler:
            result = experiment.route_response()
    assert result.status_code == 200
    body = json.loads(result.get_data())
    assert body["status"] == "success"
    assert body["submission"] == "approved"
    assert _table_query_count(profiler, "participant_link_barrier") == 0
    assert _table_query_count(profiler, "participant_link_sync_group") <= 1
    assert _table_query_count(profiler, "module_state") <= 2
    timing = result.headers.get("Server-Timing", "")
    assert "app;dur=" in timing
    assert "process;dur=" in timing
    assert "barriers;dur=" in timing
    assert "render;dur=" in timing


def test_timeline_redirects_finished_participants_to_the_exit_page(
    db_session, request_participant
):
    """Back from the exit page must not revive a finished participant's timeline."""
    from datetime import datetime

    experiment = get_experiment()
    unique_id = request_participant
    participant = Participant.query.filter_by(unique_id=unique_id).one()
    participant.complete = True
    participant.progress = 1.0
    participant.end_time = datetime.now()
    db.session.commit()
    participant_id = participant.id
    db.session.remove()

    with _timeline_request(unique_id):
        response = experiment.route_timeline()

    assert response.status_code in (301, 302)
    assert (
        f"/recruiter-exit?participant_id={participant_id}"
        in response.headers["Location"]
    )


def test_timeline_does_not_redirect_before_successful_end_logic(
    db_session, request_participant
):
    """Progress reaches one before the successful end branch marks completion."""
    experiment = get_experiment()
    unique_id = request_participant
    participant = Participant.query.filter_by(unique_id=unique_id).one()
    participant.complete = False
    participant.progress = 1.0
    db.session.commit()
    db.session.remove()

    with _timeline_request(unique_id):
        response = experiment.route_timeline()

    assert response.status_code == 200
    assert json.loads(response.get_data())["attributes"]["unique_id"] == unique_id


def test_server_timing_header_formats_phases():
    header = Experiment._server_timing_header(
        {"process": 12.34, "barriers": 0.0, "app": 100}
    )
    assert "process;dur=12.3" in header
    assert "barriers;dur=0.0" in header
    assert "app;dur=100.0" in header

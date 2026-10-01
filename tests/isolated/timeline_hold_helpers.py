"""Shared helpers for stacked-hold and timeline-hold protocol tests.

This module is not named ``test_*.py`` so isolated CI does not collect it as
an empty test file. Import it from the ``tests/isolated`` directory.
"""

import json
import threading
import uuid
from contextlib import contextmanager

from dallinger import db
from dallinger.models import timenow
from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from psynet.experiment import Experiment
from psynet.modular_page import ModularPage
from psynet.participant import Participant
from psynet.sync import GroupBarrier, SimpleGrouper
from psynet.timeline import Timeline
from psynet.timeline_hold import TimelineHoldRecord


def new_participant(experiment):
    """Create and add a debug HotAir participant without committing."""
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id="XYZ",
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    db.session.add(participant)
    return participant


def _stacked_partner_timeline(
    group_type, group_size=2, hold_content="Waiting for your partner"
):
    """RPS-like grouper plus two entry barriers before the first action page."""
    return Timeline(
        SimpleGrouper(
            group_type=group_type,
            initial_group_size=group_size,
            content=hold_content,
        ),
        GroupBarrier(
            id_=f"{group_type}_init",
            group_type=group_type,
            content=hold_content,
        ),
        GroupBarrier(
            id_=f"{group_type}_prepare",
            group_type=group_type,
            content=hold_content,
        ),
        ModularPage("choose_action", "Choose your action", time_estimate=1),
    )


@contextmanager
def _using_stacked_timeline(exp, group_type, **kwargs):
    """Install a stacked partner timeline on ``exp`` for the duration of the block."""
    original = exp.timeline
    exp.timeline = _stacked_partner_timeline(group_type, **kwargs)
    try:
        yield
    finally:
        exp.timeline = original


def _json_timeline(exp, participant):
    """Run ``GET /timeline?mode=json`` for ``participant`` in a request context."""
    with Flask(__name__).test_request_context(
        f"/timeline?unique_id={participant.unique_id}",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment._route_timeline(exp, participant, mode="json")


def _json_timeline_via_route(participant):
    """Run ``GET /timeline?mode=json`` through the busy-503 wrapper."""
    with Flask(__name__).test_request_context(
        f"/timeline?unique_id={participant.unique_id}&mode=json",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment.route_timeline()


def _process_response(exp, participant, page_uuid, *, timeline_hold_resume=False):
    """Run ``process_response`` for ``participant`` in a request context."""
    with Flask(__name__).test_request_context(
        "/response",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return exp.process_response(
            participant.id,
            None,
            {},
            {},
            page_uuid,
            "127.0.0.1",
            timeline_hold_resume=timeline_hold_resume,
        )


def _route_approved_response(participant, *, raw_answer=True):
    """POST ``/response`` as an ordinary Next, including last-arrival finalize."""
    payload = {
        "participant_id": participant.id,
        "page_uuid": participant.page_uuid,
        "raw_answer": raw_answer,
        "metadata": {"time_taken": 1},
        "include_timeline_fragment": False,
    }
    with Flask(__name__).test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment.route_response()


def _working_participants(exp, count):
    """Create ``count`` working participants for stacked-hold arrival tests."""
    participants = [new_participant(exp) for _ in range(count)]
    for participant in participants:
        participant.status = "working"
    db.session.commit()
    return participants


def _json_hold_is_silent(payload):
    """Return whether a JSON timeline page is a silent catch-up hold."""
    attributes = (payload or {}).get("attributes") or {}
    hold = attributes.get("timeline_hold") or {}
    return hold.get("silent") is True


def _assert_cursor_unchanged(participant_id, page_uuid):
    """This participant must still be on the given hold page uuid."""
    db.session.expire_all()
    participant = Participant.query.get(participant_id)
    assert participant.page_uuid == page_uuid


def _assert_left_hold_uuid(participant_id, page_uuid):
    """This participant must have left the given hold page uuid."""
    db.session.expire_all()
    participant = Participant.query.get(participant_id)
    assert participant.page_uuid != page_uuid


def _assert_on_action_page(exp, participant_ids):
    """Every listed participant must have left the hold for ``choose_action``."""
    db.session.expire_all()
    groups = []
    for participant_id in participant_ids:
        participant = Participant.query.get(participant_id)
        page = exp.timeline.get_current_elt(exp, participant)
        assert not getattr(page, "is_timeline_hold", False)
        assert page.label == "choose_action"
        assert participant.sync_group is not None
        groups.append(participant.sync_group.id)
    assert len(set(groups)) == 1


def _catch_up_until_action(exp, participant_ids, *, rounds=20):
    """Advance each participant on their own GET until the action page."""
    participant_ids = list(participant_ids)
    for _ in range(rounds):
        db.session.expire_all()
        remaining = []
        for participant_id in participant_ids:
            participant = Participant.query.get(participant_id)
            page = exp.timeline.get_current_elt(exp, participant)
            if getattr(page, "label", None) != "choose_action":
                remaining.append(participant)
        if not remaining:
            _assert_on_action_page(exp, participant_ids)
            return
        for participant in remaining:
            assert _json_timeline(exp, participant).status_code == 200
    _assert_on_action_page(exp, participant_ids)


def _participant_row_is_locked(participant_id):
    """Return whether another connection holds ``FOR UPDATE`` on this participant."""
    with db.engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text("SELECT id FROM participant WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": participant_id},
            )
        except OperationalError as err:
            if getattr(getattr(err, "orig", None), "pgcode", None) == "55P03":
                return True
            raise
        else:
            return False
        finally:
            trans.rollback()


@contextmanager
def _lock_participant_row(participant_id):
    """Hold ``FOR UPDATE`` on ``participant_id`` from an extra connection."""
    conn = db.engine.connect()
    trans = conn.begin()
    try:
        conn.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": participant_id},
        )
        yield
    finally:
        if trans.is_active:
            trans.rollback()
        conn.close()


def _route_timeline_via_route_in_thread(unique_id):
    """Run ``route_timeline`` on a thread-local session and request context."""
    result = {}
    errors = []

    def target():
        try:
            participant = Participant.query.filter_by(unique_id=unique_id).one()
            response = _json_timeline_via_route(participant)
            result["status"] = response.status_code
            payload = response.get_json()
            result["payload"] = payload
            attributes = (payload or {}).get("attributes") or {}
            result["type"] = attributes.get("type")
        except Exception as err:  # pragma: no cover - surfaced by the caller
            errors.append(err)
        finally:
            db.session.remove()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result, errors


def _hold_wake_publications(monkeypatch):
    """Capture Redis hold-wake publishes as ``(channel, payload)`` pairs."""
    publications = []
    monkeypatch.setattr(
        db.redis_conn,
        "publish",
        lambda channel_name, data: publications.append(
            (channel_name, json.loads(data))
        ),
    )
    return publications


def _released_wake_count(publications):
    """Count committed barrier-release wakes in captured Redis publishes."""
    return sum(
        1
        for _, payload in publications
        for target in payload.get("targets", [])
        if target.get("reason") == "barrier_released"
    )


def _barrier_link_released(participant_id, barrier_id):
    """Return whether this participant's link to ``barrier_id`` is released."""
    with db.engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT released
                FROM participant_link_barrier
                WHERE participant_id = :participant_id
                  AND barrier_id = :barrier_id
                """
            ),
            {"participant_id": participant_id, "barrier_id": barrier_id},
        ).scalar()


def _participant_hold(participant, page_uuid, hold_id):
    """Attach one unresumed hold so a wake can be queued for ``participant``."""
    participant.page_uuid = page_uuid
    hold = TimelineHoldRecord(
        participant=participant,
        page_uuid=page_uuid,
        hold_id=hold_id,
        started_at=timenow(),
        expected_wait=1,
        max_wait_time=20,
        fix_time_credit=False,
    )
    db.session.add(hold)
    db.session.flush()
    return hold

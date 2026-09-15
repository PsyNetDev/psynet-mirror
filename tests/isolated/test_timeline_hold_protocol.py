"""Reachable-state witnesses for the timeline-hold lock and pin protocol.

These tests pause at transaction boundaries and assert HTTP/first-paint
outcomes. They do not monkeypatch ``is_ready_to_resume``, and they do not
treat a ready overlay on an unreleased ``active_barriers`` link as a
protocol witness. See ``docs/developer/timeline_hold_traces.rst``.
"""

import json
import threading
import uuid
from contextlib import contextmanager

import pytest
from dallinger import db
from dallinger.models import timenow
from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    GroupBarrier,
    SimpleGrouper,
    _hold_instance_id_for_page,
    _hold_visit_pinned_by_last_arrival,
    _run_pending_barrier_checks,
    check_barriers,
)
from psynet.timeline import Timeline
from psynet.timeline_hold import (
    TimelineHoldRecord,
    _last_arrival_follow_in_progress,
    _last_arrival_render_gate,
    _last_arrival_render_key,
    _mark_last_arrival_render_instance,
    _parked_hold_wake_key,
    _publish_wakes,
)

CONSENTS = pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("consents")],
    indirect=True,
)


def _new_participant(experiment):
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


def _stacked_partner_timeline(group_type, group_size=2):
    """RPS-like grouper plus two entry barriers before the first action page."""
    hold_content = "Waiting for your partner"
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


def _working_participants(exp, count):
    participants = [_new_participant(exp) for _ in range(count)]
    for participant in participants:
        participant.status = "working"
    db.session.commit()
    return participants


def _assert_on_action_page(exp, participant_ids):
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
    return sum(
        1
        for _, payload in publications
        for target in payload.get("targets", [])
        if target.get("reason") == "barrier_released"
    )


def _track_barrier_check_claims(monkeypatch):
    """Record ``_run_pending_barrier_checks`` results without changing behavior."""
    claimed = []
    original = _run_pending_barrier_checks

    def tracking(instance_ids, **kwargs):
        result = original(instance_ids, **kwargs)
        claimed.append(result)
        return result

    monkeypatch.setattr("psynet.sync._run_pending_barrier_checks", tracking)
    return claimed


def _current_hold_instance_id(participant):
    return next(iter(participant.active_barriers.values())).barrier_instance_id


@CONSENTS
def test_both_nowait_misses_first_paint_live_hold_not_503(
    in_experiment_directory, db_session, monkeypatch
):
    """T7: two waiter ``NOWAIT`` misses first-paint the live hold, not HTTP 503.

    The extra connection holds the waiter's row through both check attempts.
    After that lock drops, the poller finishes the skip.
    """
    exp = get_experiment()
    group_type = f"t7_both_miss_{uuid.uuid4().hex[:8]}"
    with _using_stacked_timeline(exp, group_type):
        first, last = _working_participants(exp, 2)
        first_id, last_id = first.id, last.id
        last_uid = last.unique_id
        assert _json_timeline(exp, first).status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first_id)
        last = Participant.query.get(last_id)
        page = exp.timeline.get_current_elt(exp, first)
        assert getattr(page, "is_timeline_hold", False)
        hold_uuid = first.page_uuid
        assert (
            TimelineHoldRecord.query.filter_by(
                participant_id=first_id, page_uuid=hold_uuid
            ).one()
            is not None
        )
        claimed = _track_barrier_check_claims(monkeypatch)
        with _lock_participant_row(first_id):
            assert _participant_row_is_locked(first_id)
            last = Participant.query.filter_by(unique_id=last_uid).one()
            last_response = _json_timeline_via_route(last)
            assert claimed == [False, False]
            assert last_response.status_code == 200
            payload = last_response.get_json() or {}
            assert (payload.get("attributes") or {}).get("type") != "ModularPage"
            db.session.expire_all()
            last = Participant.query.get(last_id)
            first = Participant.query.get(first_id)
            assert getattr(
                exp.timeline.get_current_elt(exp, last), "is_timeline_hold", False
            )
            assert getattr(
                exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
            )
        check_barriers()
        _catch_up_until_action(exp, [first_id, last_id])


@CONSENTS
@pytest.mark.parametrize("settle_how", ["fail", "pending_redirect"])
def test_fail_or_redirect_hold_resume_settles_under_live_follow_pin(
    in_experiment_directory, db_session, monkeypatch, settle_how
):
    """I5: fail and ``pending_redirect`` settle even while a follow pin is live.

    Last-arrival is paused after the arrival commit and follow pin, before
    the check can release. The overlay looks ready because of fail/redirect,
    not because ``active_barriers`` dropped the link.
    """
    exp = get_experiment()
    group_type = f"i5_{settle_how}_{uuid.uuid4().hex[:8]}"
    original_finalize = Experiment._finalize_pending_timeline_barriers
    entered = threading.Event()
    may_finish = threading.Event()

    @classmethod
    def pausing_finalize(cls, experiment, participant, page):
        entered.set()
        assert may_finish.wait(timeout=10)
        return original_finalize(experiment, participant, page)

    monkeypatch.setattr(
        Experiment, "_finalize_pending_timeline_barriers", pausing_finalize
    )
    with _using_stacked_timeline(exp, group_type):
        first, last = _working_participants(exp, 2)
        first_id, last_id = first.id, last.id
        last_uid = last.unique_id
        assert _json_timeline(exp, first).status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first_id)
        hold_uuid = first.page_uuid
        instance_id = _current_hold_instance_id(first)
        page = exp.timeline.get_current_elt(exp, first)
        assert not page.is_ready_to_resume(exp, first)
        assert _hold_instance_id_for_page(first, page) == instance_id
        thread, result, errors = _route_timeline_via_route_in_thread(last_uid)
        try:
            assert entered.wait(timeout=10)
            db.session.expire_all()
            first = Participant.query.get(first_id)
            page = exp.timeline.get_current_elt(exp, first)
            assert _last_arrival_follow_in_progress(instance_id)
            assert _hold_visit_pinned_by_last_arrival(first)
            assert _hold_instance_id_for_page(first, page) == instance_id
            assert not page.is_ready_to_resume(exp, first)
            if settle_how == "fail":
                first.fail("protocol_suite")
            else:
                first.pending_redirect = "unsuccessful_end"
            db.session.commit()
            db.session.expire_all()
            first = Participant.query.get(first_id)
            page = exp.timeline.get_current_elt(exp, first)
            assert page.is_ready_to_resume(exp, first)
            assert _hold_instance_id_for_page(first, page) == instance_id
            assert _hold_visit_pinned_by_last_arrival(first)
            resumed = _process_response(
                exp, first, hold_uuid, timeline_hold_resume=True
            )
            assert not getattr(resumed, "skip_write", False)
            db.session.commit()
            record = TimelineHoldRecord.query.filter_by(
                participant_id=first_id, page_uuid=hold_uuid
            ).one()
            assert record.resumed_at is not None
        finally:
            may_finish.set()
            thread.join(timeout=10)
        assert errors == []
        assert result.get("status") == 200
        assert not _participant_row_is_locked(first_id)
        assert not _participant_row_is_locked(last_id)


@CONSENTS
def test_overlapping_render_pin_owners_publish_wake_once(
    in_experiment_directory, db_session, monkeypatch
):
    """T8: the last overlapping render-pin owner drains a parked wake once."""
    participant = _new_participant(get_experiment())
    participant.status = "working"
    participant.page_uuid = "overlap-pin"
    hold = TimelineHoldRecord(
        participant=participant,
        page_uuid="overlap-pin",
        hold_id="overlap",
        started_at=timenow(),
        expected_wait=1,
        max_wait_time=20,
        fix_time_credit=False,
    )
    db.session.add(hold)
    db.session.commit()
    publications = _hold_wake_publications(monkeypatch)
    instance_id = f"overlap-{uuid.uuid4().hex}"
    wake = {
        "participant_id": participant.id,
        "reason": "barrier_released",
        "wake_token": hold.wake_token,
        "instance_id": instance_id,
    }
    a_pinned = threading.Event()
    b_pinned = threading.Event()
    a_may_exit = threading.Event()
    b_may_exit = threading.Event()
    errors = []

    def owner(pinned, may_exit):
        try:
            with _last_arrival_render_gate():
                _mark_last_arrival_render_instance(instance_id)
                pinned.set()
                assert may_exit.wait(timeout=5)
        except Exception as err:  # pragma: no cover - surfaced by the caller
            errors.append(err)

    thread_a = threading.Thread(target=owner, args=(a_pinned, a_may_exit), daemon=True)
    thread_b = threading.Thread(target=owner, args=(b_pinned, b_may_exit), daemon=True)
    thread_a.start()
    thread_b.start()
    try:
        assert a_pinned.wait(timeout=5)
        assert b_pinned.wait(timeout=5)
        assert int(db.redis_conn.get(_last_arrival_render_key(instance_id))) == 2
        _publish_wakes([dict(wake)])
        assert _released_wake_count(publications) == 0
        assert db.redis_conn.llen(_parked_hold_wake_key(instance_id)) == 1
        a_may_exit.set()
        thread_a.join(timeout=5)
        assert not thread_a.is_alive()
        assert int(db.redis_conn.get(_last_arrival_render_key(instance_id))) == 1
        assert _released_wake_count(publications) == 0
        b_may_exit.set()
        thread_b.join(timeout=5)
        assert not thread_b.is_alive()
    finally:
        a_may_exit.set()
        b_may_exit.set()
    assert errors == []
    assert _released_wake_count(publications) == 1
    assert not db.redis_conn.llen(_parked_hold_wake_key(instance_id))
    assert db.redis_conn.get(_last_arrival_render_key(instance_id)) is None

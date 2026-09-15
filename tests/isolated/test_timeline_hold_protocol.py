"""Reachable-state witnesses for the timeline-hold lock and pin protocol.

The GET/POST tests pause at transaction boundaries and assert HTTP and
first-paint outcomes. They do not monkeypatch ``is_ready_to_resume``, and
they do not treat a ready overlay on an unreleased ``active_barriers``
link as a protocol witness. ``test_overlapping_render_pin_owners_publish_wake_once``
is a Lua/owner-token witness: it drives Redis pins directly. See
``docs/developer/timeline_hold_traces.rst``.
"""

import sys
import threading
import uuid
from pathlib import Path

import pytest
from dallinger import db

from psynet.experiment import Experiment, get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.sync import (
    _hold_instance_id_for_page,
    _hold_visit_pinned_by_last_arrival,
    _run_pending_barrier_checks,
    check_barriers,
)
from psynet.timeline_hold import (
    TimelineHoldRecord,
    _last_arrival_follow_in_progress,
    _last_arrival_render_gate,
    _last_arrival_render_key,
    _mark_last_arrival_render_instance,
    _parked_hold_wake_key,
    _publish_wakes,
)

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import (  # noqa: E402
    _assert_on_action_page,
    _barrier_link_released,
    _hold_wake_publications,
    _json_timeline,
    _json_timeline_via_route,
    _lock_participant_row,
    _participant_row_is_locked,
    _process_response,
    _released_wake_count,
    _route_timeline_via_route_in_thread,
    _using_stacked_timeline,
    _working_participants,
)

CONSENTS = pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("consents")],
    indirect=True,
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


@CONSENTS
def test_both_nowait_misses_first_paint_live_hold_not_503(
    in_experiment_directory, db_session, monkeypatch
):
    """T7: waiter ``NOWAIT`` misses first-paint the live hold, not HTTP 503.

    The extra connection holds the waiter's row through every check attempt.
    After that lock drops, ``check_barriers()`` must finish the skip without a
    catch-up GET.
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
        barrier_id = page.barrier_id
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
            assert all(flag is False for flag in claimed)
            assert len(claimed) >= 2
            assert last_response.status_code == 200
            payload = last_response.get_json() or {}
            assert payload["attributes"]["type"] == "_BarrierHoldPage"
            db.session.expire_all()
            last = Participant.query.get(last_id)
            first = Participant.query.get(first_id)
            assert getattr(
                exp.timeline.get_current_elt(exp, last), "is_timeline_hold", False
            )
            assert getattr(
                exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
            )
            assert _barrier_link_released(first_id, barrier_id) is False
            assert _barrier_link_released(last_id, barrier_id) is False
        check_barriers()
        _assert_on_action_page(exp, [first_id, last_id])


@CONSENTS
@pytest.mark.parametrize("settle_how", ["fail", "pending_redirect"])
def test_fail_or_redirect_hold_resume_settles_under_live_follow_pin(
    in_experiment_directory, db_session, monkeypatch, settle_how
):
    """I5: fail and ``pending_redirect`` settle even while a follow pin is live.

    Last-arrival is paused after the arrival commit and follow pin, before
    the check can release. The overlay looks ready because of fail/redirect,
    not because ``active_barriers`` dropped the link. The follow pin TTL is
    15 s and is not refreshed while last-arrival is parked here; keep this
    window well under that.
    """
    exp = get_experiment()
    group_type = f"i5_{settle_how}_{uuid.uuid4().hex[:8]}"
    original_finalize = Experiment._finalize_pending_timeline_barriers
    entered = threading.Event()
    may_finish = threading.Event()
    with _using_stacked_timeline(exp, group_type):
        first, last = _working_participants(exp, 2)
        first_id, last_id = first.id, last.id
        last_uid = last.unique_id

        @classmethod
        def pausing_finalize(cls, experiment, participant, page):
            if participant.id == last_id:
                entered.set()
                assert may_finish.wait(timeout=10)
            return original_finalize(experiment, participant, page)

        monkeypatch.setattr(
            Experiment, "_finalize_pending_timeline_barriers", pausing_finalize
        )
        assert _json_timeline(exp, first).status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first_id)
        hold_uuid = first.page_uuid
        page = exp.timeline.get_current_elt(exp, first)
        instance_id = _hold_instance_id_for_page(first, page)
        assert instance_id
        assert not page.is_ready_to_resume(exp, first)
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
    """T8 Lua: the last overlapping render-pin owner drains a parked wake once.

    This drives the last-arrival gate and ``_publish_wakes`` on a fabricated
    instance id. It is not a reachable GET witness.
    """
    publications = _hold_wake_publications(monkeypatch)
    instance_id = f"overlap-{uuid.uuid4().hex}"
    wake = {
        "participant_id": 0,
        "reason": "barrier_released",
        "wake_token": "lua-overlap-token",
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
        assert db.redis_conn.scard(_last_arrival_render_key(instance_id)) == 2
        _publish_wakes([dict(wake)])
        assert _released_wake_count(publications) == 0
        assert db.redis_conn.llen(_parked_hold_wake_key(instance_id)) == 1
        a_may_exit.set()
        thread_a.join(timeout=5)
        assert not thread_a.is_alive()
        assert db.redis_conn.scard(_last_arrival_render_key(instance_id)) == 1
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
    assert not db.redis_conn.exists(_last_arrival_render_key(instance_id))


@CONSENTS
def test_stale_render_pin_owner_does_not_drop_newer_generation(
    in_experiment_directory, db_session, monkeypatch
):
    """A live owner whose pin expired must not unpin a later generation."""
    publications = _hold_wake_publications(monkeypatch)
    instance_id = f"ttl-gen-{uuid.uuid4().hex}"
    wake = {
        "participant_id": 0,
        "reason": "barrier_released",
        "wake_token": "lua-ttl-gen-token",
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
    try:
        assert a_pinned.wait(timeout=5)
        db.redis_conn.delete(_last_arrival_render_key(instance_id))
        thread_b.start()
        assert b_pinned.wait(timeout=5)
        assert db.redis_conn.scard(_last_arrival_render_key(instance_id)) == 1
        _publish_wakes([dict(wake)])
        assert _released_wake_count(publications) == 0
        a_may_exit.set()
        thread_a.join(timeout=5)
        assert not thread_a.is_alive()
        assert db.redis_conn.scard(_last_arrival_render_key(instance_id)) == 1
        assert _released_wake_count(publications) == 0
        b_may_exit.set()
        thread_b.join(timeout=5)
        assert not thread_b.is_alive()
    finally:
        a_may_exit.set()
        b_may_exit.set()
    assert errors == []
    assert _released_wake_count(publications) == 1
    assert not db.redis_conn.exists(_last_arrival_render_key(instance_id))

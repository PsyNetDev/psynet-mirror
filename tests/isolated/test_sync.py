import json
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from dallinger import db
from dallinger.experiment_server import sockets
from dallinger.models import timenow
from dominate import tags
from flask import Flask
from sqlalchemy import Column, String, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

import psynet.bot
import psynet.sync
from psynet.async_job import LocalAsyncJob, WorkerAsyncJob
from psynet.barrier_spec import (
    BarrierSpecError,
    barrier_from_spec_json,
    barrier_spec_json,
)
from psynet.bot import make_late_now
from psynet.dashboard.sync_groups import (
    _fail_sync_group_participant,
    _get_grouper_progress,
    _index_waiting_barriers,
    _kick_sync_group_participant,
    _summarize_waiting_at_barriers,
)
from psynet.data import SQLBase
from psynet.db import _set_transaction_lock_timeout, transaction
from psynet.experiment import Experiment, get_experiment
from psynet.modular_page import ModularPage
from psynet.page import InfoPage, WaitPage, wait_while
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.serialize import SerializedCallable
from psynet.sqlalchemy_profiling import assert_query_count
from psynet.sync import (
    _BARRIER_FROM_SPEC_CACHE_KEY,
    _HAS_ACTIVE_SYNC_GROUP_ATTR,
    Barrier,
    BarrierDefinition,
    BarrierInstance,
    GroupBarrier,
    ParticipantLinkBarrier,
    ParticipantLinkSyncGroup,
    SimpleGrouper,
    SimpleSyncGroup,
    SyncGroup,
    _advance_released_hold_waiters_after_commit,
    _check_and_skip_held_instance,
    _check_claimed_barrier_instance,
    _check_held_instance,
    _claim_barrier_instance,
    _group_barrier_outcome,
    _has_active_sync_group,
    _hold_barrier_instance_claim,
    _hold_instance_id_for_page,
    _pending_checks_should_wait_for_claim,
    _process_barrier_instance,
    _queue_barrier_check,
    _queue_released_hold_waiters,
    _removed_from_group,
    _removed_from_group_notice,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
    _take_released_hold_waiter_ids,
    _visit_check_would_release,
    arrival_notice_payload,
    check_barriers,
    check_sync_groups,
    group_seats,
    hold_message,
    leave_group,
    pending_arrival_notice_for,
)
from psynet.timeline import (
    CodeBlock,
    Page,
    PageMaker,
    Response,
    Timeline,
)
from psynet.timeline_hold import (
    TimelineHoldRecord,
    _defer_timeline_hold_wakes,
    _enqueue_timeline_hold_wake,
    _queue_arrival_update,
    _timeline_hold_channel,
    _TimelineHoldPage,
    default_group_barrier_arrival_message,
    default_hold_progress,
)
from psynet.trial.main import _edit_group_runs
from psynet.trial.static import StaticTrialMaker
from psynet.utils import call_function_with_context, get_config

_ISOLATED_DIR = Path(__file__).resolve().parent
if str(_ISOLATED_DIR) not in sys.path:
    sys.path.insert(0, str(_ISOLATED_DIR))
from timeline_hold_helpers import (  # noqa: E402
    _assert_cursor_unchanged,
    _assert_left_hold_uuid,
    _assert_on_action_page,
    _barrier_link_released,
    _catch_up_until_action,
    _hold_wake_publications,
    _json_hold_is_silent,
    _json_timeline,
    _lock_participant_row,
    _participant_hold,
    _participant_row_is_locked,
    _process_response,
    _released_wake_count,
    _route_approved_response,
    _route_timeline_via_route_in_thread,
    _stacked_partner_timeline,
    _working_participants,
    new_participant,
)


def get_random_id():
    return str(uuid.uuid4())


def async_job_noop():
    return None


processed_barriers = []
two_poller_checks = []
two_poller_check_started = threading.Event()
two_poller_check_can_finish = threading.Event()


class ExplodingBarrier(Barrier):
    def check_waiting_participants(self, waiting_participants):
        raise RuntimeError("boom")

    def choose_who_to_release(self, waiting_participants):
        return []


class RecordingBarrier(Barrier):
    def check_waiting_participants(self, waiting_participants):
        processed_barriers.append(self.id)

    def choose_who_to_release(self, waiting_participants):
        return []


class ReleaseAllBarrier(Barrier):
    def choose_who_to_release(self, waiting_participants):
        return waiting_participants


class SpecErrorBarrier(Barrier):
    def choose_who_to_release(self, waiting_participants):
        raise BarrierSpecError("broken")


class BlockingReleaseBarrier(ReleaseAllBarrier):
    def check_waiting_participants(self, waiting_participants):
        two_poller_checks.append(self.id)
        two_poller_check_started.set()
        assert two_poller_check_can_finish.wait(timeout=2)


class WaitForTwoBarrier(Barrier):
    def choose_who_to_release(self, waiting_participants):
        if len(waiting_participants) < 2:
            return []
        return waiting_participants


class ConfigurableBarrier(Barrier):
    def __init__(self, id_, required):
        super().__init__(id_)
        self.required = required

    def choose_who_to_release(self, waiting_participants):
        if len(waiting_participants) < self.required:
            return []
        return waiting_participants


class RecordingTimeoutGroupBarrier(GroupBarrier):
    def handle_max_wait_timeout(self, participant):
        participant.timeout_callback_ran = True


class DummyModel(SQLBase):
    __tablename__ = "dummy_model"

    id = Column(String, primary_key=True)

    def on_release(
        self, group, participants, participant=None, barrier=None, experiment=None
    ):
        group.var.callback_owner = self.id


def test_random_partition():
    input = list(range(10))

    with pytest.raises(ValueError):
        SimpleGrouper.randomly_partition_list(input, group_size=3)

    partitioned = SimpleGrouper.randomly_partition_list(input, group_size=2)
    assert len(partitioned) == 5
    contents = [elt for group in partitioned for elt in group]
    assert sorted(contents) == list(range(10))


def test_max_wait_action_leave_group_requires_group_barrier():
    with pytest.raises(TypeError, match="max_wait_action"):
        Barrier(id_="plain_barrier", max_wait_action="leave_group")

    with pytest.raises(TypeError, match="max_wait_action"):
        RecordingBarrier(id_="recording_barrier", max_wait_action="leave_group")

    barrier = GroupBarrier(
        id_="group_barrier",
        group_type="main",
        max_wait_action="leave_group",
    )
    assert barrier.max_wait_action == "leave_group"
    for option in ["max_wait_action", "late_action"]:
        with pytest.raises(ValueError, match="renamed"):
            GroupBarrier(id_="group_barrier", group_type="main", **{option: "kick"})


def _noop_on_release(group, participants, participant, barrier):
    pass


def test_group_barrier_keeps_the_released_positional_order():
    """v13.3.0: (id_, group_type, waiting_logic, repetitions, max_wait_time, on_release, fix_time_credit)."""
    with pytest.warns(FutureWarning, match="waiting_logic_expected_repetitions"):
        barrier = GroupBarrier(
            "group_barrier", "main", None, 3, 30, _noop_on_release, True
        )

    assert barrier.max_wait_time == 30
    assert barrier.on_release.function is _noop_on_release
    assert barrier.fix_time_credit is True
    assert barrier.max_wait_action == "fail"


def test_default_barrier_uses_timeline_hold():
    barrier = ReleaseAllBarrier(id_="hold")

    assert barrier.waiting_logic.is_timeline_hold
    assert barrier.waiting_logic.barrier_id == barrier.id
    assert barrier.waiting_logic.time_estimate == 1.5
    assert barrier.waiting_logic.waiting_message is None
    assert barrier.waiting_logic.message_kind == "barrier"
    assert not isinstance(barrier.waiting_logic, WaitPage)


def test_barrier_accepts_custom_waiting_message():
    barrier = GroupBarrier(
        id_="wait_for_partner",
        group_type="pair",
        waiting_message="Waiting for your partner",
    )
    hold = barrier.waiting_logic

    assert hold.waiting_message == "Waiting for your partner"
    assert hold.message_kind is None
    assert hold.translated_waiting_message(None) == "Waiting for your partner"
    html = GroupBarrier(id_="tag", group_type="pair", waiting_message=tags.b("Wait"))
    assert str(html.waiting_logic.translated_waiting_message(None)) == "<b>Wait</b>"


def _message_by_role(participant):
    return f"Waiting for the {participant.var.role}'s partner"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_barrier_waiting_message_can_depend_on_the_participant(
    in_experiment_directory, db_session
):
    barrier = GroupBarrier(
        id_="wait_by_role", group_type="pair", waiting_message=_message_by_role
    )
    restored = barrier_from_spec_json(barrier_spec_json(barrier))
    proposer = new_participant(get_experiment())
    proposer.var.role = "proposer"

    expected = "Waiting for the proposer's partner"
    assert barrier.waiting_logic.translated_waiting_message(proposer) == expected
    assert (
        call_function_with_context(restored.waiting_message, participant=proposer)
        == expected
    )


def test_explicit_barrier_waiting_logic_is_preserved():
    waiting_logic = WaitPage(wait_time=1)
    barrier = ReleaseAllBarrier(id_="page_wait", waiting_logic=waiting_logic)

    assert barrier.waiting_logic is waiting_logic


def test_waiting_message_rejects_explicit_waiting_logic():
    with pytest.raises(ValueError, match="waiting_message"):
        ReleaseAllBarrier(
            id_="page_wait",
            waiting_logic=WaitPage(wait_time=1),
            waiting_message="Waiting for your partner",
        )


def test_barrier_rejects_negative_expected_wait():
    with pytest.raises(ValueError, match="expected_wait"):
        ReleaseAllBarrier(id_="negative_wait", expected_wait=-1)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_barrier_definition_and_instance_use_request_transaction(
    in_experiment_directory, db_session
):
    """Barrier persistence must not commit through a hidden side session."""
    participant = new_participant(get_experiment())
    participant.status = "working"
    barrier = ReleaseAllBarrier(id_=f"transactional_{get_random_id()}")

    barrier.receive_participant(participant)
    definition_id = barrier.id
    instance_id = participant.active_barriers[barrier.id].barrier_instance.id

    with db.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT id FROM barrier WHERE id = :id"),
                {"id": definition_id},
            ).first()
            is None
        )
        assert (
            connection.execute(
                text("SELECT id FROM barrier_instance WHERE id = :id"),
                {"id": instance_id},
            ).first()
            is None
        )

    db_session.commit()
    assert BarrierDefinition.query.get(definition_id) is not None
    instance = BarrierInstance.query.get(instance_id)
    assert json.loads(instance.spec)["version"] == 1
    assert "py/object" not in instance.spec


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_pending_barrier_checks_are_discarded_on_rollback(
    in_experiment_directory, db_session
):
    participant = new_participant(get_experiment())
    participant.status = "working"
    barrier = ReleaseAllBarrier(id_="rolled_back_arrival")
    _arrive_at_group_barrier(get_experiment(), barrier, participant)

    db_session.rollback()

    assert _take_pending_barrier_checks() == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_nested_edits_to_a_group_s_trial_maker_runs_are_saved(
    in_experiment_directory, db_session
):
    group = _pair_sync_group(get_experiment(), db_session)[1]
    _edit_group_runs(group, "tm", lambda runs: runs.append({"members": []}))
    db_session.commit()
    _edit_group_runs(group, "tm", lambda runs: runs[-1]["members"].append(1))
    db_session.commit()
    db_session.expire_all()

    assert group.trial_maker_runs == {"tm": [{"members": [1]}]}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_reuses_one_instance_per_group_visit(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first, second = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="instance_visit", group_type="main")

    _arrive_at_group_barrier(exp, barrier, first)
    first_instance_id = first.active_barriers[barrier.id].barrier_instance_id
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, second)
    second_instance_id = second.barrier_links[-1].barrier_instance_id
    _commit_barrier_arrivals()

    assert second_instance_id == first_instance_id
    assert not BarrierInstance.query.get(first_instance_id).active

    barrier.receive_participant(first)
    next_instance_id = first.active_barriers[barrier.id].barrier_instance_id
    assert next_instance_id != first_instance_id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_existing_barrier_instance_does_not_take_creation_lock(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    first, second = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="instance_fast_path", group_type="main")
    barrier.receive_participant(first)
    db_session.commit()

    def reject_creation_lock(instance_id, *, wait=False):
        if wait:
            raise AssertionError("Existing instances must not take the creation lock.")
        return True

    monkeypatch.setattr("psynet.sync._claim_barrier_instance", reject_creation_lock)
    barrier.receive_participant(second)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_active_barrier_instance_is_unique_per_group(
    in_experiment_directory, db_session
):
    """Two active visits for the same group must not share a waiting pool."""
    exp = get_experiment()
    first, _second = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="unique_group_instance", group_type="main")
    barrier.receive_participant(first)
    db_session.commit()
    existing = first.active_barriers[barrier.id].barrier_instance
    duplicate = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id=existing.barrier_id,
        group_id=existing.group_id,
        active=True,
        spec=existing.spec,
        behavior_hash=existing.behavior_hash,
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(duplicate)
            db_session.flush()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_active_ungrouped_barrier_instance_is_unique(
    in_experiment_directory, db_session
):
    """Groupers and other ungrouped barriers share one active pool per ID."""
    BarrierDefinition.ensure_exists("unique_ungrouped", SimpleGrouper)
    first = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id="unique_ungrouped",
        group_id=None,
        active=True,
        spec="{}",
        behavior_hash="hash",
    )
    db_session.add(first)
    db_session.commit()
    duplicate = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id="unique_ungrouped",
        group_id=None,
        active=True,
        spec="{}",
        behavior_hash="hash",
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(duplicate)
            db_session.flush()
    first.active = False
    db_session.commit()
    db_session.add(duplicate)
    db_session.flush()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_for_arrival_recovers_when_a_concurrent_insert_wins(
    in_experiment_directory, db_session, monkeypatch
):
    """A unique-index collision must reuse the committed winner."""
    exp = get_experiment()
    first, second = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="unique_recover", group_type="main")
    barrier.receive_participant(first)
    db_session.commit()
    winner = first.active_barriers[barrier.id].barrier_instance
    remaining = {"lookups": 2}
    original = BarrierInstance._active_instance.__func__

    def miss_then_find(cls, barrier_id, group_id):
        if remaining["lookups"]:
            remaining["lookups"] -= 1
            return None
        return original(cls, barrier_id, group_id)

    monkeypatch.setattr(
        BarrierInstance, "_active_instance", classmethod(miss_then_find)
    )
    recovered = BarrierInstance.for_arrival(barrier, second)
    assert recovered.id == winner.id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_barrier_id_rejects_a_different_class(in_experiment_directory, db_session):
    exp = get_experiment()
    first = new_participant(exp)
    second = new_participant(exp)
    first.status = second.status = "working"
    ReleaseAllBarrier(id_="stable_definition").receive_participant(first)
    db_session.commit()

    with pytest.raises(ValueError, match="already identifies"):
        WaitForTwoBarrier(id_="stable_definition").receive_participant(second)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_shared_barrier_id_rejects_different_behavior(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first = new_participant(exp)
    second = new_participant(exp)
    first.status = second.status = "working"
    ConfigurableBarrier(id_="stable_behavior", required=2).receive_participant(first)
    db_session.commit()

    with pytest.raises(ValueError, match="different behavior"):
        ConfigurableBarrier(id_="stable_behavior", required=3).receive_participant(
            second
        )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_same_group_barrier_id_uses_distinct_instances_per_group(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first_group = _pair_sync_group(exp, db_session)[0]
    second_group = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="group_scoped", group_type="main")

    barrier.receive_participant(first_group[0])
    barrier.receive_participant(second_group[0])

    first_instance = first_group[0].active_barriers[barrier.id].barrier_instance
    second_instance = second_group[0].active_barriers[barrier.id].barrier_instance
    assert first_instance.id != second_instance.id
    assert first_instance.group_id != second_instance.group_id
    assert first_instance.participant_links == [
        first_group[0].active_barriers[barrier.id]
    ]
    assert second_instance.participant_links == [
        second_group[0].active_barriers[barrier.id]
    ]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_same_barrier_id_keeps_each_group_visits_callback(
    in_experiment_directory, db_session
):
    """Each group's instance must retain its first arrival's bound callback."""
    DummyModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    exp = get_experiment()
    first_group, first_sync_group = _pair_sync_group(exp, db_session)
    second_group, second_sync_group = _pair_sync_group(exp, db_session)
    first_owner = DummyModel(id=get_random_id())
    second_owner = DummyModel(id=get_random_id())
    db_session.add_all([first_owner, second_owner])
    db_session.flush()
    first_barrier = GroupBarrier(
        id_="callback_scoped", group_type="main", on_release=first_owner.on_release
    )
    second_barrier = GroupBarrier(
        id_="callback_scoped", group_type="main", on_release=second_owner.on_release
    )

    _arrive_at_group_barrier(exp, first_barrier, first_group[0])
    _arrive_at_group_barrier(exp, second_barrier, second_group[0])
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, first_barrier, first_group[1])
    _arrive_at_group_barrier(exp, second_barrier, second_group[1])
    _commit_barrier_arrivals()

    db_session.refresh(first_sync_group)
    db_session.refresh(second_sync_group)
    assert first_sync_group.var.callback_owner == first_owner.id
    assert second_sync_group.var.callback_owner == second_owner.id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_accepts_same_callback_bound_to_each_participants_model(
    in_experiment_directory, db_session
):
    """Participant-local ORM receivers must not change shared barrier behavior."""
    DummyModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    exp = get_experiment()
    participants, sync_group = _pair_sync_group(exp, db_session)
    owners = [DummyModel(id=get_random_id()), DummyModel(id=get_random_id())]
    db_session.add_all(owners)
    db_session.flush()

    for participant, owner in zip(participants, owners):
        barrier = GroupBarrier(
            id_="participant_bound_callback",
            group_type="main",
            on_release=owner.on_release,
        )
        _arrive_at_group_barrier(exp, barrier, participant)

    _commit_barrier_arrivals()
    db_session.refresh(sync_group)
    assert sync_group.var.callback_owner == owners[0].id


def test_group_barrier_resolved_timeout_uses_overridden_handler():
    barrier = RecordingTimeoutGroupBarrier(
        id_="group_barrier",
        group_type="main",
        max_wait_action="leave_group",
    )
    elts = barrier.resolve()
    hold = next(elt for elt in elts if getattr(elt, "is_timeline_hold", False))
    participant = SimpleNamespace(timeout_callback_ran=False, module_state=None)

    assert hold.fail_on_timeout is False
    hold.apply_timeout(participant)
    assert participant.timeout_callback_ran


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_allocator(in_experiment_directory, db_session):
    exp = get_experiment()
    grouper = SimpleGrouper(group_type="main", initial_group_size=3, quorum=3)
    participants = [new_participant(exp) for _ in range(6)]

    _arrive_at_group_barrier(exp, grouper, participants[0])
    _commit_barrier_arrivals()

    assert BarrierDefinition.query.get("main_grouper_3") is not None
    assert "main_grouper_3" in participants[0].active_barriers
    assert "main_grouper_3" not in participants[1].active_barriers
    assert not grouper.can_participant_exit(participants[0])

    for participant in participants:
        assert participant.sync_group is None

    _arrive_at_group_barrier(exp, grouper, participants[1])
    _commit_barrier_arrivals()

    assert not grouper.can_participant_exit(participants[0])

    for participant in participants:
        assert participant.sync_group is None

    _arrive_at_group_barrier(exp, grouper, participants[2])

    _commit_barrier_arrivals()

    assert grouper.can_participant_exit(participants[0])

    for participant in participants[:3]:
        group = participant.sync_group
        assert len(group.participants) == 3
        assert group.creation_time is not None
        assert group.end_time is None

    group = participants[0].sync_group
    assert isinstance(group.leader, Participant)

    with pytest.raises(TypeError, match=r"group\.add_participant"):
        group.participants.append(participants[3])
    assert participants[3] not in group.participants

    with pytest.raises(
        RuntimeError,
        match="Participant is already in a group with this group_type \\('main'\\).",
    ):
        grouper.receive_participant(participants[0])

    group.close()
    db.session.commit()

    assert participants[0].sync_group is None
    grouper.receive_participant(participants[0])


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_simple_grouper_groups_on_last_arrival(in_experiment_directory, db_session):
    exp = get_experiment()
    first, second = [new_participant(exp) for _ in range(2)]
    for participant in (first, second):
        participant.status = "working"
    grouper = SimpleGrouper(
        group_type="pair_on_arrival",
        initial_group_size=2,
        waiting_message="Waiting for your partner",
    )

    _arrive_at_group_barrier(exp, grouper, first)
    _commit_barrier_arrivals()
    assert first.sync_group is None

    _arrive_at_group_barrier(exp, grouper, second)
    _commit_barrier_arrivals()
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.sync_group is not None
    assert second.sync_group.id == first.sync_group.id
    assert len(first.sync_group.participants) == 2


@pytest.mark.parametrize("stop_top_ups", [False, True])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_grouper_leftover_waiter_joins_an_open_group(
    in_experiment_directory, db_session, stop_top_ups
):
    """A waiter left over from a burst joins the group formed without them, unless a barrier stopped top-ups."""
    exp = get_experiment()
    grouper = SimpleGrouper(
        group_type="quorum",
        initial_group_size=2,
        max_group_size=None,
        join_existing_groups=True,
        use_admission_points=False,
    )
    participants = _working_participants(exp, 3)
    for participant in participants:
        _arrive_at_group_barrier(exp, grouper, participant)
    _commit_barrier_arrivals()
    leftover = next(p for p in participants if p.sync_group is None)
    if stop_top_ups:
        game_starts = GroupBarrier(
            id_="game_starts", group_type="quorum", stop_top_ups=True
        )
        for participant in participants:
            if participant is not leftover:
                _arrive_at_group_barrier(exp, game_starts, participant)
        _commit_barrier_arrivals()

    check_barriers()

    db_session.refresh(leftover)
    if stop_top_ups:
        assert leftover.sync_group is None
        return
    assert grouper.can_participant_exit(leftover)
    assert len(leftover.sync_group.participants) == 3


@pytest.mark.parametrize("accepts_top_ups", [True, False])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_grouper_does_not_join_a_group_without_active_members(
    in_experiment_directory, db_session, accepts_top_ups
):
    """A group whose members all left closes, with or without top-ups, and is not joined.

    The barrier poller closes a group that accepts top-ups, under its row lock.
    """
    exp = get_experiment()
    (member,), group = _sync_group_of(exp, db_session, 1, group_type="quorum")
    group.accepts_top_ups = accepts_top_ups
    member.fail("left")
    assert group.active == accepts_top_ups
    db_session.commit()
    check_sync_groups()
    db_session.refresh(group)
    assert not group.active
    (newcomer,) = _working_participants(exp, 1)
    grouper = SimpleGrouper(
        group_type="quorum",
        initial_group_size=2,
        max_group_size=None,
        join_existing_groups=True,
        use_admission_points=False,
    )

    assert grouper.choose_who_to_release([newcomer]) == []
    assert newcomer.sync_group is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_simultaneous_joins_do_not_overfill_a_group(
    in_experiment_directory, db_session
):
    """Two participants racing for a group's last place cannot both get it."""
    exp = get_experiment()
    _members, group = _sync_group_of(exp, db_session, 2, group_type="top_up")
    group.accepts_top_ups = True
    group.max_group_size = 3
    first, second = _working_participants(exp, 2)
    group_id, joiner_ids = group.id, (first.id, second.id)
    db.session.commit()
    db.session.remove()
    grouper = SimpleGrouper(
        group_type="top_up",
        initial_group_size=2,
        max_group_size=3,
        join_existing_groups=True,
        use_admission_points=False,
    )
    first_joined, first_may_commit = threading.Event(), threading.Event()
    errors, second_pid = [], []

    def join(participant_id, joined=None, may_commit=None):
        try:
            if joined is None:
                second_pid.append(
                    db.session.execute(text("SELECT pg_backend_pid()")).scalar()
                )
            participant = (
                Participant.query.with_for_update(of=Participant)
                .populate_existing()
                .get(participant_id)
            )
            grouper.choose_who_to_release([participant])
            db.session.flush()
            if joined is not None:
                joined.set()
                assert may_commit.wait(60)
            db.session.commit()
        except Exception as err:  # pragma: no cover - surfaced below
            errors.append(err)
            db.session.rollback()
        finally:
            db.session.remove()

    racers = [
        threading.Thread(
            target=join, args=(joiner_ids[0], first_joined, first_may_commit)
        ),
        threading.Thread(target=join, args=(joiner_ids[1],)),
    ]
    racers[0].start()
    assert first_joined.wait(30)
    racers[1].start()
    # Commit the first join only once the second has finished or is blocked on it.
    deadline = time.monotonic() + 30
    while racers[1].is_alive() and time.monotonic() < deadline:
        if (
            second_pid
            and db.session.execute(
                text(
                    "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :p"
                ),
                {"p": second_pid[0]},
            ).scalar()
        ):
            break
        db.session.rollback()
        time.sleep(0.05)
    first_may_commit.set()
    for racer in racers:
        racer.join(30)

    assert not any(racer.is_alive() for racer in racers)
    assert errors == []
    group = SimpleSyncGroup.query.get(group_id)
    assert len(group.participants) == 3
    assert group.n_active_participants == 3


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_join_skips_a_group_that_another_request_is_changing(
    in_experiment_directory, db_session
):
    """A joiner takes the next open group instead of waiting for a busy one."""
    exp = get_experiment()
    groups = [
        _sync_group_of(exp, db_session, 2, group_type="top_up")[1] for _ in range(2)
    ]
    for group in groups:
        group.accepts_top_ups = True
        group.max_group_size = 3
    (joiner,) = _working_participants(exp, 1)
    db.session.commit()
    busy, free = groups
    grouper = SimpleGrouper(
        group_type="top_up",
        initial_group_size=2,
        max_group_size=3,
        join_existing_groups=True,
        use_admission_points=False,
    )

    with db.engine.connect() as other, other.begin():
        other.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR UPDATE"), {"id": busy.id}
        )
        _set_transaction_lock_timeout(1)
        assert grouper.choose_who_to_release([joiner]) == [joiner]
        assert joiner.active_sync_groups["top_up"].id == free.id


def _commit_once_blocked(connection, transaction, pid, before_commit=None):
    """Commit ``transaction`` once backend ``pid`` waits on a lock, calling ``before_commit`` first."""
    deadline = time.monotonic() + 10
    while (
        time.monotonic() < deadline
        and not connection.execute(
            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
        ).scalar()
    ):
        time.sleep(0.01)
    if before_commit is not None:
        before_commit()
    transaction.commit()


def _row_lock_is_free(group_id):
    """Return whether another connection can lock a sync group's row without waiting."""
    with db.engine.connect() as prober, prober.begin():
        try:
            prober.execute(
                text(
                    "SELECT id FROM sync_group WHERE id = :id FOR NO KEY UPDATE NOWAIT"
                ),
                {"id": group_id},
            )
            return True
        except OperationalError:
            return False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_newcomer_waits_briefly_for_a_busy_group_instead_of_the_poller(
    in_experiment_directory, db_session
):
    """Reaching the grouper, a newcomer joins a group another request holds once it commits."""
    exp = get_experiment()
    _members, group = _sync_group_of(exp, db_session, 2, group_type="top_up")
    group.accepts_top_ups = True
    group.max_group_size = 4
    prompt, slow = _working_participants(exp, 2)
    grouper = SimpleGrouper(
        group_type="top_up",
        initial_group_size=2,
        max_group_size=4,
        join_existing_groups=True,
        use_admission_points=False,
    )

    def hold_group_row(other):
        transaction = other.begin()
        other.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR NO KEY UPDATE"),
            {"id": group.id},
        )
        return transaction

    lock_timeout = "SELECT current_setting('lock_timeout')"
    _set_transaction_lock_timeout(5)
    newcomer_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
    with db.engine.connect() as other:
        releaser = threading.Thread(
            target=_commit_once_blocked,
            args=(other, hold_group_row(other), newcomer_pid),
        )
        releaser.start()
        grouper._join_on_arrival(prompt)
        releaser.join(30)
    assert prompt.in_sync_group("top_up")
    assert db_session.execute(text(lock_timeout)).scalar() == "5s"
    db_session.commit()

    _set_transaction_lock_timeout(5)
    with db.engine.connect() as other:
        transaction = hold_group_row(other)
        grouper._join_on_arrival(slow)
        assert not slow.in_sync_group("top_up")
        assert db_session.execute(text(lock_timeout)).scalar() == "5s"
        db_session.commit()
        transaction.commit()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_newcomer_waiting_for_a_busy_group_holds_no_full_groups_row(
    in_experiment_directory, db_session, monkeypatch
):
    """While a newcomer waits for a busy group, a group found full stays unlocked."""
    # The busy row is released only after the probe, so the wait must outlast it.
    monkeypatch.setattr("psynet.sync._JOIN_LOCK_WAIT_SECONDS", 30)
    exp = get_experiment()
    _, full = _sync_group_of(exp, db_session, 4, group_type="top_up")
    _, busy = _sync_group_of(exp, db_session, 2, group_type="top_up")
    full.n_active_participants = 1  # stale, so it is tried first
    for group in [full, busy]:
        group.accepts_top_ups = True
        group.max_group_size = 4
    (newcomer,) = _working_participants(exp, 1)
    grouper = SimpleGrouper(
        group_type="top_up",
        initial_group_size=2,
        max_group_size=4,
        join_existing_groups=True,
        use_admission_points=False,
    )
    lock_sql = "SELECT id FROM sync_group WHERE id = :id FOR NO KEY UPDATE"
    full_id, busy_id = full.id, busy.id
    full_row_free = []

    newcomer_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
    with db.engine.connect() as other:
        transaction = other.begin()
        other.execute(text(lock_sql), {"id": busy_id})
        releaser = threading.Thread(
            target=_commit_once_blocked,
            args=(other, transaction, newcomer_pid),
            kwargs={
                "before_commit": lambda: full_row_free.append(
                    _row_lock_is_free(full_id)
                )
            },
        )
        releaser.start()
        grouper._join_on_arrival(newcomer)
        releaser.join(30)
    assert full_row_free == [True]
    assert newcomer.active_sync_groups["top_up"] == busy
    db_session.commit()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_newcomer_releases_a_busy_group_found_full_after_waiting(
    in_experiment_directory, db_session
):
    """A busy group the newcomer waited for but found full is not left locked."""
    exp = get_experiment()
    _, full = _sync_group_of(exp, db_session, 4, group_type="top_up")
    full.n_active_participants = 1  # stale, so it looks open
    full.accepts_top_ups = True
    full.max_group_size = 4
    (newcomer,) = _working_participants(exp, 1)
    grouper = SimpleGrouper(
        group_type="top_up",
        initial_group_size=2,
        max_group_size=4,
        join_existing_groups=True,
        use_admission_points=False,
    )
    full_id = full.id
    db_session.commit()

    newcomer_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
    with db.engine.connect() as other:
        transaction = other.begin()
        other.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR NO KEY UPDATE"),
            {"id": full_id},
        )
        releaser = threading.Thread(
            target=_commit_once_blocked, args=(other, transaction, newcomer_pid)
        )
        releaser.start()
        grouper._join_on_arrival(newcomer)
        releaser.join(30)
    assert not newcomer.in_sync_group("top_up")
    assert _row_lock_is_free(full_id)
    db_session.commit()


@pytest.mark.parametrize("request_kind", ["response", "timeline"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_partner_leaving_sends_participant_to_unsuccessful_end(
    in_experiment_directory, db_session, request_kind
):
    """The open page is not rebuilt after the partner leaves and the group closes."""
    exp = get_experiment()
    original_timeline = exp.timeline
    exp.timeline = Timeline(
        PageMaker(
            lambda participant: InfoPage(f"Group {participant.sync_group.id}"),
            time_estimate=1,
        ),
    )
    try:
        (stayer, leaver), _ = _pair_sync_group(exp, db_session)
        assert _json_timeline(exp, stayer).status_code == 200
        leaver.fail("returned the study")
        db_session.commit()
        assert stayer.failed

        if request_kind == "response":
            result = _process_response(exp, stayer, stayer.page_uuid)
            assert result.payload["submission"] == "approved"
            assert Response.query.filter_by(participant_id=stayer.id).count() == 0
        else:
            assert _json_timeline(exp, stayer).status_code == 200
        assert exp.timeline.get_participant_branch(stayer) == "unsuccessful_end"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_queued_redirect_still_checks_the_page_uuid(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original_timeline = exp.timeline
    exp.timeline = Timeline(
        PageMaker(
            lambda participant: InfoPage(f"Group {participant.sync_group.id}"),
            time_estimate=1,
        ),
    )
    try:
        (stayer, leaver), _ = _pair_sync_group(exp, db_session)
        assert _json_timeline(exp, stayer).status_code == 200
        leaver.fail("returned the study")
        stayer.client_ip_address = "203.0.113.9"
        db_session.commit()

        result = _process_response(exp, stayer, "not-the-open-page")
        assert result.payload["submission"] == "rejected"
        assert stayer.unique_id not in json.dumps(result.payload)
        assert stayer.client_ip_address == "203.0.113.9"
        assert stayer.pending_redirect == "unsuccessful_end"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_queued_redirect_accepts_a_catch_up_from_the_participants_hold(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    original_timeline = exp.timeline
    exp.timeline = _stacked_partner_timeline(f"redirect_{uuid.uuid4().hex[:8]}")
    try:
        stayer, leaver = _working_participants(exp, 2)
        _json_timeline(exp, stayer)
        _json_timeline(exp, leaver)
        db.session.expire_all()
        stayer = Participant.query.get(stayer.id)
        _json_timeline(exp, stayer)
        db.session.expire_all()
        stayer = Participant.query.get(stayer.id)
        assert type(exp.timeline.get_current_elt(exp, stayer)).__name__ == (
            "_BarrierHoldPage"
        )
        hold_uuid = stayer.page_uuid
        _catch_up_until_action(exp, [stayer.id, leaver.id])
        db.session.expire_all()
        Participant.query.get(leaver.id).fail("returned the study")
        db_session.commit()
        stayer = Participant.query.get(stayer.id)
        assert Experiment._pending_redirect_replaces_open_page(stayer)

        result = _process_response(exp, stayer, hold_uuid)
        assert result.payload["submission"] == "approved"
        assert exp.timeline.get_participant_branch(stayer) == "unsuccessful_end"
    finally:
        exp.timeline = original_timeline


def test_sync_group_dashboard_waiting_barrier_indexes():
    waiting_by_participant, waiting_by_barrier = _index_waiting_barriers(
        [
            (2, "barrier_b"),
            (1, "barrier_a"),
            (2, "barrier_a"),
        ]
    )

    assert waiting_by_participant[1] == ["barrier_a"]
    assert waiting_by_participant[2] == ["barrier_b", "barrier_a"]
    assert waiting_by_barrier == {
        "barrier_a": (2, [1, 2]),
        "barrier_b": (1, [2]),
    }
    assert _summarize_waiting_at_barriers({1, 2}, waiting_by_participant) == [
        {"barrier_id": "barrier_a", "waiting_count": 2, "participant_ids": [1, 2]},
        {"barrier_id": "barrier_b", "waiting_count": 1, "participant_ids": [2]},
    ]


def test_sync_group_dashboard_grouper_progress_uses_timeline_all_elts(monkeypatch):
    grouper = SimpleGrouper(
        group_type="main", initial_group_size=3, quorum=3, batch_size=2
    )
    timeline = SimpleNamespace(
        all_elts=[
            SimpleNamespace(links={"barrier": grouper}),
            SimpleNamespace(links={"barrier": grouper}),
            SimpleNamespace(links={}),
        ]
    )
    monkeypatch.setattr(
        "psynet.experiment.get_experiment",
        lambda: SimpleNamespace(timeline=timeline),
    )

    assert _get_grouper_progress() == [
        {
            "barrier_id": "main_grouper_3",
            "group_type": "main",
            "batch_size": 2,
            "initial_group_size": 3,
        }
    ]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_manual_sync_group_participant_failure(in_experiment_directory, db_session):
    exp = get_experiment()
    participants = [new_participant(exp) for _ in range(2)]
    for participant in participants:
        participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=2,
        max_group_size=2,
        quorum=1,
        n_active_participants=2,
        accepts_top_ups=False,
    )
    db_session.add(group)
    for participant in participants:
        group.add_participant(participant)
    group.leader = participants[0]
    db_session.commit()

    failed_participant = _fail_sync_group_participant(
        participants[0].id, group.id, "manual_failure"
    )

    assert failed_participant.failed
    assert "manual_failure" in failed_participant.failure_tags
    assert participants[0] not in group.active_participants
    assert participants[1] in group.active_participants


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_manual_sync_group_participant_kick(in_experiment_directory, db_session):
    exp = get_experiment()
    participants = [new_participant(exp) for _ in range(2)]
    for participant in participants:
        participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=2,
        max_group_size=2,
        quorum=1,
        n_active_participants=2,
        accepts_top_ups=False,
    )
    db_session.add(group)
    for participant in participants:
        group.add_participant(participant)
    group.leader = participants[0]
    db_session.commit()

    kicked_participant = _kick_sync_group_participant(
        participants[0].id, group.id, "manual_kick"
    )

    assert not kicked_participant.failed
    assert "manual_failure" not in kicked_participant.failure_tags
    assert participants[0] not in group.active_participants
    assert participants[1] in group.active_participants
    assert (
        kicked_participant.sync_group_removal_reason("main")
        == "removed_by_experimenter"
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_manual_sync_group_participant_kick_targets_selected_group(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"

    main_group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=2,
        quorum=1,
        n_active_participants=1,
        accepts_top_ups=True,
    )
    secondary_group = SimpleSyncGroup(
        group_type="secondary",
        initial_group_size=1,
        max_group_size=2,
        quorum=1,
        n_active_participants=1,
        accepts_top_ups=True,
    )
    db_session.add(main_group)
    db_session.add(secondary_group)
    main_group.add_participant(participant)
    secondary_group.add_participant(participant)
    main_group.leader = participant
    secondary_group.leader = participant
    db_session.commit()

    kicked_participant = _kick_sync_group_participant(
        participant.id, secondary_group.id, "manual_kick"
    )

    assert kicked_participant == participant
    assert participant in main_group.active_participants
    assert participant not in secondary_group.active_participants
    assert participant.active_sync_groups == {"main": main_group}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_manual_sync_group_participant_kick_handles_empty_top_up_group(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=2,
        quorum=1,
        n_active_participants=1,
        accepts_top_ups=True,
    )
    db_session.add(group)
    group.add_participant(participant)
    group.leader = participant
    db_session.commit()

    kicked_participant = _kick_sync_group_participant(
        participant.id, group.id, "manual_kick"
    )

    assert not kicked_participant.failed
    assert group.active_participants == []
    assert group.n_active_participants == 0
    assert group.leader is None
    db_session.commit()
    check_sync_groups()
    db_session.refresh(group)
    assert not group.active
    assert group.end_time is not None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("fail_below_min_size", [True, False])
def test_manual_sync_group_participant_kick_dissolves_group_below_min_size(
    in_experiment_directory, db_session, fail_below_min_size
):
    exp = get_experiment()
    participants = [new_participant(exp) for _ in range(3)]
    for participant in participants:
        participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=3,
        n_active_participants=3,
        accepts_top_ups=False,
        below_quorum="fail" if fail_below_min_size else "continue_without_group",
    )
    db_session.add(group)
    for participant in participants:
        group.add_participant(participant)
    group.leader = participants[0]
    db_session.commit()

    kicked_participant = _kick_sync_group_participant(
        participants[0].id, group.id, "manual_kick"
    )

    assert not kicked_participant.failed
    assert participants[0] not in group.active_participants
    assert participants[1] not in group.active_participants
    assert participants[2] not in group.active_participants
    assert participants[1].failed == fail_below_min_size
    assert participants[2].failed == fail_below_min_size
    assert group.n_active_participants == 0
    assert not group.active


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("participant_status", ["approved", "returned"])
def test_manual_sync_group_participant_failure_rejects_non_working_participants(
    in_experiment_directory, db_session, participant_status
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = participant_status

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        quorum=1,
        n_active_participants=1,
        accepts_top_ups=False,
    )
    db_session.add(group)
    group.add_participant(participant)
    group.leader = participant
    db_session.commit()

    with pytest.raises(
        ValueError, match="Only active working participants can be failed manually."
    ):
        _fail_sync_group_participant(participant.id, group.id, "manual_failure")

    assert not participant.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_manual_sync_group_participant_failure_rejects_inactive_group_member(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        quorum=1,
        n_active_participants=1,
        accepts_top_ups=False,
    )
    db_session.add(group)
    group.add_participant(participant)
    group.participant_links[0].active = False
    group.leader = participant
    db_session.commit()

    with pytest.raises(
        ValueError, match="not currently active in the selected sync group"
    ):
        _fail_sync_group_participant(participant.id, group.id, "manual_failure")

    assert not participant.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_skips_failure(in_experiment_directory, db_session):
    exp = get_experiment()
    processed_barriers.clear()

    bad_barrier = ExplodingBarrier(id_="a_bad")
    good_barrier = RecordingBarrier(id_="b_good")
    participants = [new_participant(exp) for _ in range(2)]

    bad_barrier.receive_participant(participants[0])
    good_barrier.receive_participant(participants[1])
    db.session.commit()

    check_barriers()

    assert "b_good" in processed_barriers


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_poller_does_not_leave_advisory_locks_after_success_or_failure(
    in_experiment_directory, db_session
):
    """A poller sweep must return advisory locks to baseline, including failures."""
    exp = get_experiment()
    baseline = _advisory_lock_count()
    processed_barriers.clear()
    bad_barrier = ExplodingBarrier(id_="a_bad_lock")
    good_barrier = RecordingBarrier(id_="b_good_lock")
    participants = [new_participant(exp) for _ in range(2)]
    bad_barrier.receive_participant(participants[0])
    good_barrier.receive_participant(participants[1])
    db.session.commit()

    check_barriers()

    assert "b_good_lock" in processed_barriers
    assert _advisory_lock_count() == baseline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_skip_after_commit_releases_extra_claim_on_failure(
    in_experiment_directory, db_session, monkeypatch
):
    """An extra-connection visit claim must not leak if the poller skip raises."""
    exp = get_experiment()
    baseline = _advisory_lock_count()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="skip_claim_leak", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)

    def boom(participant_ids):
        raise RuntimeError("skip failed")

    monkeypatch.setattr("psynet.sync._advance_released_hold_waiters_after_commit", boom)
    checks = _commit_arrival_write()
    instance_id = checks[0]
    with pytest.raises(RuntimeError, match="skip failed"):
        with _hold_barrier_instance_claim(instance_id, wait=True):
            _check_and_skip_held_instance(instance_id)
    assert _advisory_lock_count() == baseline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_already_claimed_skips_orm_visit_key(
    in_experiment_directory, db_session, monkeypatch
):
    """Check-and-skip must not take the visit key on ``db.session``."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="already_claimed_key", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)
    db.session.commit()
    instance_id = next(iter(last.active_barriers.values())).barrier_instance_id
    instance = BarrierInstance.query.get(instance_id)

    with _hold_barrier_instance_claim(instance_id, wait=True):
        assert _claim_barrier_instance(instance_id, wait=False) is False

        def forbid_orm_claim(*_args, **_kwargs):
            raise AssertionError("ORM session must not take the visit key")

        monkeypatch.setattr("psynet.sync._claim_barrier_instance", forbid_orm_claim)
        assert _check_claimed_barrier_instance(instance, already_claimed=True) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_skip_failure_after_waiter_lock_releases_row_and_claim(
    in_experiment_directory, db_session, monkeypatch
):
    """A skip that already holds a participant row must still drop that lock."""
    exp = get_experiment()
    baseline = _advisory_lock_count()
    processed_barriers.clear()
    bad = ReleaseAllBarrier(id_="a_skip_lock")
    good = RecordingBarrier(id_="b_skip_ok")
    bad_participant = new_participant(exp)
    good_participant = new_participant(exp)
    bad_participant.status = "working"
    good_participant.status = "working"
    bad.receive_participant(bad_participant)
    good.receive_participant(good_participant)
    db.session.commit()
    bad_id = bad_participant.id
    original_advance = Experiment._advance_past_ready_holds
    original_get = type(exp.timeline).get_current_elt
    boom_calls = []

    def hold_elt(self, experiment, participant):
        if participant.id == bad_id:
            return SimpleNamespace(is_timeline_hold=True)
        return original_get(self, experiment, participant)

    def boom(self, participant, page):
        if participant.id == bad_id:
            boom_calls.append(participant.id)
            raise RuntimeError("skip failed after lock")
        return original_advance(self, participant, page)

    monkeypatch.setattr(type(exp.timeline), "get_current_elt", hold_elt)
    monkeypatch.setattr(Experiment, "_advance_past_ready_holds", boom)
    check_barriers()

    assert boom_calls == [bad_id]
    assert "b_skip_ok" in processed_barriers
    assert _participant_row_is_locked(bad_id) is False
    assert _advisory_lock_count() == baseline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_pending_checks_run_every_instance_after_a_false_result(
    in_experiment_directory, db_session, monkeypatch
):
    """A waiter NOWAIT miss must not skip later queued instance checks."""
    from contextlib import contextmanager

    seen = []

    @contextmanager
    def fake_claim(_instance_id, **_kwargs):
        yield True

    def fake_check(instance_id, **_kwargs):
        seen.append(instance_id)
        return False

    monkeypatch.setattr("psynet.sync._hold_barrier_instance_claim", fake_claim)
    monkeypatch.setattr("psynet.sync._check_held_instance", fake_check)
    assert _run_pending_barrier_checks(["first-id", "second-id"]) is False
    assert seen == ["first-id", "second-id"]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_pending_checks_without_wait_tries_the_claim(
    in_experiment_directory, db_session, monkeypatch
):
    """Waiter GET recovery still tries the visit claim when it is free."""
    instance_id = f"no-wait-{uuid.uuid4().hex}"
    seen = []

    def fake_check(check_id, **_kwargs):
        seen.append(check_id)
        return True

    monkeypatch.setattr("psynet.sync._check_held_instance", fake_check)
    assert _run_pending_barrier_checks([instance_id], wait=False) is True
    assert seen == [instance_id]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_grouper_would_release_only_when_the_batch_is_full(
    in_experiment_directory, db_session
):
    """GET wait-for-claim must distinguish waiter arrival from last-arrival."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"would_release_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=2)
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        assert _pending_checks_should_wait_for_claim([instance_id]) is False
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        last = Participant.query.get(last.id)
        assert last.sync_group is not None
        last_page = exp.timeline.get_current_elt(exp, last)
        if getattr(last_page, "is_timeline_hold", False):
            assert _json_hold_is_silent(last_response.get_json())
        else:
            assert last_page.label == "choose_action"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_visit_check_would_release_spec_error_does_not_wait(
    in_experiment_directory, db_session, monkeypatch
):
    """A spec error during the release peek must not fail the arriver."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"peek_spec_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id

        def boom(self):
            raise BarrierSpecError("missing callback")

        monkeypatch.setattr(BarrierInstance, "get_barrier", boom)
        assert _visit_check_would_release(instance_id) is False
        _set_transaction_lock_timeout(0.3)
        assert db.session.execute(text("SELECT 1")).scalar() == 1
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_visit_check_would_release_rolls_back_peek_mutations(
    in_experiment_directory, db_session, monkeypatch
):
    """A mutating ``would_release`` override must not leak into the request."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"peek_mutate_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        original_progress = first.progress
        reconstructed = BarrierInstance.query.get(instance_id).get_barrier()

        def mutating(self, waiting):
            instance = BarrierInstance.query.get(instance_id)
            instance.active = False
            waiting[0].progress = original_progress + 1
            self.peek_mutated = True
            db.session.flush()
            return True

        monkeypatch.setattr(type(reconstructed), "would_release", mutating)
        assert _visit_check_would_release(instance_id) is True
        instance = BarrierInstance.query.get(instance_id)
        first = Participant.query.get(first.id)
        later = instance.get_barrier()
        assert instance.active is True
        assert first.progress == original_progress
        assert later is not reconstructed
        assert not getattr(later, "peek_mutated", False)
        _set_transaction_lock_timeout(0.3)
        assert db.session.execute(text("SELECT 1")).scalar() == 1
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_visit_check_would_release_db_error_keeps_the_session_usable(
    in_experiment_directory, db_session, monkeypatch
):
    """A failed peek must roll back its savepoint before the claim wait."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"peek_db_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id

        def boom(*args, **kwargs):
            db.session.execute(text("SELECT 1 FROM psynet_peek_missing_table"))

        monkeypatch.setattr("psynet.sync._get_waiting_participants", boom)
        assert _visit_check_would_release(instance_id) is True
        _set_transaction_lock_timeout(0.3)
        assert db.session.execute(text("SELECT 1")).scalar() == 1
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_visit_check_would_release_transient_error_propagates(
    in_experiment_directory, db_session, monkeypatch
):
    """A lock timeout during the peek must still become HTTP 503."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"peek_transient_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id

        class _Orig:
            pgcode = "55P03"

        def boom(*args, **kwargs):
            raise OperationalError("SELECT", {}, _Orig())

        monkeypatch.setattr("psynet.sync._get_waiting_participants", boom)
        with pytest.raises(OperationalError):
            _visit_check_would_release(instance_id)
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_waiter_get_spec_error_peek_returns_hold(
    in_experiment_directory, db_session, monkeypatch
):
    """GET must first-paint the hold when the peek hits a spec error."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"peek_get_spec_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)

        def boom(self):
            raise BarrierSpecError("missing callback")

        monkeypatch.setattr(BarrierInstance, "get_barrier", boom)
        response = _json_timeline(exp, first)
        assert response.status_code == 200
        assert response.get_json()["attributes"]["type"] == "_BarrierHoldPage"
        first = Participant.query.get(first.id)
        assert first.failed is False
    finally:
        exp.timeline = original_timeline


def test_resolve_get_timeline_hold_peeks_after_skip_ready(monkeypatch):
    """A ready-hold skip must not wait for the next visit unless it would release."""
    participant = SimpleNamespace(id=1)
    hold = SimpleNamespace(is_timeline_hold=True)
    experiment = SimpleNamespace(
        timeline=SimpleNamespace(get_current_elt=lambda e, p: hold),
    )
    seen = []
    monkeypatch.setattr("psynet.sync._take_pending_barrier_checks", lambda: [])
    monkeypatch.setattr(
        Experiment,
        "_timeline_hold_is_ready_to_resume",
        staticmethod(lambda *a, **k: True),
    )
    monkeypatch.setattr(
        Experiment,
        "_skip_ready_hold_on_get",
        classmethod(lambda cls, e, p: (p, hold, ["after-skip"])),
    )
    monkeypatch.setattr(
        "psynet.sync._pending_checks_should_wait_for_claim",
        lambda ids: seen.append(list(ids)) or False,
    )
    _, _, checks, wait = Experiment._resolve_get_timeline_hold(
        experiment, participant, hold
    )
    assert checks == ["after-skip"]
    assert wait is False
    assert seen == [["after-skip"]]


def test_finalize_barrier_arrivals_peeks_nested_checks_before_waiting(monkeypatch):
    """Stacked checks after a skip must peek before occupying a claim wait."""
    waits = []
    participant = SimpleNamespace(id=1)

    class Page:
        def __json__(self, participant):
            return {"participant_id": participant.id}

    page = Page()

    class Query:
        session = SimpleNamespace(execute=lambda statement: None)

        def with_for_update(self, **kwargs):
            return self

        def populate_existing(self):
            return self

        def get(self, participant_id):
            return participant

    experiment = SimpleNamespace(
        _participant_request_query=lambda: Query(),
        _advance_past_ready_holds=lambda participant, current_page: current_page,
        timeline=SimpleNamespace(get_current_elt=lambda experiment, participant: page),
    )
    result = SimpleNamespace(page=None, payload={})
    pending = {"nested": ["nested-id"]}

    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda seconds: None
    )
    monkeypatch.setattr(
        "psynet.sync._run_pending_barrier_checks",
        lambda checks, **kwargs: waits.append(kwargs.get("wait", True)) or True,
    )
    monkeypatch.setattr(
        "psynet.sync._take_pending_barrier_checks",
        lambda: pending.pop("nested", []),
    )
    monkeypatch.setattr(
        "psynet.sync._pending_checks_should_wait_for_claim",
        lambda ids: False,
    )
    monkeypatch.setattr(db.session, "commit", lambda: None)
    monkeypatch.setattr(db.session, "expire_all", lambda: None)

    Experiment._finalize_barrier_arrivals(
        experiment,
        participant_id=1,
        checks=["first-id"],
        result=result,
        wait_for_claim=True,
    )

    assert waits == [True, False]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_nested_rollback_keeps_pre_savepoint_barrier_queues(
    in_experiment_directory, db_session
):
    """A later instance's SAVEPOINT miss must not wipe an earlier skip's queues."""
    _queue_barrier_check("outer-id")
    _queue_released_hold_waiters([SimpleNamespace(id=1)])
    with pytest.raises(RuntimeError, match="boom"):
        with db.session.begin_nested():
            _queue_barrier_check("inner-id")
            _queue_released_hold_waiters([SimpleNamespace(id=2)])
            raise RuntimeError("boom")
    assert _take_pending_barrier_checks() == ["outer-id"]
    assert _take_released_hold_waiter_ids() == [1]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_and_skip_rereads_instance_after_a_release_peek(
    in_experiment_directory, db_session, monkeypatch
):
    """A claim wait must not evaluate the identity-map snapshot from the peek."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"peek_stale_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    checks = []
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        instance = BarrierInstance.query.get(instance_id)
        assert instance.active is True
        assert _visit_check_would_release(instance_id) is False
        monkeypatch.setattr(
            Barrier, "_check_instance", lambda self, check_id: checks.append(check_id)
        )
        with db.engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text(
                        "UPDATE participant_link_barrier "
                        "SET released = true "
                        "WHERE barrier_instance_id = :id"
                    ),
                    {"id": instance_id},
                )
                conn.execute(
                    text("UPDATE barrier_instance SET active = false WHERE id = :id"),
                    {"id": instance_id},
                )
        assert instance.active is True
        with _hold_barrier_instance_claim(instance_id, wait=False) as claimed:
            assert claimed is True
            assert _check_and_skip_held_instance(instance_id) is True
        assert checks == []
        db.session.expire_all()
        assert BarrierInstance.query.get(instance_id).active is False
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_nontransient_check_error_propagates(
    in_experiment_directory, db_session, monkeypatch
):
    """A deterministic last-arrival check failure must not first-paint a hold."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="last_arrival_boom", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)

    def boom(self, waiting_participants):
        raise RuntimeError("boom")

    monkeypatch.setattr(GroupBarrier, "check_waiting_participants", boom)
    with pytest.raises(RuntimeError, match="boom"):
        _commit_barrier_arrivals()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_spec_error_leaves_the_group_waiting(
    in_experiment_directory, db_session, monkeypatch
):
    """A malformed barrier spec must roll back the check and keep the group waiting."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="last_arrival_spec", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)

    def boom(_spec):
        raise BarrierSpecError("malformed spec")

    monkeypatch.setattr("psynet.sync.barrier_from_spec_json", boom)
    db.session.info.pop(_BARRIER_FROM_SPEC_CACHE_KEY, None)
    _commit_barrier_arrivals()
    db_session.refresh(first)
    db_session.refresh(last)
    assert first.failed is False
    assert last.failed is False
    assert _barrier_link_released(first.id, barrier.id) is False
    assert _barrier_link_released(last.id, barrier.id) is False


_group_release_calls = []


def _count_group_release(
    group, participants, participant=None, barrier=None, experiment=None
):
    _group_release_calls.append(group.id)


_left_at_release = []


def _record_who_left(left):
    _left_at_release.append([(p.id, p.sync_group_removal_reason("main")) for p in left])


def _custom_arrival_message(*, kind, waiting_count=None, group_size=None, **kwargs):
    return "custom"


def _sync_group_of(exp, db_session, n, group_type="main"):
    participants = [new_participant(exp) for _ in range(n)]
    for participant in participants:
        participant.status = "working"
    group = SimpleSyncGroup(
        group_type=group_type,
        initial_group_size=n,
        max_group_size=n,
        quorum=n,
        n_active_participants=n,
        accepts_top_ups=False,
    )
    db_session.add(group)
    for participant in participants:
        group.add_participant(participant)
    group.leader = participants[0]
    db_session.commit()
    return participants, group


def _pair_sync_group(exp, db_session, group_type="main"):
    return _sync_group_of(exp, db_session, 2, group_type)


def _set_group_clocks_in_the_past(group, seconds):
    """Pretend the group passed its last barrier, and its members joined, ``seconds`` ago."""
    past = timenow() - timedelta(seconds=seconds)
    group.last_barrier_pass_time = past
    for link in group.participant_links:
        link.arrival_time = past
        if link.admitted_at is not None:
            link.admitted_at = past


def _arrive_at_group_barrier(exp, barrier, participant):
    barrier.receive_participant(participant)
    if barrier._uses_timeline_hold:
        barrier.waiting_logic.consume(exp, participant)


def _commit_barrier_arrivals():
    """Mirror the response route's write and coordination commits."""
    db.session.commit()
    checks = _take_pending_barrier_checks()
    if checks:
        _run_pending_barrier_checks(checks)
        db.session.commit()


class _DummyFinalizePage:
    """Stand-in page so finalize tests do not depend on the consents timeline."""

    is_timeline_hold = False

    def pre_render(self):
        return None

    def __json__(self, participant):
        return {"participant_id": participant.id}


def _stub_finalize_timeline(experiment, page=None):
    """Keep finalize away from the host experiment's real timeline."""
    page = page or _DummyFinalizePage()
    experiment.timeline = SimpleNamespace(
        get_current_elt=lambda _experiment, _participant: page
    )
    experiment._advance_past_ready_holds = lambda participant, current_page: (
        current_page
    )
    return page


def _pause_group_barrier_checks(monkeypatch, barrier_id, started, finish, enabled):
    """Pause ``GroupBarrier`` checks so another session can observe held waiters."""
    original = GroupBarrier.check_waiting_participants

    def pausing(self, waiting_participants):
        original(self, waiting_participants)
        if self.id == barrier_id and enabled[0]:
            started.set()
            assert finish.wait(timeout=2)

    monkeypatch.setattr(GroupBarrier, "check_waiting_participants", pausing)


def _commit_arrival_write():
    """Commit the arrival write and return queued post-commit checks."""
    db.session.commit()
    return _take_pending_barrier_checks()


def _queued_last_arrival_checks(exp, barrier, first, last):
    """Arrive both group members and return checks for the last arrival only."""
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)
    return _commit_arrival_write()


def _run_finalize_in_thread(experiment, participant_id, checks, result):
    """Run ``_finalize_barrier_arrivals`` on a thread-local session."""
    errors = []

    def target():
        try:
            Experiment._finalize_barrier_arrivals(
                experiment,
                participant_id=participant_id,
                checks=checks,
                result=result,
            )
        except Exception as err:  # pragma: no cover - surfaced by the caller
            errors.append(err)
        finally:
            db.session.remove()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, errors


def test_finalize_barrier_arrivals_commits_checks_before_participant_relock(
    monkeypatch,
):
    """Barrier-wide participant locks must not span timeline advancement."""
    events = []
    participant = SimpleNamespace(id=1)

    class Page:
        def __json__(self, participant):
            return {"participant_id": participant.id}

    page = Page()

    class Query:
        session = SimpleNamespace(execute=lambda statement: None)

        def with_for_update(self, **kwargs):
            return self

        def populate_existing(self):
            return self

        def get(self, participant_id):
            events.append("participant_relock")
            assert events == ["check", "commit", "participant_relock"]
            return participant

    experiment = SimpleNamespace(
        _participant_request_query=lambda: Query(),
        _advance_past_ready_holds=lambda participant, current_page: current_page,
        timeline=SimpleNamespace(get_current_elt=lambda experiment, participant: page),
    )
    result = SimpleNamespace(page=None, payload={})

    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda seconds: None
    )
    monkeypatch.setattr(
        "psynet.sync._run_pending_barrier_checks",
        lambda checks, **_kwargs: events.append("check") or True,
    )
    monkeypatch.setattr("psynet.sync._take_pending_barrier_checks", lambda: [])
    monkeypatch.setattr(db.session, "commit", lambda: events.append("commit"))

    Experiment._finalize_barrier_arrivals(
        experiment,
        participant_id=1,
        checks=["instance"],
        result=result,
    )

    assert events == ["check", "commit", "participant_relock", "commit"]
    assert result.page is page
    assert result.payload["page"] == {"participant_id": 1}


def test_finalize_barrier_arrivals_does_not_relock_after_losing_claim(monkeypatch):
    """A peer that owns the check may keep participant rows locked."""
    events = []
    participant = SimpleNamespace(id=1)

    class Hold:
        is_timeline_hold = True

        def __json__(self, _participant):
            return "hold"

    hold = Hold()

    class Query:
        session = SimpleNamespace(execute=lambda statement: None)

        def with_for_update(self, **kwargs):
            events.append("participant_relock")
            return self

        def populate_existing(self):
            return self

        def get(self, participant_id):
            events.append("participant_read")
            return participant

    experiment = SimpleNamespace(
        _participant_request_query=lambda: Query(),
        _advance_past_ready_holds=lambda participant, current_page: current_page,
        timeline=SimpleNamespace(
            get_current_elt=lambda _experiment, _participant: hold
        ),
    )
    result = SimpleNamespace(page=hold, payload={"page": "stale"})

    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda seconds: None
    )
    monkeypatch.setattr(
        "psynet.sync._run_pending_barrier_checks",
        lambda checks, **_kwargs: events.append("check") or False,
    )
    monkeypatch.setattr(db.session, "commit", lambda: events.append("commit"))

    returned = Experiment._finalize_barrier_arrivals(
        experiment,
        participant_id=1,
        checks=["instance"],
        result=result,
    )

    assert returned is participant
    assert events == [
        "check",
        "commit",
        "check",
        "commit",
        "participant_relock",
        "participant_read",
        "commit",
    ]
    assert result.page is hold
    assert result.payload == {"page": "hold"}


def test_finalize_barrier_arrivals_uses_later_hold_after_lost_claim(monkeypatch):
    """If the winner skipped to the next hold, the loser must not first-paint the old one."""
    events = []
    participant = SimpleNamespace(id=1)

    class NextHold:
        is_timeline_hold = True

        def __json__(self, _participant):
            return {"label": "next_hold"}

    page = NextHold()

    class Query:
        session = SimpleNamespace(execute=lambda statement: None)

        def with_for_update(self, **kwargs):
            events.append("participant_relock")
            return self

        def populate_existing(self):
            return self

        def get(self, participant_id):
            events.append("participant_read")
            return participant

    experiment = SimpleNamespace(
        _participant_request_query=lambda: Query(),
        _advance_past_ready_holds=lambda participant, current_page: current_page,
        timeline=SimpleNamespace(
            get_current_elt=lambda _experiment, _participant: page
        ),
    )
    result = SimpleNamespace(page=object(), payload={"page": "old_hold"})

    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda seconds: None
    )
    monkeypatch.setattr(
        "psynet.sync._run_pending_barrier_checks",
        lambda checks, **_kwargs: events.append("check") or False,
    )
    monkeypatch.setattr(db.session, "commit", lambda: events.append("commit"))

    returned = Experiment._finalize_barrier_arrivals(
        experiment,
        participant_id=1,
        checks=["instance"],
        result=result,
    )

    assert returned is participant
    assert events == [
        "check",
        "commit",
        "check",
        "commit",
        "participant_relock",
        "participant_read",
        "commit",
    ]
    assert result.page is page
    assert result.payload["page"] == {"label": "next_hold"}


def test_finalize_barrier_arrivals_uses_already_advanced_page_after_lost_claim(
    monkeypatch,
):
    """If the winner already left the hold, the loser must not first-paint it."""
    events = []
    participant = SimpleNamespace(id=1)

    class Page:
        is_timeline_hold = False

        def __json__(self, _participant):
            return {"label": "choose_action"}

    page = Page()

    class Query:
        session = SimpleNamespace(execute=lambda statement: None)

        def with_for_update(self, **kwargs):
            events.append("participant_relock")
            return self

        def populate_existing(self):
            return self

        def get(self, participant_id):
            events.append("participant_read")
            return participant

    experiment = SimpleNamespace(
        _participant_request_query=lambda: Query(),
        _advance_past_ready_holds=lambda participant, current_page: current_page,
        timeline=SimpleNamespace(
            get_current_elt=lambda _experiment, _participant: page
        ),
    )
    result = SimpleNamespace(page=object(), payload={"page": "hold"})

    monkeypatch.setattr(
        "psynet.experiment._set_transaction_lock_timeout", lambda seconds: None
    )
    monkeypatch.setattr(
        "psynet.sync._run_pending_barrier_checks",
        lambda checks, **_kwargs: events.append("check") or False,
    )
    monkeypatch.setattr(db.session, "commit", lambda: events.append("commit"))

    returned = Experiment._finalize_barrier_arrivals(
        experiment,
        participant_id=1,
        checks=["instance"],
        result=result,
    )

    assert returned is participant
    assert events == [
        "check",
        "commit",
        "check",
        "commit",
        "participant_relock",
        "participant_read",
        "commit",
    ]
    assert result.page is page
    assert result.payload["page"] == {"label": "choose_action"}


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_finalize_does_not_wait_on_locked_waiter_rows(
    in_experiment_directory, db_session
):
    """Last-arrival waits for the instance claim, then uses waiter ``NOWAIT``.

    A partner ``POST`` can hold a waiter row without owning the visit claim.
    That request must fail the waiter lock immediately rather than sit in
    ``lock_timeout``. Losing the waiter lock may still first-paint a hold;
    the poller finishes the skip.
    """
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    first_id = first.id
    last_id = last.id
    barrier = GroupBarrier(id_="finalize_nowait_waiters", group_type="main")
    hold_page = SimpleNamespace(is_timeline_hold=True)
    hold_page.__json__ = lambda _participant: {"label": "hold"}
    exp.timeline = SimpleNamespace(get_current_elt=lambda _e, _p: hold_page)
    exp._advance_past_ready_holds = lambda participant, current_page: current_page
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    result = SimpleNamespace(page=object(), payload={"page": "stale"})

    with db.engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
                {"id": first_id},
            )
            started_at = time.perf_counter()
            Experiment._finalize_barrier_arrivals(
                exp,
                participant_id=last_id,
                checks=checks,
                result=result,
            )
            elapsed = time.perf_counter() - started_at
        finally:
            trans.rollback()

    assert elapsed < 1
    assert result.page is hold_page
    assert result.payload["page"] == {"label": "hold"}
    assert _barrier_link_released(first_id, barrier.id) is False
    assert _barrier_link_released(last_id, barrier.id) is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_finalize_drops_partner_locks_before_submitter_relock(
    in_experiment_directory, db_session
):
    """Partner rows must be free once the winner advances its own timeline."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    first_id = first.id
    last_id = last.id
    barrier = GroupBarrier(id_="finalize_drop_partner_locks", group_type="main")
    page = _DummyFinalizePage()
    exp.timeline = SimpleNamespace(get_current_elt=lambda _e, _p: page)
    locks = []

    def advance(participant, current_page):
        locks.append(
            {
                "partner": _participant_row_is_locked(first_id),
                "submitter": _participant_row_is_locked(last_id),
            }
        )
        return current_page

    exp._advance_past_ready_holds = advance
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    result = SimpleNamespace(page=object(), payload={})

    Experiment._finalize_barrier_arrivals(
        exp,
        participant_id=last_id,
        checks=checks,
        result=result,
    )

    assert locks == [{"partner": False, "submitter": True}]
    assert result.page is page
    assert _barrier_link_released(first_id, barrier.id) is True
    assert _barrier_link_released(last_id, barrier.id) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_finalize_self_skips_without_holding_partner_rows(
    in_experiment_directory, db_session
):
    """Last-arrival drops partner FOR UPDATE locks and only self-skips.

    Partners leave on overlay wake. This request relocks the submitter after
    the check commit and does not take partner rows again.
    """
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    first_id, last_id = first.id, last.id
    barrier = GroupBarrier(id_="finalize_skip_waiters", group_type="main")
    hold_page = SimpleNamespace(
        is_timeline_hold=True,
        hold_id="skip_waiters",
        __json__=lambda _participant: {"label": "hold"},
    )
    exp.timeline = SimpleNamespace(get_current_elt=lambda _e, _p: hold_page)
    locks = []

    def advance(participant, current_page):
        locks.append(
            {
                "participant_id": participant.id,
                "first_locked": _participant_row_is_locked(first_id),
                "last_locked": _participant_row_is_locked(last_id),
            }
        )
        return current_page

    exp._advance_past_ready_holds = advance
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    result = SimpleNamespace(page=object(), payload={})

    Experiment._finalize_barrier_arrivals(
        exp,
        participant_id=last_id,
        checks=checks,
        result=result,
    )

    assert [row["participant_id"] for row in locks] == [last_id]
    assert locks[0] == {
        "participant_id": last_id,
        "first_locked": False,
        "last_locked": True,
    }
    assert _barrier_link_released(first_id, barrier.id) is True
    assert _barrier_link_released(last_id, barrier.id) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_finalize_relock_after_check_commit_is_bounded(
    in_experiment_directory, db_session, monkeypatch
):
    """Relocking the submitter must use lock_timeout after the check commit."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    last_id = last.id
    barrier = GroupBarrier(id_="finalize_bounded_relock", group_type="main")
    _stub_finalize_timeline(exp)
    monkeypatch.setattr(
        "psynet.experiment.get_config",
        lambda: SimpleNamespace(get=lambda key, **_kwargs: 0.2),
    )
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    result = SimpleNamespace(page=object(), payload={})
    real_commit = db.session.commit
    held = []
    blocker = db.engine.connect()
    blocker_trans = blocker.begin()

    def commit_then_hold_submitter():
        real_commit()
        if not held:
            held.append(True)
            blocker.execute(
                text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
                {"id": last_id},
            )

    monkeypatch.setattr(db.session, "commit", commit_then_hold_submitter)
    try:
        started_at = time.perf_counter()
        with pytest.raises(OperationalError) as excinfo:
            Experiment._finalize_barrier_arrivals(
                exp,
                participant_id=last_id,
                checks=checks,
                result=result,
            )
        elapsed = time.perf_counter() - started_at
        db.session.rollback()
    finally:
        blocker_trans.rollback()
        blocker.close()

    assert elapsed < 1.5
    assert Experiment._is_transient_transaction_error(excinfo.value)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_partner_timeline_lock_times_out_during_in_flight_check(
    in_experiment_directory, db_session, monkeypatch
):
    """Partner ``/timeline`` FOR UPDATE stays bounded while a check holds waiters."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    first_unique_id = first.unique_id
    barrier = GroupBarrier(id_="finalize_timeline_busy", group_type="main")
    started = threading.Event()
    finish = threading.Event()
    enabled = [False]
    _pause_group_barrier_checks(monkeypatch, barrier.id, started, finish, enabled)
    _stub_finalize_timeline(exp)
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    enabled[0] = True
    result = SimpleNamespace(page=object(), payload={"page": "hold"})
    winner, winner_errors = _run_finalize_in_thread(exp, last.id, checks, result)
    assert started.wait(timeout=2)

    _set_transaction_lock_timeout(0.2)
    started_at = time.perf_counter()
    with pytest.raises(OperationalError) as excinfo:
        Experiment._get_request_participant_from_unique_id(
            first_unique_id, for_update=True
        )
    elapsed = time.perf_counter() - started_at
    db.session.rollback()
    finish.set()
    winner.join(timeout=2)

    assert elapsed < 1.5
    assert Experiment._is_transient_transaction_error(excinfo.value)
    assert winner_errors == []
    assert not winner.is_alive()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_process_response_does_not_wait_when_participant_row_is_locked(
    in_experiment_directory, db_session
):
    """A hold-resume must not sit in lock_timeout while last-arrival holds the row."""
    exp = get_experiment()
    participant = new_participant(exp)
    db.session.commit()
    participant_id = participant.id
    page_uuid = participant.page_uuid
    db.session.expire_all()

    with db.engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
                {"id": participant_id},
            )
            started_at = time.perf_counter()
            with pytest.raises(OperationalError) as excinfo:
                exp.process_response(
                    participant_id,
                    None,
                    {},
                    {},
                    page_uuid,
                    "127.0.0.1",
                    timeline_hold_resume=True,
                )
            elapsed = time.perf_counter() - started_at
        finally:
            trans.rollback()

    assert elapsed < 0.5
    assert Experiment._is_transient_transaction_error(excinfo.value)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_unready_hold_resume_does_not_lock_the_waiter_row(
    in_experiment_directory, db_session
):
    """A still-waiting overlay check must not hold ``FOR UPDATE``.

    Last-arrival locks waiters with ``NOWAIT``. If this POST kept the row,
    that query would fail for the whole group and leave partners on the
    overlay until the poller.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"unready_resume_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        first_id = first.id
        hold_uuid = first.page_uuid
        assert getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )

        resumed = _process_response(exp, first, hold_uuid, timeline_hold_resume=True)
        assert resumed.payload["submission"] == "approved"
        assert getattr(resumed.page, "is_timeline_hold", False)
        assert resumed.skip_write is True
        assert not _participant_row_is_locked(first_id)
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_route_response_unready_hold_resume_rolls_back_identity_map_dirties(
    in_experiment_directory, db_session
):
    """``skip_write`` must drop overlay dirties before the route's outer commit.

    Isolated tests usually call ``process_response``. ``get_current_elt`` can
    dirty ``elt_id_max``; without rollback, ``with_transaction`` would commit
    that and wait accounting. Inject a dirty so this POST proves the route
    rolls it back.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"unready_route_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    original_get = exp.timeline.get_current_elt
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        first_id = first.id
        hold_uuid = first.page_uuid
        credit_before = first.time_credit
        wait_before = first.total_wait_page_time
        elt_max_before = list(first.elt_id_max or [])
        record = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=hold_uuid
        ).one()
        actual_before = record.actual_wait_seconds

        def dirtying_get(experiment, participant):
            page = original_get(experiment, participant)
            participant.time_credit = (participant.time_credit or 0.0) + 99
            participant.total_wait_page_time = (
                participant.total_wait_page_time or 0.0
            ) + 99
            participant.elt_id_max = list(participant.elt_id_max or []) + [99]
            participant.client_ip_address = "9.9.9.9"
            return page

        exp.timeline.get_current_elt = dirtying_get
        response = _route_hold_resume(first_id, hold_uuid)
        assert response.status_code == 200
        body = json.loads(response.get_data())
        assert body["status"] == "success"
        assert body["submission"] == "approved"
        db.session.expire_all()
        first = Participant.query.get(first_id)
        assert first.time_credit == credit_before
        assert first.total_wait_page_time == wait_before
        assert list(first.elt_id_max or []) == elt_max_before
        assert first.client_ip_address != "9.9.9.9"
        record = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=hold_uuid
        ).one()
        assert record.actual_wait_seconds == actual_before
        assert not _participant_row_is_locked(first_id)
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_releases_waiters_during_unready_hold_resume(
    in_experiment_directory, db_session, monkeypatch
):
    """Last-arrival must still lock and release waiters during an overlay check.

    Pause the still-waiting hold-resume after the unlocked readiness check.
    If that POST took ``FOR UPDATE``, waiter ``NOWAIT`` would fail and this
    GET would first-paint a hold instead of self-skipping the released wait.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"unready_overlap_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    resume_started = threading.Event()
    resume_finish = threading.Event()
    resume_result = []
    resume_errors = []
    original_unready = Experiment._unready_hold_resume_result

    def pausing_unready(self, participant, page_uuid):
        result = original_unready(self, participant, page_uuid)
        if result is not None:
            resume_started.set()
            assert resume_finish.wait(timeout=5)
        return result

    monkeypatch.setattr(Experiment, "_unready_hold_resume_result", pausing_unready)
    resume_thread = None
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        first_id = first.id
        last_id = last.id
        last_uid = last.unique_id
        hold_uuid = first.page_uuid
        assert getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )

        def hold_resume():
            try:
                participant = Participant.query.get(first_id)
                resume_result.append(
                    _process_response(
                        exp, participant, hold_uuid, timeline_hold_resume=True
                    )
                )
            except Exception as err:  # pragma: no cover - surfaced by the caller
                resume_errors.append(err)
            finally:
                db.session.remove()

        resume_thread = threading.Thread(target=hold_resume, daemon=True)
        resume_thread.start()
        assert resume_started.wait(timeout=2)
        assert not _participant_row_is_locked(first_id)

        last = Participant.query.filter_by(unique_id=last_uid).one()
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        _assert_left_hold_uuid(last_id, hold_uuid)
        _assert_cursor_unchanged(first_id, hold_uuid)
        assert not _participant_row_is_locked(first_id)
        assert not _participant_row_is_locked(last_id)
    finally:
        resume_finish.set()
        if resume_thread is not None:
            resume_thread.join(timeout=5)
        exp.timeline = original_timeline

    assert resume_errors == []
    assert resume_thread is not None
    assert not resume_thread.is_alive()
    assert len(resume_result) == 1
    resumed = resume_result[0]
    assert resumed.payload["submission"] == "approved"
    assert getattr(resumed.page, "is_timeline_hold", False)
    assert resumed.skip_write is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_ready_partner_overlay_advances_after_last_arrival_release(
    in_experiment_directory, db_session, monkeypatch
):
    """A released overlay POST advances the partner; last-arrival does not.

    Pause last-arrival while it self-skips after the release commit. The
    overlay then looks ready because ``active_barriers`` no longer contains
    the link, takes ``FOR UPDATE``, and catch-up-skips this waiter.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    original_advance = Experiment._advance_past_ready_holds
    group_type = f"ready_overlap_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    released = threading.Event()
    last_may_finish = threading.Event()
    last_id_holder = {}

    def pausing_advance(self, participant, page):
        if (
            last_id_holder.get("id") is not None
            and participant.id == last_id_holder["id"]
            and not released.is_set()
        ):
            released.set()
            assert last_may_finish.wait(timeout=5)
        return original_advance(self, participant, page)

    monkeypatch.setattr(Experiment, "_advance_past_ready_holds", pausing_advance)
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        first_id = first.id
        last_id = last.id
        last_id_holder["id"] = last_id
        last_uid = last.unique_id
        hold_uuid = first.page_uuid
        thread, result, errors = _route_timeline_in_thread(exp, last_uid)
        assert released.wait(timeout=5)
        first = Participant.query.get(first_id)
        page = exp.timeline.get_current_elt(exp, first)
        assert page.is_ready_to_resume(exp, first)
        assert _hold_instance_id_for_page(first, page) is None
        _assert_cursor_unchanged(first_id, hold_uuid)
        resumed = _route_hold_resume(first_id, hold_uuid)
        assert resumed.status_code == 200
        body = json.loads(resumed.get_data())
        assert body["submission"] == "approved"
        last_may_finish.set()
        thread.join(timeout=5)
        assert errors == []
        assert not thread.is_alive()
        assert result.get("status") == 200
        _assert_left_hold_uuid(first_id, hold_uuid)
        _catch_up_until_action(exp, [first_id, last_id])
    finally:
        last_may_finish.set()
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_ready_hold_resume_does_not_wait_when_participant_row_is_locked(
    in_experiment_directory, db_session, monkeypatch
):
    """A hold that can resume must fail the waiter lock immediately.

    Timed-out and already-released overlays still take ``FOR UPDATE NOWAIT``.
    Blocking here would freeze a worker behind last-arrival's ``lock_timeout``.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"ready_resume_nowait_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, _last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        participant_id = first.id
        hold_uuid = first.page_uuid
        assert getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )
        monkeypatch.setattr(
            _TimelineHoldPage,
            "is_ready_to_resume",
            lambda self, experiment, participant: True,
        )
        db.session.expire_all()

        with db.engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(
                    text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
                    {"id": participant_id},
                )
                started_at = time.perf_counter()
                with pytest.raises(OperationalError) as excinfo:
                    _process_response(
                        exp,
                        SimpleNamespace(id=participant_id),
                        hold_uuid,
                        timeline_hold_resume=True,
                    )
                elapsed = time.perf_counter() - started_at
            finally:
                trans.rollback()

        assert elapsed < 0.5
        assert Experiment._is_transient_transaction_error(excinfo.value)
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_two_response_finalizers_claim_one_barrier_instance(
    in_experiment_directory, db_session
):
    """Concurrent ``/response`` finalizers must not double-release or hang."""
    exp = get_experiment()
    participants, group = _pair_sync_group(exp, db_session)
    first, last = participants
    group_id = group.id
    _group_release_calls.clear()
    barrier = GroupBarrier(
        id_="finalize_two_requests",
        group_type="main",
        on_release=_count_group_release,
    )
    page = _stub_finalize_timeline(exp)
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    first_hold = object()
    last_hold = object()
    first_result = SimpleNamespace(page=first_hold, payload={"page": "hold"})
    last_result = SimpleNamespace(page=last_hold, payload={"page": "hold"})

    first_thread, first_errors = _run_finalize_in_thread(
        exp, first.id, checks, first_result
    )
    last_thread, last_errors = _run_finalize_in_thread(
        exp, last.id, checks, last_result
    )
    first_thread.join(timeout=2)
    last_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not last_thread.is_alive()
    assert first_errors == []
    assert last_errors == []
    assert _group_release_calls == [group_id]
    advanced = [result for result in (first_result, last_result) if result.page is page]
    assert len(advanced) >= 1
    assert _barrier_link_released(first.id, barrier.id) is True
    assert _barrier_link_released(last.id, barrier.id) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_check_does_not_skip_released_waiters(
    in_experiment_directory, db_session
):
    """A last-arrival barrier check releases links without advancing partners."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="release_then_skip", group_type="main")
    advanced = []
    exp.timeline = SimpleNamespace(
        get_current_elt=lambda _experiment, participant: barrier.waiting_logic
    )
    exp._advance_past_ready_holds = lambda participant, page: (
        advanced.append(participant.id) or page
    )

    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)
    _commit_barrier_arrivals()

    assert advanced == []
    assert _barrier_link_released(first.id, barrier.id) is True
    assert _barrier_link_released(last.id, barrier.id) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_timeline_finalizes_queued_arrivals_before_render(
    in_experiment_directory, db_session
):
    """The last arriver's first ``/timeline`` paint must run the fast release."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="timeline_finalize", group_type="main")
    page = _stub_finalize_timeline(exp)
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)
    db.session.commit()

    returned_participant, returned_page = (
        Experiment._finalize_pending_timeline_barriers(exp, last, barrier.waiting_logic)
    )

    assert returned_participant.id == last.id
    assert returned_page is page
    assert _barrier_link_released(first.id, barrier.id) is True
    assert _barrier_link_released(last.id, barrier.id) is True


def _explode_on_release(
    group, participants, participant=None, barrier=None, experiment=None
):
    raise RuntimeError("on_release boom")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_on_release_error_leaves_the_group_waiting(
    in_experiment_directory, db_session
):
    """A last-arrival hook failure must not fail the arriver or release waiters."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(
        id_="release_error",
        group_type="main",
        on_release=_explode_on_release,
    )
    page = _stub_finalize_timeline(exp)
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    result = SimpleNamespace(page=page, payload={})

    Experiment._finalize_barrier_arrivals(
        exp,
        participant_id=last.id,
        checks=checks,
        result=result,
    )
    db.session.commit()

    db.session.refresh(first)
    db.session.refresh(last)
    assert first.failed is False
    assert last.failed is False
    assert _barrier_link_released(first.id, barrier.id) is False
    assert _barrier_link_released(last.id, barrier.id) is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_participant_link_barrier_lists_waiting_participants(
    in_experiment_directory, db_session
):
    """Custom waiting pages can list waiters from the visit link, as demos do."""
    exp = get_experiment()
    first = new_participant(exp)
    second = new_participant(exp)
    first.status = "working"
    second.status = "working"
    db.session.commit()
    grouper = SimpleGrouper(group_type="waitlist", initial_group_size=3, quorum=3)
    _arrive_at_group_barrier(exp, grouper, first)
    db.session.commit()

    link = first.active_barriers.get("waitlist_grouper_3")
    assert link is not None
    assert link.get_waiting_participants() == [first]
    assert grouper.get_waiting_participants(first) == [first]
    assert grouper.get_waiting_participants() == [first]
    assert grouper.get_waiting_participants(second) == []
    with pytest.raises(TypeError, match="for_update"):
        grouper.get_waiting_participants(True)
    with pytest.raises(TypeError):
        link.get_waiting_participants(True)
    pair_first, _pair_last = _pair_sync_group(exp, db_session)[0]
    grouped = GroupBarrier(id_="needs_visit", group_type="main")
    with pytest.raises(TypeError, match="needs a participant"):
        grouped.get_waiting_participants()
    _arrive_at_group_barrier(exp, grouped, pair_first)
    db.session.commit()
    assert grouped.get_waiting_participants(pair_first) == [pair_first]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_arrival_requires_active_sync_group(
    in_experiment_directory, db_session
):
    participant = new_participant(get_experiment())
    participant.status = "working"
    db_session.commit()
    barrier = GroupBarrier(id_="needs_group", group_type="main")

    with pytest.raises(RuntimeError, match="is not in a sync group"):
        BarrierInstance.for_arrival(barrier, participant)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_closed_group_needs_a_new_grouper(in_experiment_directory, db_session):
    """After a GroupCloser, a barrier of that type needs a new group, even after an earlier removal."""
    (first, *_), group = _sync_group_of(get_experiment(), db_session, 3)
    group.remove_participant(first, reason="late")
    db_session.commit()
    assert _removed_from_group(first, "main")

    regrouped = SimpleSyncGroup(
        group_type="main", initial_group_size=1, accepts_top_ups=False
    )
    db_session.add(regrouped)
    regrouped.add_participant(first)
    regrouped.close()
    db_session.commit()
    assert not _removed_from_group(first, "main")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_unloaded_sync_groups_omit_arrival_updates(
    in_experiment_directory, db_session, monkeypatch
):
    """Ungrouped request participants skip the partner-ready websocket."""
    participant = new_participant(get_experiment())
    db_session.commit()
    unique_id = participant.unique_id
    db.session.remove()

    participant = get_experiment()._get_request_participant_from_unique_id(unique_id)
    assert "sync_group_links" in sa_inspect(participant).unloaded

    def boom(_participant):
        raise AssertionError("should not look up arrival notices")

    monkeypatch.setattr("psynet.sync.pending_arrival_notice_for", boom)
    page = Page(template_fragment_str="<p>Solo page</p>")
    assert "arrival_updates" not in page.attributes(participant)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_unloaded_grouped_page_includes_arrival_updates(
    in_experiment_directory, db_session
):
    """Grouped pages still subscribe when request loading left links lazy."""
    first, _last = _pair_sync_group(get_experiment(), db_session)[0]
    unique_id = first.unique_id
    db.session.remove()

    participant = get_experiment()._get_request_participant_from_unique_id(unique_id)
    assert "sync_group_links" in sa_inspect(participant).unloaded
    page = Page(template_fragment_str="<p>Grouped page</p>")
    updates = page.attributes(participant)["arrival_updates"]
    assert updates["channel"] == _timeline_hold_channel(participant.id)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_has_active_sync_group_is_memoized(in_experiment_directory, db_session):
    """Page render must not repeat the grouped-page membership EXISTS."""
    db.session.info.pop(_HAS_ACTIVE_SYNC_GROUP_ATTR, None)
    first, _last = _pair_sync_group(get_experiment(), db_session)[0]
    assert _has_active_sync_group(first) is True
    with assert_query_count(max_queries=0):
        assert _has_active_sync_group(first) is True

    ungrouped = new_participant(get_experiment())
    db_session.commit()
    assert _has_active_sync_group(ungrouped) is False
    with assert_query_count(max_queries=0):
        assert _has_active_sync_group(ungrouped) is False

    other = Participant.query.get(first.id)
    with assert_query_count(max_queries=0):
        assert _has_active_sync_group(other) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_closing_a_sync_group_forgets_membership_memo(
    in_experiment_directory, db_session
):
    """Closed groups must not keep page render on a stale membership memo."""
    db.session.info.pop(_HAS_ACTIVE_SYNC_GROUP_ATTR, None)
    first, _last = _pair_sync_group(get_experiment(), db_session)[0]
    group = first.sync_group
    assert _has_active_sync_group(first) is True
    group.close()
    assert _has_active_sync_group(first) is False
    with assert_query_count(max_queries=0):
        assert _has_active_sync_group(first) is False


def test_check_claimed_barrier_instance_treats_finished_work_as_success():
    """A completed or missing instance is not a lost in-flight claim."""
    assert _check_claimed_barrier_instance(None) is True
    assert (
        _check_claimed_barrier_instance(SimpleNamespace(active=False, id="done"))
        is True
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_inactive_grouped_instance_with_waiters_is_still_checked(
    in_experiment_directory, db_session
):
    """An inactive grouped visit must run again if working waiters remain."""
    exp = get_experiment()
    first, _last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="reactivate", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    db.session.commit()
    instance = BarrierInstance.query.filter_by(barrier_id=barrier.id).one()
    instance.active = False
    db.session.commit()
    instance = BarrierInstance.query.get(instance.id)
    assert instance.active is False
    assert _check_claimed_barrier_instance(instance) is True
    db.session.commit()
    instance = BarrierInstance.query.get(instance.id)
    assert instance.active is True
    assert _barrier_link_released(first.id, barrier.id) is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_for_arrival_reactivates_inactive_instance_with_waiters(
    in_experiment_directory, db_session
):
    """A leftover waiter must keep the same visit instead of opening a second pool."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="reuse_inactive", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    db.session.commit()
    instance = BarrierInstance.query.filter_by(barrier_id=barrier.id).one()
    instance_id = instance.id
    instance.active = False
    db.session.commit()

    recovered = BarrierInstance.for_arrival(barrier, last)
    assert recovered.id == instance_id
    assert recovered.active is True
    assert BarrierInstance.query.filter_by(barrier_id=barrier.id).count() == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_instance_does_not_reactivate_when_another_pool_is_active(
    in_experiment_directory, db_session
):
    """Leftover waiters on an inactive visit must not steal a newer active pool."""
    exp = get_experiment()
    first, _last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="split_pool", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    db.session.commit()
    leftover = BarrierInstance.query.filter_by(barrier_id=barrier.id).one()
    leftover.active = False
    db.session.commit()
    newer = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id=leftover.barrier_id,
        group_id=leftover.group_id,
        active=True,
        spec=leftover.spec,
        behavior_hash=leftover.behavior_hash,
    )
    db.session.add(newer)
    db.session.commit()

    leftover = BarrierInstance.query.get(leftover.id)
    assert leftover.active is False
    assert _check_claimed_barrier_instance(leftover) is True
    db.session.commit()
    leftover = BarrierInstance.query.get(leftover.id)
    newer = BarrierInstance.query.get(newer.id)
    first = Participant.query.get(first.id)
    assert leftover.active is False
    assert newer.active is True
    assert _barrier_link_released(first.id, barrier.id) is False
    assert first.active_barriers[barrier.id].barrier_instance_id == newer.id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_leftover_check_evaluates_the_live_instance_barrier(
    in_experiment_directory, db_session, monkeypatch
):
    """Migrated leftover waiters must be released with the live visit's spec."""
    exp = get_experiment()
    first, _last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="split_pool_live_spec", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    db.session.commit()
    leftover = BarrierInstance.query.filter_by(barrier_id=barrier.id).one()
    leftover.active = False
    db.session.commit()
    newer = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id=leftover.barrier_id,
        group_id=leftover.group_id,
        active=True,
        spec=leftover.spec,
        behavior_hash=leftover.behavior_hash,
    )
    db.session.add(newer)
    db.session.commit()

    reconstructed = []
    original = BarrierInstance.get_barrier

    def tracking_get(self):
        reconstructed.append(self.id)
        return original(self)

    monkeypatch.setattr(BarrierInstance, "get_barrier", tracking_get)
    leftover = BarrierInstance.query.get(leftover.id)
    newer_id = newer.id
    leftover_id = leftover.id
    assert _check_claimed_barrier_instance(leftover) is True
    assert reconstructed[0] == leftover_id
    assert reconstructed[-1] == newer_id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_get_barrier_reuses_session_reconstruction(
    in_experiment_directory, db_session, monkeypatch
):
    """Grouped-page render must not re-parse the same visit spec."""
    exp = get_experiment()
    first, _last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="cache_spec", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    db.session.commit()
    instance = BarrierInstance.query.filter_by(barrier_id=barrier.id).one()
    db.session.info.pop(_BARRIER_FROM_SPEC_CACHE_KEY, None)
    reconstructed = []
    original = barrier_from_spec_json

    def tracking(serialized):
        reconstructed.append(serialized)
        return original(serialized)

    monkeypatch.setattr("psynet.sync.barrier_from_spec_json", tracking)
    first_barrier = instance.get_barrier()
    second_barrier = instance.get_barrier()
    assert first_barrier is second_barrier
    assert len(reconstructed) == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_ungrouped_instance_clears_active_so_later_behavior_can_reuse_the_id(
    in_experiment_directory, db_session
):
    """Empty ungrouped visits must not keep the first arrival's behavior hash."""
    exp = get_experiment()
    first_wave = [new_participant(exp) for _ in range(3)]
    second_wave = [new_participant(exp) for _ in range(2)]
    for participant in first_wave + second_wave:
        participant.status = "working"
    db.session.commit()
    first_grouper = SimpleGrouper(
        group_type="regroup_sizes",
        initial_group_size=3,
        quorum=3,
        id_="regroup_sizes_grouper",
    )
    for participant in first_wave:
        _arrive_at_group_barrier(exp, first_grouper, participant)
        _commit_barrier_arrivals()
    instance = BarrierInstance.query.filter_by(barrier_id="regroup_sizes_grouper").one()
    assert instance.active is False
    db.session.expire_all()
    group = Participant.query.get(first_wave[0].id).sync_group
    assert group is not None
    assert {
        Participant.query.get(participant.id).sync_group.id
        for participant in first_wave
    } == {group.id}
    group.close()
    db.session.commit()
    second_grouper = SimpleGrouper(
        group_type="regroup_sizes",
        initial_group_size=2,
        id_="regroup_sizes_grouper",
    )
    _arrive_at_group_barrier(exp, second_grouper, second_wave[0])
    _commit_barrier_arrivals()
    instances = BarrierInstance.query.filter_by(
        barrier_id="regroup_sizes_grouper"
    ).all()
    assert len(instances) == 2
    active = [row for row in instances if row.active]
    assert len(active) == 1
    assert active[0].id != instance.id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_for_arrival_reactivates_inactive_ungrouped_instance_with_waiters(
    in_experiment_directory, db_session
):
    """A leftover ungrouped waiter must keep the same visit instead of opening a second pool."""
    exp = get_experiment()
    first, last = [new_participant(exp) for _ in range(2)]
    for participant in (first, last):
        participant.status = "working"
    db.session.commit()
    grouper = SimpleGrouper(
        group_type="reuse_ungrouped", initial_group_size=3, quorum=3
    )
    _arrive_at_group_barrier(exp, grouper, first)
    db.session.commit()
    instance = BarrierInstance.query.filter_by(
        barrier_id="reuse_ungrouped_grouper_3"
    ).one()
    instance_id = instance.id
    instance.active = False
    db.session.commit()

    recovered = BarrierInstance.for_arrival(grouper, last)
    assert recovered.id == instance_id
    assert recovered.active is True
    assert (
        BarrierInstance.query.filter_by(barrier_id="reuse_ungrouped_grouper_3").count()
        == 1
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_instance_does_not_reactivate_ungrouped_when_another_pool_is_active(
    in_experiment_directory, db_session
):
    """Leftover ungrouped waiters must not steal a newer active pool."""
    exp = get_experiment()
    first = new_participant(exp)
    first.status = "working"
    db.session.commit()
    grouper = SimpleGrouper(
        group_type="split_ungrouped", initial_group_size=3, quorum=3
    )
    _arrive_at_group_barrier(exp, grouper, first)
    db.session.commit()
    leftover = BarrierInstance.query.filter_by(
        barrier_id="split_ungrouped_grouper_3"
    ).one()
    leftover.active = False
    db.session.commit()
    newer = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id=leftover.barrier_id,
        group_id=None,
        active=True,
        spec=leftover.spec,
        behavior_hash=leftover.behavior_hash,
    )
    db.session.add(newer)
    db.session.commit()

    leftover = BarrierInstance.query.get(leftover.id)
    assert leftover.active is False
    assert _check_claimed_barrier_instance(leftover) is True
    db.session.commit()
    leftover = BarrierInstance.query.get(leftover.id)
    newer = BarrierInstance.query.get(newer.id)
    first = Participant.query.get(first.id)
    assert leftover.active is False
    assert newer.active is True
    assert _barrier_link_released(first.id, "split_ungrouped_grouper_3") is False
    assert first.active_barriers["split_ungrouped_grouper_3"].barrier_instance_id == (
        newer.id
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_leftover_check_defers_to_an_arrival_creating_the_pool(
    in_experiment_directory, db_session
):
    """Reactivating a leftover must not race an arrival that is opening the pool."""
    exp = get_experiment()
    first = new_participant(exp)
    first.status = "working"
    db.session.commit()
    grouper = SimpleGrouper(group_type="race_ungrouped", initial_group_size=3, quorum=3)
    _arrive_at_group_barrier(exp, grouper, first)
    db.session.commit()
    leftover = BarrierInstance.query.filter_by(barrier_id=grouper.id).one()
    leftover.active = False
    db.session.commit()
    leftover_id, spec, behavior_hash = (
        leftover.id,
        leftover.spec,
        leftover.behavior_hash,
    )
    newer_id = str(uuid.uuid4())

    with db.engine.connect() as arrival, arrival.begin() as arrival_txn:
        # What ``BarrierInstance.for_arrival`` does before it opens a new pool.
        arrival.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": grouper.id},
        )
        arrival.execute(
            BarrierInstance.__table__.insert().values(
                id=newer_id,
                type=sa_inspect(BarrierInstance).polymorphic_identity,
                barrier_id=grouper.id,
                active=True,
                spec=spec,
                behavior_hash=behavior_hash,
            )
        )
        _set_transaction_lock_timeout(1)
        leftover = BarrierInstance.query.get(leftover_id)
        assert _check_claimed_barrier_instance(leftover, already_claimed=True) is False
        db.session.commit()
        arrival_txn.commit()

    leftover = BarrierInstance.query.get(leftover_id)
    assert leftover.active is False
    assert _check_claimed_barrier_instance(leftover, already_claimed=True) is True
    db.session.commit()
    first = Participant.query.get(first.id)
    assert BarrierInstance.query.get(leftover_id).active is False
    assert first.active_barriers[grouper.id].barrier_instance_id == newer_id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_leftover_ungrouped_waiter_joins_the_active_pool_and_can_proceed(
    in_experiment_directory, db_session
):
    """A leftover waiter must join the live pool in time to be grouped."""
    exp = get_experiment()
    first, second, third = [new_participant(exp) for _ in range(3)]
    for participant in (first, second, third):
        participant.status = "working"
    db.session.commit()
    grouper = SimpleGrouper(group_type="migrate_join", initial_group_size=3, quorum=3)
    _arrive_at_group_barrier(exp, grouper, first)
    db.session.commit()
    leftover = BarrierInstance.query.filter_by(barrier_id=grouper.id).one()
    leftover.active = False
    newer = BarrierInstance(
        id=str(uuid.uuid4()),
        barrier_id=leftover.barrier_id,
        group_id=None,
        active=True,
        spec=leftover.spec,
        behavior_hash=leftover.behavior_hash,
    )
    db.session.add(newer)
    db.session.commit()
    _arrive_at_group_barrier(exp, grouper, second)
    db.session.commit()
    leftover = BarrierInstance.query.get(leftover.id)
    assert _check_claimed_barrier_instance(leftover) is True
    db.session.commit()
    db.session.expire_all()
    first = Participant.query.get(first.id)
    leftover = BarrierInstance.query.get(leftover.id)
    newer = BarrierInstance.query.get(newer.id)
    assert leftover.active is False
    assert first.active_barriers[grouper.id].barrier_instance_id == newer.id
    _arrive_at_group_barrier(exp, grouper, third)
    _commit_barrier_arrivals()
    groups = {
        Participant.query.get(participant.id).sync_group.id
        for participant in (first, second, third)
    }
    assert len(groups) == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_recovers_inactive_grouped_instance_with_waiters(
    in_experiment_directory, db_session
):
    """The 0.5s poller must still see an inactive visit that has working waiters."""
    exp = get_experiment()
    first, _last = _pair_sync_group(exp, db_session)[0]
    first_id = first.id
    barrier = GroupBarrier(id_="poller_reactivate", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    db.session.commit()
    instance = BarrierInstance.query.filter_by(barrier_id=barrier.id).one()
    instance.active = False
    db.session.commit()
    instance_id = instance.id
    barrier_id = barrier.id
    check_barriers()
    db.session.expire_all()
    instance = BarrierInstance.query.get(instance_id)
    assert instance.active is True
    assert _barrier_link_released(first_id, barrier_id) is False


@pytest.mark.parametrize("waiting_page", [False, True])
@pytest.mark.parametrize("action", ["fail", "leave_group"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_times_out_waiters_past_their_deadline(
    in_experiment_directory, db_session, action, waiting_page
):
    """A waiter who left is timed out at their deadline, with the usual knock-on."""
    exp = get_experiment()
    overdue, partner = _pair_sync_group(exp, db_session)[0]
    patient, _ = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(
        id_="abandoned",
        group_type="main",
        max_wait_time=300,
        max_wait_action=action,
        waiting_logic=InfoPage("Filler", time_estimate=5) if waiting_page else None,
    )
    for participant in (overdue, patient):
        _arrive_at_group_barrier(exp, barrier, participant)
    db.session.commit()
    deadline_rows = (
        ParticipantLinkBarrier.query if waiting_page else TimelineHoldRecord.query
    )
    arrival_deadline = deadline_rows.filter_by(participant_id=overdue.id).one()
    arrived_at = (
        arrival_deadline.arrival_time if waiting_page else arrival_deadline.started_at
    )
    assert (arrival_deadline.deadline_at - arrived_at).total_seconds() == (
        pytest.approx(300)
    )
    deadline_rows.filter_by(participant_id=overdue.id).update(
        {"deadline_at": timenow() - timedelta(seconds=1)}
    )
    db.session.commit()
    ids = overdue.id, partner.id, patient.id

    check_barriers()

    db.session.expire_all()
    overdue, partner, patient = (Participant.query.get(i) for i in ids)
    if action == "fail":
        assert overdue.failed and "fail_on_timeout" in overdue.failure_tags
    else:
        assert not overdue.failed and not overdue.active_sync_groups
    assert _barrier_link_released(overdue.id, barrier.id)
    assert partner.failure_tags == ["sync group below quorum"]
    assert not patient.failed
    assert _barrier_link_released(patient.id, barrier.id) is False


_max_wait_time_calls = []


def _shrinking_max_wait_time(participant):
    _max_wait_time_calls.append(participant.id)
    return 300 if len(_max_wait_time_calls) == 1 else 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_callable_max_wait_time_is_evaluated_once_on_arrival(
    in_experiment_directory, db_session
):
    """A callable ``max_wait_time`` fixes the waiting-page deadline on arrival."""
    _max_wait_time_calls.clear()
    exp = get_experiment()
    original_timeline = exp.timeline
    exp.timeline = Timeline(
        GroupBarrier(
            id_="callable_deadline",
            group_type="main",
            max_wait_time=_shrinking_max_wait_time,
            waiting_logic=InfoPage("Filler", time_estimate=5),
        ),
        ModularPage("after", "After", time_estimate=1),
    )
    try:
        (waiter, _), _ = _pair_sync_group(exp, db_session)
        waiter_id = waiter.id
        assert _json_timeline(exp, waiter).status_code == 200
        link = ParticipantLinkBarrier.query.filter_by(participant_id=waiter_id).one()
        assert (link.deadline_at - link.arrival_time).total_seconds() == (
            pytest.approx(300)
        )
        time.sleep(1.1)
        check_barriers()

        waiter = Participant.query.get(waiter_id)
        _process_response(exp, waiter, waiter.page_uuid)
        waiter = Participant.query.get(waiter_id)
        assert not waiter.failed
        assert _max_wait_time_calls == [waiter_id]
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize("action", ["fail", "leave_group"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_waiting_page_timeout_applies_on_the_next_request(
    in_experiment_directory, db_session, action
):
    """A waiter timed out mid filler page is failed, or continues alone, on their next Next."""
    exp = get_experiment()
    original_timeline = exp.timeline
    exp.timeline = Timeline(
        GroupBarrier(
            id_="filler_timeout",
            group_type="main",
            max_wait_time=300,
            max_wait_action=action,
            waiting_logic=InfoPage("Filler", time_estimate=5),
        ),
        ModularPage("choose_action", "Choose your action", time_estimate=1),
    )
    try:
        (waiter, _), _ = _pair_sync_group(exp, db_session)
        waiter_id = waiter.id
        assert _json_timeline(exp, waiter).status_code == 200
        ParticipantLinkBarrier.query.filter_by(participant_id=waiter_id).update(
            {"deadline_at": timenow() - timedelta(seconds=1)}
        )
        db_session.commit()
        check_barriers()

        waiter = Participant.query.get(waiter_id)
        _process_response(exp, waiter, waiter.page_uuid)
        waiter = Participant.query.get(waiter_id)
        if action == "fail":
            assert waiter.failed
            assert exp.timeline.get_participant_branch(waiter) == "unsuccessful_end"
        else:
            assert not waiter.failed
            assert exp.timeline.get_current_elt(exp, waiter).label == "choose_action"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize("below_quorum", ["fail", "continue_without_group"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_dissolution_waits_for_a_busy_member_then_removes_everyone_at_once(
    in_experiment_directory, db_session, below_quorum
):
    """Nobody leaves while a member's own request holds their row; the poll then dissolves the rest in one go."""
    exp = get_experiment()
    (waiter, busy, quitter), group = _sync_group_of(exp, db_session, 3)
    group.below_quorum = below_quorum
    barrier = GroupBarrier(id_="dissolve_at_once", group_type="main")
    for participant in (waiter, busy):
        _arrive_at_group_barrier(exp, barrier, participant)
    _commit_barrier_arrivals()
    ids, group_id = sorted([waiter.id, busy.id]), group.id

    with db.engine.connect() as busy_request, busy_request.begin():
        busy_request.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": busy.id},
        )
        _set_transaction_lock_timeout(1)
        quitter.fail("returned")
        db.session.commit()
        check_barriers()
        db.session.expire_all()
        assert Participant.query.get(waiter.id).in_sync_group("main")

    check_barriers()

    db.session.expire_all()
    for participant_id in ids:
        participant = Participant.query.get(participant_id)
        assert not participant.in_sync_group("main")
        assert participant.failed == (below_quorum == "fail")
    assert SyncGroup.query.get(group_id).active is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_deferred_dissolution_leaves_free_members_rows_unlocked(
    in_experiment_directory, db_session
):
    """Waiting for a busy member doesn't hold the free members' rows until the caller commits."""
    exp = get_experiment()
    (free, busy, quitter), group = _sync_group_of(exp, db_session, 3)

    with _lock_participant_row(busy.id):
        _set_transaction_lock_timeout(1)
        quitter.fail("returned")
        assert group.dissolving
        assert not _participant_row_is_locked(free.id)
        db.session.commit()

    db.session.expire_all()
    assert Participant.query.get(quitter.id).failed
    assert not Participant.query.get(quitter.id).in_sync_group("main")
    assert Participant.query.get(free.id).in_sync_group("main")

    check_barriers()
    db.session.expire_all()
    assert not Participant.query.get(free.id).in_sync_group("main")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_member_whose_own_request_dissolves_the_group_is_removed_at_once(
    in_experiment_directory, db_session
):
    """The requester's own row lock doesn't hold up the dissolution it triggers."""
    exp = get_experiment()
    (stayer, late), group = _pair_sync_group(exp, db_session)
    group.below_quorum = "continue_without_group"
    db_session.commit()
    Participant.query.with_for_update(of=Participant).populate_existing().get(stayer.id)

    group.remove_participant(late, reason="late")

    assert not stayer.in_sync_group("main")
    assert not group.active and not group.dissolving


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_two_members_failing_at_once_do_not_deadlock(
    in_experiment_directory, db_session
):
    """Each holds their own row, as their requests do, then fails at the same time."""
    exp = get_experiment()
    members, group = _sync_group_of(exp, db_session, 3)
    ids, group_id = [p.id for p in members], group.id
    db.session.remove()
    both_locked = threading.Barrier(2)
    errors = []

    def fail_self(participant_id):
        try:
            _set_transaction_lock_timeout(5)
            participant = (
                Participant.query.with_for_update(of=Participant)
                .populate_existing()
                .get(participant_id)
            )
            both_locked.wait(5)
            participant.fail("timeout")
            db.session.commit()
        except Exception as err:  # pragma: no cover - surfaced below
            errors.append(err)
            db.session.rollback()
        finally:
            db.session.remove()

    threads = [threading.Thread(target=fail_self, args=(i,)) for i in ids[1:]]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    check_barriers()

    assert errors == []
    db.session.expire_all()
    tags = [Participant.query.get(i).failure_tags for i in ids]
    assert tags[0] == ["sync group below quorum"]
    assert all("timeout" in t for t in tags[1:])
    assert SyncGroup.query.get(group_id).active is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_electing_a_busy_leader_does_not_wait(in_experiment_directory, db_session):
    """Re-electing a leader doesn't wait for the new leader's own request."""
    exp = get_experiment()
    (leader, busy, _), group = _sync_group_of(exp, db_session, 3)
    group.quorum = 1
    db.session.commit()
    busy_id, group_id = busy.id, group.id

    with db.engine.connect() as busy_request, busy_request.begin():
        busy_request.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": busy_id},
        )
        _set_transaction_lock_timeout(1)
        leader.fail("left")
        db.session.commit()

    assert SyncGroup.query.get(group_id).leader_id == busy_id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_does_not_let_a_failing_visit_starve_others(
    in_experiment_directory, db_session, monkeypatch
):
    """A visit whose check keeps failing queues behind the other visits."""
    monkeypatch.setattr("psynet.sync._POLLER_SWEEP_BUDGET_SECONDS", 0)
    exp = get_experiment()
    for barrier in (SpecErrorBarrier(id_="broken"), ReleaseAllBarrier(id_="healthy")):
        participant = new_participant(exp)
        participant.status = "working"
        db.session.commit()
        _arrive_at_group_barrier(exp, barrier, participant)
        db.session.commit()
    healthy_id = participant.id

    for _ in range(2):
        check_barriers()
    assert _barrier_link_released(healthy_id, "healthy")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_spreads_idle_visits_over_sweeps(
    in_experiment_directory, db_session, monkeypatch
):
    """Past its time budget a sweep stops; later sweeps reach the other visits."""
    monkeypatch.setattr("psynet.sync._POLLER_SWEEP_BUDGET_SECONDS", 0)
    exp = get_experiment()
    waiters = []
    for i in range(3):
        participant = new_participant(exp)
        participant.status = "working"
        db.session.commit()
        _arrive_at_group_barrier(exp, ReleaseAllBarrier(id_=f"idle_{i}"), participant)
        db.session.commit()
        waiters.append((participant.id, f"idle_{i}"))

    released = []
    for _ in waiters:
        check_barriers()
        released.append(sum(_barrier_link_released(*waiter) for waiter in waiters))
    assert released == [1, 2, 3]


def _count_poller_checks(monkeypatch):
    """Return the list of visits each later ``check_barriers`` call checks, cleared per call."""
    checked = []
    process = psynet.sync._process_barrier_instance

    def counting(instance_id, *, retry=False):
        checked.append(instance_id)
        return process(instance_id, retry=retry)

    monkeypatch.setattr("psynet.sync._process_barrier_instance", counting)

    def sweep():
        checked.clear()
        check_barriers()
        db.session.expire_all()
        return list(checked)

    return sweep


def _seconds_until_release_can_be_due():
    """Return how long until the poller's only remembered visit can next release, by its last check."""
    ((_, _, due),) = psynet.sync._poller_checked_visits.values()
    return None if due is None else due - time.monotonic()


class _CustomReleaseGroupBarrier(GroupBarrier):
    def choose_who_to_release(self, waiting_participants):
        return super().choose_who_to_release(waiting_participants)


@pytest.mark.parametrize("change", ["timed_page", "returned", "made_late_now"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_poller_skips_a_visit_until_a_member_can_be_late(
    in_experiment_directory, db_session, monkeypatch, change
):
    """Unchanged, it waits for late_after or the 10 s re-check; a partner's change, or make_late_now's backdating, makes it due."""
    exp = get_experiment()
    (waiter, partner), group = _pair_sync_group(exp, db_session)
    barrier = GroupBarrier(
        id_="slow_partner", group_type="main", late_after=30, late_action="fail"
    )
    _arrive_at_group_barrier(exp, barrier, waiter)
    db.session.commit()
    sweep = _count_poller_checks(monkeypatch)

    (instance_id,) = sweep()
    assert _seconds_until_release_can_be_due() == pytest.approx(30, abs=2)
    assert sweep() == []
    monkeypatch.setattr("psynet.sync._POLLER_RECHECK_SECONDS", 0)
    assert sweep() == [instance_id]
    monkeypatch.setattr("psynet.sync._POLLER_RECHECK_SECONDS", 10)
    assert sweep() == []

    if change == "timed_page":
        partner.sync_group_link("main").page_deadline = timenow()
    elif change == "returned":
        partner.status = "returned"
    else:
        psynet.bot._backdate_group(group, 31)
    db.session.commit()
    assert sweep() == [instance_id]


def _waiting_for_top_ups(exp, db_session):
    grouper = SimpleGrouper(
        "team",
        initial_group_size=2,
        join_existing_groups=True,
        use_admission_points=False,
        below_quorum="continue_without_group",
        top_up_wait=40,
    )
    quitter, waiter = _working_participants(exp, 2)
    grouper._make_group([quitter, waiter], initial_group_size=2)
    db_session.commit()
    quitter.fail("quit")
    return GroupBarrier(id_="game_starts", group_type="team"), [waiter]


def _waiting_with_a_newcomer(exp, db_session):
    group, founders, (newcomer,) = _society(exp, db_session, target_group_size=4)
    group.top_up_wait = 60
    barrier = GroupBarrier(
        "generation_start",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=40,
    )
    return barrier, [*founders, newcomer]


def _waiting_to_start_short(exp, db_session):
    grouper = SimpleGrouper(
        "team",
        initial_group_size=4,
        quorum=2,
        below_quorum="fail",
        start_short_after=40,
        max_wait_time=80,
    )
    return grouper, _working_participants(exp, 2)


@pytest.mark.parametrize(
    "setup", [_waiting_for_top_ups, _waiting_with_a_newcomer, _waiting_to_start_short]
)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_poller_skips_a_visit_until_its_wait_can_end(
    in_experiment_directory, db_session, monkeypatch, setup
):
    """top_up_wait, newcomer_max_wait and start_short_after each decide when the poller checks again."""
    exp = get_experiment()
    barrier, waiters = setup(exp, db_session)
    for waiter in waiters:
        _arrive_at_group_barrier(exp, barrier, waiter)
    db.session.commit()
    sweep = _count_poller_checks(monkeypatch)

    (instance_id,) = sweep()
    assert _seconds_until_release_can_be_due() == pytest.approx(40, abs=2)
    monkeypatch.setattr("psynet.sync._POLLER_RECHECK_SECONDS", 60)
    monotonic = time.monotonic
    for seconds_later, checked in [(0, []), (38, []), (42, [instance_id])]:
        monkeypatch.setattr(
            time, "monotonic", lambda later=seconds_later: monotonic() + later
        )
        assert sweep() == checked


@pytest.mark.parametrize("why", ["waiter_busy", "custom_release_rule"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_poller_checks_some_unchanged_visits_at_every_sweep(
    in_experiment_directory, db_session, monkeypatch, why
):
    """A deferred check, or a subclass that changes the release rule, gets no skip."""
    exp = get_experiment()
    (waiter, _), _ = _pair_sync_group(exp, db_session)
    barrier_class = (
        _CustomReleaseGroupBarrier if why == "custom_release_rule" else GroupBarrier
    )
    barrier = barrier_class(
        id_="unskipped", group_type="main", late_after=30, late_action="fail"
    )
    _arrive_at_group_barrier(exp, barrier, waiter)
    db.session.commit()
    sweep = _count_poller_checks(monkeypatch)

    if why == "waiter_busy":
        with _lock_participant_row(waiter.id):
            (instance_id, _retry) = sweep()
    else:
        (instance_id,) = sweep()
    assert _seconds_until_release_can_be_due() is None
    assert sweep() == [instance_id]


def _arrival_hold_messages(publications, participant_id):
    """Return arrival-update overlay HTML published to one participant."""
    return [
        target.get("hold_message")
        for published_id, payload in publications
        if published_id == participant_id
        for target in payload.get("targets", [])
        if target.get("reason") == "arrival_update"
    ]


def _route_hold_resume(participant_id, page_uuid):
    """POST ``/response`` as a hold-resume overlay, including ``skip_write``."""
    payload = {
        "participant_id": participant_id,
        "page_uuid": page_uuid,
        "metadata": {},
        "timeline_hold_resume": True,
        "include_timeline_fragment": False,
    }
    with Flask(__name__).test_request_context(
        "/response",
        method="POST",
        data={"json": json.dumps(payload)},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        return Experiment.route_response()


def _assert_still_holding(exp, participant_ids):
    """Listed participants must still be on a timeline hold."""
    for participant_id in participant_ids:
        participant = Participant.query.get(participant_id)
        page = exp.timeline.get_current_elt(exp, participant)
        assert getattr(page, "is_timeline_hold", False)
        assert participant.sync_group is None


def _assert_still_on_hold(exp, participant_ids):
    """Listed participants must still be on a timeline hold after a release."""
    db.session.expire_all()
    for participant_id in participant_ids:
        participant = Participant.query.get(participant_id)
        page = exp.timeline.get_current_elt(exp, participant)
        assert getattr(page, "is_timeline_hold", False)


def _advisory_lock_count():
    """Return how many advisory locks the test database currently holds."""
    # pg_locks spans the whole server, which parallel CI slots share.
    with db.engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND database = (SELECT oid FROM pg_database "
                "WHERE datname = current_database())"
            )
        ).scalar()


def _short_timeline_lock_timeout(monkeypatch, seconds=0.3):
    """Bound claim and ORM lock waits so timeout tests stay fast."""
    real_get_config = get_config

    def wrapped():
        cfg = real_get_config()

        def getter(key, default=None):
            if key == "timeline_lock_timeout_seconds":
                return seconds
            return cfg.get(key, default)

        return SimpleNamespace(get=getter)

    monkeypatch.setattr("psynet.sync.get_config", wrapped)
    monkeypatch.setattr("psynet.experiment.get_config", wrapped)


def _assert_last_arrival_left_partners_waiting(
    exp, last_response, waiter_cursors, last_id
):
    """Last-arrival released the group but did not advance waiting partners."""
    payload = last_response.get_json() or {}
    page_type = (payload.get("attributes") or {}).get("type")
    assert page_type in ("_BarrierHoldPage", "ModularPage")
    if page_type == "_BarrierHoldPage":
        assert _json_hold_is_silent(payload)
    for waiter_id, page_uuid in waiter_cursors:
        _assert_cursor_unchanged(waiter_id, page_uuid)
        participant = Participant.query.get(waiter_id)
        page = exp.timeline.get_current_elt(exp, participant)
        assert getattr(page, "is_timeline_hold", False)
    last = Participant.query.get(last_id)
    assert last.sync_group is not None
    ids = [waiter_id for waiter_id, _ in waiter_cursors] + [last_id]
    _catch_up_until_action(exp, ids)


def _assert_stacked_finalize_publishes_wakes(exp, monkeypatch, group_size):
    """Last-arrival publishes partner wakes at the check commit."""
    original_timeline = exp.timeline
    group_type = f"stack{group_size}_wake_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=group_size)
    publications = _hold_wake_publications(monkeypatch)
    released_at_inner_commit = []
    original_finalize = Experiment._finalize_barrier_arrivals
    real_commit = db.session.commit

    def tracking_commit(*args, **kwargs):
        result = real_commit(*args, **kwargs)
        released_at_inner_commit.append(_released_wake_count(publications))
        return result

    @classmethod
    def wrapped_finalize(cls, *args, **kwargs):
        monkeypatch.setattr(db.session, "commit", tracking_commit)
        try:
            return original_finalize(*args, **kwargs)
        finally:
            monkeypatch.setattr(db.session, "commit", real_commit)

    try:
        participants = _working_participants(exp, group_size)
        waiters = participants[:-1]
        last = participants[-1]
        waiter_cursors = []
        for waiter in waiters:
            assert _json_timeline(exp, waiter).status_code == 200
            waiter = Participant.query.get(waiter.id)
            waiter_cursors.append((waiter.id, waiter.page_uuid))
        tokens = {
            TimelineHoldRecord.query.filter_by(
                participant_id=waiter_id, page_uuid=page_uuid, resumed_at=None
            )
            .one()
            .wake_token
            for waiter_id, page_uuid in waiter_cursors
        }
        publications.clear()
        monkeypatch.setattr(Experiment, "_finalize_barrier_arrivals", wrapped_finalize)

        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        assert released_at_inner_commit
        assert any(count >= 1 for count in released_at_inner_commit)
        published = {
            target["wake_token"]
            for _, payload in publications
            for target in payload.get("targets", [])
            if target.get("reason") == "barrier_released" and target.get("wake_token")
        }
        assert tokens <= published
        _assert_last_arrival_left_partners_waiting(
            exp, last_response, waiter_cursors, last.id
        )
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_get_publishes_wakes_before_render(
    in_experiment_directory, db_session, monkeypatch
):
    """Waiting partners are woken at the check commit, before HTML render."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_render_wake_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    publications = _hold_wake_publications(monkeypatch)
    wakes_during_render = []
    original_render = Experiment._render_timeline_page_read_only

    def tracking_render(*args, **kwargs):
        wakes_during_render.append(_released_wake_count(publications))
        return original_render(*args, **kwargs)

    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        publications.clear()
        monkeypatch.setattr(
            Experiment, "_render_timeline_page_read_only", tracking_render
        )
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        assert wakes_during_render
        assert all(count >= 1 for count in wakes_during_render)
        assert _released_wake_count(publications) >= 1
        _assert_cursor_unchanged(first.id, hold_uuid)
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_timeline_arrival_does_not_skip_partner_cursors(
    in_experiment_directory, db_session
):
    """The last member self-skips; waiting partners stay on the released hold."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, last = [new_participant(exp) for _ in range(2)]
        for participant in (first, last):
            participant.status = "working"
        db.session.commit()

        first_response = _json_timeline(exp, first)
        assert first_response.status_code == 200
        assert first_response.get_json()["attributes"]["type"] == "_BarrierHoldPage"
        first = Participant.query.get(first.id)
        first_page = exp.timeline.get_current_elt(exp, first)
        assert getattr(first_page, "is_timeline_hold", False)
        assert first.sync_group is None
        hold_uuid = first.page_uuid

        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        _assert_last_arrival_left_partners_waiting(
            exp, last_response, [(first.id, hold_uuid)], last.id
        )
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_post_does_not_skip_partner_cursors(
    in_experiment_directory, db_session, monkeypatch
):
    """Last-arrival ``POST /response`` releases and wakes, without moving partners."""
    exp = get_experiment()
    original_timeline = exp.timeline
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier_id = f"post_gate_{uuid.uuid4().hex[:8]}"
    exp.timeline = Timeline(
        InfoPage("start", time_estimate=1),
        GroupBarrier(
            id_=barrier_id,
            group_type="main",
            waiting_message="Waiting for your partner",
        ),
        ModularPage("choose_action", "Choose your action", time_estimate=1),
    )
    publications = _hold_wake_publications(monkeypatch)
    first_id = first.id
    last_id = last.id
    try:
        assert _json_timeline(exp, first).status_code == 200
        assert _json_timeline(exp, last).status_code == 200
        first = Participant.query.get(first_id)
        last = Participant.query.get(last_id)
        first_response = _route_approved_response(first)
        assert first_response.status_code == 200
        first = Participant.query.get(first_id)
        hold_uuid = first.page_uuid
        assert getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )
        publications.clear()
        last = Participant.query.get(last_id)
        last_response = _route_approved_response(last)
        assert last_response.status_code == 200
        body = json.loads(last_response.get_data())
        assert body["submission"] == "approved"
        _assert_cursor_unchanged(first_id, hold_uuid)
        assert _released_wake_count(publications) >= 1
        resumed = _route_hold_resume(first_id, hold_uuid)
        assert resumed.status_code == 200
        _catch_up_until_action(exp, [first_id, last_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_catchup_hold_stays_silent(
    in_experiment_directory, db_session, monkeypatch
):
    """A hold consumed after skipping a released wait stays a silent spinner."""
    from psynet.timeline_hold import compose_hold_overlay_html

    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_silent_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)
    publications = _hold_wake_publications(monkeypatch)
    try:
        first, second, last = _working_participants(exp, 3)
        first_id, second_id, last_id = first.id, second.id, last.id
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first_id)
        first_hold_uuid = first.page_uuid
        first_hold = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=first_hold_uuid
        ).one()
        assert first_hold.silent is False
        assert _json_timeline(exp, second).status_code == 200
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        payload = last_response.get_json() or {}
        assert (payload.get("attributes") or {}).get("type") == "_BarrierHoldPage"
        assert _json_hold_is_silent(payload)
        last = Participant.query.get(last_id)
        last_hold_uuid = last.page_uuid
        last_hold = TimelineHoldRecord.query.filter_by(
            participant_id=last_id, page_uuid=last_hold_uuid
        ).one()
        assert last_hold.silent is True
        page = exp.timeline.get_current_elt(exp, last)
        assert page.overlay_html(last) == compose_hold_overlay_html("", None)
        resumed = _process_response(
            exp, last, last_hold_uuid, timeline_hold_resume=True
        )
        assert resumed.skip_write is True
        assert _json_hold_is_silent(resumed.payload["page"])
        first = Participant.query.get(first_id)
        first_page = exp.timeline.get_current_elt(exp, first)
        assert "Waiting for your partner" in (first_page.overlay_html(first) or "")
        publications.clear()
        first_get = _json_timeline(exp, first)
        assert first_get.status_code == 200
        first = Participant.query.get(first_id)
        first_page = exp.timeline.get_current_elt(exp, first)
        assert getattr(first_page, "is_timeline_hold", False)
        first_catchup = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=first.page_uuid
        ).one()
        assert first_catchup.silent is True
        assert _json_hold_is_silent(first_get.get_json())
        first_resume = _route_hold_resume(first_id, first.page_uuid)
        assert first_resume.status_code == 200
        last = Participant.query.get(last_id)
        last_hold = TimelineHoldRecord.query.filter_by(
            participant_id=last_id, page_uuid=last_hold_uuid
        ).one()
        assert last_hold.silent is True
        last_page = exp.timeline.get_current_elt(exp, last)
        assert last_page.overlay_html(last) == compose_hold_overlay_html("", None)
        assert _arrival_hold_messages(publications, last_id) == []
        _catch_up_until_action(exp, [first_id, second_id, last_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_poller_catchup_hold_stays_silent(in_experiment_directory, db_session):
    """Waiters the poller skips onto a later hold consume it as a silent spinner."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_poller_silent_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)
    try:
        first, second, last = _working_participants(exp, 3)
        first_id, second_id, last_id = first.id, second.id, last.id
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first_id)
        first_hold_uuid = first.page_uuid
        assert _json_timeline(exp, second).status_code == 200
        assert _json_timeline(exp, last).status_code == 200
        _assert_cursor_unchanged(first_id, first_hold_uuid)
        _advance_released_hold_waiters_after_commit([first_id])
        first = Participant.query.get(first_id)
        assert first.page_uuid != first_hold_uuid
        page = exp.timeline.get_current_elt(exp, first)
        assert getattr(page, "is_timeline_hold", False)
        record = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=first.page_uuid
        ).one()
        assert record.silent is True
        _catch_up_until_action(exp, [first_id, second_id, last_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_hold_resume_post_catchup_hold_stays_silent(
    in_experiment_directory, db_session
):
    """A ready overlay POST that lands on a later wait marks that hold silent."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_post_silent_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)
    try:
        first, second, last = _working_participants(exp, 3)
        first_id, second_id, last_id = first.id, second.id, last.id
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first_id)
        first_hold_uuid = first.page_uuid
        assert _json_timeline(exp, second).status_code == 200
        assert _json_timeline(exp, last).status_code == 200
        _assert_cursor_unchanged(first_id, first_hold_uuid)
        resumed = _process_response(
            exp,
            Participant.query.get(first_id),
            first_hold_uuid,
            timeline_hold_resume=True,
        )
        first = Participant.query.get(first_id)
        assert first.page_uuid != first_hold_uuid
        assert getattr(resumed.page, "is_timeline_hold", False)
        record = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=first.page_uuid
        ).one()
        assert record.silent is True
        _catch_up_until_action(exp, [first_id, second_id, last_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_catchup_holds_stay_silent(
    in_experiment_directory, db_session, monkeypatch
):
    """Poller-won stacked skips mark later holds silent before they are skipped."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_poller_check_silent_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)

    @classmethod
    def skip_finalize(cls, experiment, participant, page):
        return participant, page

    try:
        first, second, last = _working_participants(exp, 3)
        first_id, second_id, last_id = first.id, second.id, last.id
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first_id)
        first_hold_uuid = first.page_uuid
        first_hold = TimelineHoldRecord.query.filter_by(
            participant_id=first_id, page_uuid=first_hold_uuid
        ).one()
        assert first_hold.silent is False
        assert _json_timeline(exp, second).status_code == 200
        monkeypatch.setattr(
            Experiment, "_finalize_pending_timeline_barriers", skip_finalize
        )
        assert _json_timeline(exp, last).status_code == 200
        check_barriers()
        holds = (
            TimelineHoldRecord.query.filter_by(participant_id=first_id)
            .order_by(TimelineHoldRecord.id)
            .all()
        )
        assert holds[0].page_uuid == first_hold_uuid
        assert holds[0].silent is False
        assert any(record.silent for record in holds[1:])
        _assert_on_action_page(exp, [first_id, second_id, last_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_skips_released_waiters_after_commit(
    in_experiment_directory, db_session, monkeypatch
):
    """The poller releases links, then skips waiters while wakes stay unpublished.

    Concurrent last-arrival GETs can leave partner rows locked, so the
    poller finishes the stacked skip after those locks drop.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_poller_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    publications = _hold_wake_publications(monkeypatch)
    wakes_during_instances = []
    original_process = _process_barrier_instance
    original_finalize = Experiment._finalize_pending_timeline_barriers

    def tracking_process(*args, **kwargs):
        result = original_process(*args, **kwargs)
        wakes_during_instances.append(_released_wake_count(publications))
        return result

    @classmethod
    def skip_finalize(cls, experiment, participant, page):
        return participant, page

    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        first_id = first.id
        last_id = last.id
        hold_uuid = first.page_uuid
        publications.clear()
        monkeypatch.setattr(
            Experiment, "_finalize_pending_timeline_barriers", skip_finalize
        )
        assert _json_timeline(exp, last).status_code == 200
        monkeypatch.setattr("psynet.sync._process_barrier_instance", tracking_process)
        check_barriers()
        _assert_on_action_page(exp, [first_id, last_id])
        assert wakes_during_instances
        assert all(count == 0 for count in wakes_during_instances)
        assert _released_wake_count(publications) >= 1
        monkeypatch.setattr(
            Experiment, "_finalize_pending_timeline_barriers", original_finalize
        )
        resumed = _process_response(
            exp, Participant.query.get(first_id), hold_uuid, timeline_hold_resume=True
        )
        assert resumed.payload["submission"] == "approved"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_second_of_three_still_paints_stacked_group_holds(
    in_experiment_directory, db_session
):
    """A group is not complete at n-1, so the second member must still wait."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack3_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)
    try:
        first, second, last = [new_participant(exp) for _ in range(3)]
        for participant in (first, second, last):
            participant.status = "working"
        db.session.commit()

        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        second_response = _json_timeline(exp, second)
        assert second_response.status_code == 200
        assert second_response.get_json()["attributes"]["type"] == "_BarrierHoldPage"

        first = Participant.query.get(first.id)
        second = Participant.query.get(second.id)
        assert getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )
        assert getattr(
            exp.timeline.get_current_elt(exp, second), "is_timeline_hold", False
        )
        assert first.sync_group is None
        assert second.sync_group is None
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_of_three_does_not_skip_partner_cursors(
    in_experiment_directory, db_session
):
    """The third member's first /timeline paint does not advance waiting partners."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack3_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)
    try:
        first, second, last = [new_participant(exp) for _ in range(3)]
        for participant in (first, second, last):
            participant.status = "working"
        db.session.commit()

        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        assert _json_timeline(exp, second).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        second = Participant.query.get(second.id)
        waiter_cursors = [(first.id, first.page_uuid), (second.id, second.page_uuid)]
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        _assert_last_arrival_left_partners_waiting(
            exp, last_response, waiter_cursors, last.id
        )
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stale_hold_resume_approves_the_current_page_after_last_arrival(
    in_experiment_directory, db_session
):
    """A submit with the old hold uuid is a catch-up, not a multi-tab reject."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_resume_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        assert TimelineHoldRecord.query.filter_by(
            participant_id=first.id, page_uuid=hold_uuid
        ).one()

        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first.id)
        rejected = _process_response(exp, first, str(uuid.uuid4()))
        assert rejected.payload["submission"] == "rejected"

        unknown = _process_response(
            exp, first, str(uuid.uuid4()), timeline_hold_resume=True
        )
        assert unknown.payload["submission"] == "rejected"

        current_page = exp.timeline.get_current_elt(exp, first)
        approved = _process_response(exp, first, hold_uuid)
        assert approved.payload["submission"] == "approved"
        leftover = exp._page_for_stale_hold_resume(first, hold_uuid, current_page)
        assert leftover is not None
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stale_hold_uuid_catches_up_onto_a_later_hold(
    in_experiment_directory, db_session
):
    """A leftover hold uuid is catch-up for ordinary submits and hold-resume."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_later_hold_{uuid.uuid4().hex[:8]}"
    exp.timeline = Timeline(
        SimpleGrouper(
            group_type=group_type,
            initial_group_size=2,
            waiting_message="Waiting for your partner",
        ),
        wait_while(lambda: True, expected_wait=1, max_wait_time=60),
        ModularPage("choose_action", "Choose your action", time_estimate=1),
    )
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first.id)
        current_page = exp.timeline.get_current_elt(exp, first)
        assert getattr(current_page, "is_timeline_hold", False)

        resumed = _process_response(exp, first, hold_uuid, timeline_hold_resume=True)
        assert resumed.payload["submission"] == "approved"
        assert getattr(resumed.page, "is_timeline_hold", False)
        assert first.page_uuid != hold_uuid
        assert resumed.payload["page"]["attributes"]["page_uuid"] == first.page_uuid

        first = Participant.query.get(first.id)
        approved = _process_response(exp, first, hold_uuid)
        assert approved.payload["submission"] == "approved"
        assert getattr(approved.page, "is_timeline_hold", False)
        assert approved.payload["page"]["attributes"]["page_uuid"] == first.page_uuid
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stale_wait_while_uuid_is_catch_up_after_get_skip(
    in_experiment_directory, db_session
):
    """A ready wait_while skip must accept the old hold uuid on the next POST."""
    exp = get_experiment()
    original_timeline = exp.timeline
    ready = {"stop": False}
    exp.timeline = Timeline(
        wait_while(lambda: not ready["stop"], expected_wait=1),
        InfoPage("done", time_estimate=1),
    )
    try:
        (first,) = _working_participants(exp, 1)
        first_response = _json_timeline(exp, first)
        assert first_response.status_code == 200
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        assert getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )
        ready["stop"] = True
        skipped = _json_timeline(exp, first)
        assert skipped.status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first.id)
        assert first.page_uuid != hold_uuid
        assert not getattr(
            exp.timeline.get_current_elt(exp, first), "is_timeline_hold", False
        )
        approved = _process_response(exp, first, hold_uuid)
        assert approved.payload["submission"] == "approved"
        assert not getattr(approved.page, "is_timeline_hold", False)
        assert approved.payload["page"]["attributes"]["page_uuid"] == first.page_uuid
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stale_hold_uuid_catches_up_across_a_skipped_hold(
    in_experiment_directory, db_session, resume
):
    """Pages consumed since the old hold were all holds, so it is still catch-up."""
    exp = get_experiment()
    original_timeline = exp.timeline
    ready = {"a": False, "b": False}
    exp.timeline = Timeline(
        wait_while(lambda: not ready["a"], expected_wait=1),
        wait_while(lambda: not ready["b"], expected_wait=1),
        wait_while(lambda: True, expected_wait=1, max_wait_time=60),
        InfoPage("done", time_estimate=1),
    )
    try:
        (first,) = _working_participants(exp, 1)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        for key in ready:
            ready[key] = True
            assert _json_timeline(exp, first).status_code == 200
            db.session.expire_all()
            first = Participant.query.get(first.id)

        result = _process_response(exp, first, hold_uuid, timeline_hold_resume=resume)
        assert result.payload["submission"] == "approved"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_hold_uuid_is_not_catch_up_after_answering_a_later_page(
    in_experiment_directory, db_session
):
    """An old hold uuid from a stale tab must still get the multi-tab reject."""
    exp = get_experiment()
    original_timeline = exp.timeline
    ready = {"stop": False}
    exp.timeline = Timeline(
        wait_while(lambda: not ready["stop"], expected_wait=1),
        ModularPage("first", "First", time_estimate=1),
        ModularPage("second", "Second", time_estimate=1),
    )
    try:
        (first,) = _working_participants(exp, 1)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        ready["stop"] = True
        assert _json_timeline(exp, first).status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first.id)
        answered = _process_response(exp, first, first.page_uuid)
        assert answered.payload["submission"] == "approved"
        db.session.commit()
        first = Participant.query.get(first.id)
        assert exp.timeline.get_current_elt(exp, first).label == "second"

        stale = _process_response(exp, first, hold_uuid)
        assert stale.payload["submission"] == "rejected"
        stale_resume = _process_response(
            exp, first, hold_uuid, timeline_hold_resume=True
        )
        assert stale_resume.payload["submission"] == "rejected"
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_failing_a_held_participant_wakes_their_overlay(
    in_experiment_directory, db_session, monkeypatch
):
    """Admin or partner fails must not leave the overlay on its safety poll."""
    exp = get_experiment()
    original_timeline = exp.timeline
    exp.timeline = Timeline(
        wait_while(lambda: True, expected_wait=1, max_wait_time=60),
        InfoPage("done", time_estimate=1),
    )
    try:
        (first,) = _working_participants(exp, 1)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        wake_token = first.timeline_holds[0].wake_token
        publications = _hold_wake_publications(monkeypatch)
        redis_channels = []
        original_publish = db.redis_conn.publish

        def recording_publish(channel, message):
            redis_channels.append(channel)
            return original_publish(channel, message)

        monkeypatch.setattr(db.redis_conn, "publish", recording_publish)

        first.fail("manual")
        db_session.commit()
    finally:
        exp.timeline = original_timeline

    assert not [
        channel
        for channel in redis_channels
        if str(channel).startswith("psynet_timeline_hold")
    ]
    assert publications == [
        (
            first.id,
            {
                "type": "timeline_hold_wake",
                "targets": [{"wake_token": wake_token, "reason": "participant_failed"}],
            },
        )
    ]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_waiter_get_timeline_survives_stale_hold_after_own_advance(
    in_experiment_directory, db_session, monkeypatch
):
    """GET /timeline must paint the live page if this waiter already advanced."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_get_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        hold_page = exp.timeline.get_current_elt(exp, first)
        hold_uuid = first.page_uuid
        assert getattr(hold_page, "is_timeline_hold", False)

        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first.id)

        catch_up = _json_timeline(exp, first)
        assert catch_up.status_code == 200
        db.session.expire_all()
        first = Participant.query.get(first.id)
        assert first.page_uuid != hold_uuid

        original_get = Experiment.get_current_page

        @classmethod
        def stale_get(cls, experiment, participant):
            if participant.id == first.id:
                hold_page.pre_render()
                return hold_page
            return original_get.__func__(cls, experiment, participant)

        monkeypatch.setattr(Experiment, "get_current_page", stale_get)
        response = _json_timeline(exp, first)
        assert response.status_code == 200
        assert response.get_json()["attributes"]["page_uuid"] != hold_uuid
    finally:
        exp.timeline = original_timeline


def _route_timeline_in_thread(exp, unique_id):
    """Run ``_route_timeline`` on a thread-local session and request context."""
    result = {}
    errors = []

    def target():
        try:
            participant = Participant.query.filter_by(unique_id=unique_id).one()
            response = _json_timeline(exp, participant)
            payload = response.get_json()
            result["status"] = response.status_code
            result["type"] = payload["attributes"]["type"]
        except Exception as err:  # pragma: no cover - surfaced by the caller
            errors.append(err)
        finally:
            db.session.remove()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result, errors


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_two_late_trio_arrivals_release_the_waiting_member(
    in_experiment_directory, db_session
):
    """Concurrent n-1 and n arrivals must still complete the group."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack3_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=3)
    try:
        first, late_a, late_b = [new_participant(exp) for _ in range(3)]
        for participant in (first, late_a, late_b):
            participant.status = "working"
        db.session.commit()
        late_a_id, late_b_id, first_id = late_a.id, late_b.id, first.id
        late_a_uid, late_b_uid = late_a.unique_id, late_b.unique_id

        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        thread_a, result_a, errors_a = _route_timeline_in_thread(exp, late_a_uid)
        thread_b, result_b, errors_b = _route_timeline_in_thread(exp, late_b_uid)
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)
        assert errors_a == []
        assert errors_b == []
        assert not thread_a.is_alive()
        assert not thread_b.is_alive()
        assert result_a.get("status") == 200
        assert result_b.get("status") == 200
        _catch_up_until_action(exp, [first_id, late_a_id, late_b_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("group_size", [4, 5])
def test_last_of_n_does_not_skip_partner_cursors(
    in_experiment_directory, db_session, group_size
):
    """The last member's first /timeline paint must not advance waiting partners."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack{group_size}_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=group_size)
    try:
        participants = _working_participants(exp, group_size)
        waiter_ids = [participant.id for participant in participants[:-1]]
        last_id = participants[-1].id
        waiter_cursors = []
        for waiter in participants[:-1]:
            response = _json_timeline(exp, waiter)
            assert response.status_code == 200
            assert response.get_json()["attributes"]["type"] == "_BarrierHoldPage"
            waiter = Participant.query.get(waiter.id)
            waiter_cursors.append((waiter.id, waiter.page_uuid))
        _assert_still_holding(exp, waiter_ids)

        last_response = _json_timeline(exp, participants[-1])
        assert last_response.status_code == 200
        _assert_last_arrival_left_partners_waiting(
            exp, last_response, waiter_cursors, last_id
        )
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_penultimate_of_four_still_paints_stacked_group_holds(
    in_experiment_directory, db_session
):
    """A group of four is not complete at n-1, so the third member still waits."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack4_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=4)
    try:
        participants = _working_participants(exp, 4)
        for waiter in participants[:3]:
            response = _json_timeline(exp, waiter)
            assert response.status_code == 200
            assert response.get_json()["attributes"]["type"] == "_BarrierHoldPage"
        _assert_still_holding(exp, [participant.id for participant in participants[:3]])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_two_late_arrivals_complete_a_group_of_four(
    in_experiment_directory, db_session
):
    """Two waiters plus two concurrent arrivals must still complete the group."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack4_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type, group_size=4)
    try:
        first, second, late_a, late_b = _working_participants(exp, 4)
        first_id, second_id = first.id, second.id
        late_a_id, late_b_id = late_a.id, late_b.id
        late_a_uid, late_b_uid = late_a.unique_id, late_b.unique_id

        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        assert _json_timeline(exp, second).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        _assert_still_holding(exp, [first_id, second_id])

        thread_a, result_a, errors_a = _route_timeline_in_thread(exp, late_a_uid)
        thread_b, result_b, errors_b = _route_timeline_in_thread(exp, late_b_uid)
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)
        assert errors_a == []
        assert errors_b == []
        assert not thread_a.is_alive()
        assert not thread_b.is_alive()
        assert result_a.get("status") == 200
        assert result_b.get("status") == 200
        _catch_up_until_action(exp, [first_id, second_id, late_a_id, late_b_id])
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_finalize_rechecks_current_hold_when_follow_up_queue_is_dropped(
    in_experiment_directory, db_session, monkeypatch
):
    """Stacked entry holds must finish even if a later queued check is lost."""
    from psynet.sync import _take_pending_barrier_checks as original_take

    seen = {"count": 0}

    def drop_follow_ups():
        checks = original_take()
        seen["count"] += 1
        if seen["count"] > 1:
            return []
        return checks

    monkeypatch.setattr("psynet.sync._take_pending_barrier_checks", drop_follow_ups)
    test_last_timeline_arrival_does_not_skip_partner_cursors(
        in_experiment_directory, db_session
    )
    assert seen["count"] > 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_retries_an_unclaimed_barrier_check_once(
    in_experiment_directory, db_session, monkeypatch
):
    """A busy partner row must not make the last arriver first-paint a hold.

    Last-arrival waits for the instance claim, then locks waiters with
    ``NOWAIT``. If a partner row is still busy, one immediate retry (still
    ``NOWAIT``, no lock wait) lets this GET self-skip stacked entry holds.
    """
    from psynet.sync import _run_pending_barrier_checks as original_run

    seen = {"count": 0}

    def fail_first(checks, **kwargs):
        seen["count"] += 1
        if seen["count"] == 1:
            return False
        return original_run(checks, **kwargs)

    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_retry_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        hold_uuid = first.page_uuid
        monkeypatch.setattr("psynet.sync._run_pending_barrier_checks", fail_first)
        last_response = _json_timeline(exp, last)
        assert last_response.status_code == 200
        assert seen["count"] >= 2
        _assert_last_arrival_left_partners_waiting(
            exp, last_response, [(first.id, hold_uuid)], last.id
        )
    finally:
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_releases_waiters_when_nowait_retry_sees_unlocked_row(
    in_experiment_directory, db_session, monkeypatch
):
    """A waiter ``FOR UPDATE`` that drops before the immediate retry must release.

    The retry is immediate; this test rolls back the partner lock between
    attempts so the second ``NOWAIT`` can take the row.
    """
    from psynet.sync import _run_pending_barrier_checks as original_run

    exp = get_experiment()
    original_timeline = exp.timeline
    original_advance = exp._advance_past_ready_holds
    first, last = _pair_sync_group(exp, db_session)[0]
    first_id = first.id
    last_id = last.id
    barrier = GroupBarrier(id_="finalize_nowait_retry_drop", group_type="main")
    page = _DummyFinalizePage()
    exp.timeline = SimpleNamespace(get_current_elt=lambda _e, _p: page)
    exp._advance_past_ready_holds = lambda participant, current_page: current_page
    checks = _queued_last_arrival_checks(exp, barrier, first, last)
    result = SimpleNamespace(page=object(), payload={"page": "stale"})
    claimed_flags = []
    blocker = db.engine.connect()
    blocker_trans = blocker.begin()
    blocker.execute(
        text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
        {"id": first_id},
    )

    def run_then_drop(instance_ids, **kwargs):
        claimed = original_run(instance_ids, **kwargs)
        claimed_flags.append(claimed)
        if len(claimed_flags) == 1 and blocker_trans.is_active:
            blocker_trans.rollback()
        return claimed

    monkeypatch.setattr("psynet.sync._run_pending_barrier_checks", run_then_drop)
    try:
        started_at = time.perf_counter()
        Experiment._finalize_barrier_arrivals(
            exp,
            participant_id=last_id,
            checks=checks,
            result=result,
        )
        elapsed = time.perf_counter() - started_at
    finally:
        if blocker_trans.is_active:
            blocker_trans.rollback()
        blocker.close()
        exp.timeline = original_timeline
        exp._advance_past_ready_holds = original_advance

    assert elapsed < 1
    assert claimed_flags[0] is False
    assert claimed_flags[1] is True
    assert _barrier_link_released(first_id, barrier.id) is True
    assert _barrier_link_released(last_id, barrier.id) is True
    assert result.page is page


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_waits_for_a_busy_barrier_claim(
    in_experiment_directory, db_session
):
    """Last-arrival GET must wait for the poller's instance claim, then continue.

    Playwright first-paint fails if this GET renders a hold while the 0.5 s
    poller still owns the visit. Waiting for the advisory claim (not waiter
    rows) lets the last arriver evaluate the barrier instead of first-painting
    the unreleased hold.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_claim_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    release_claim = threading.Event()
    claim_held = threading.Event()
    holder_error = []
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        last_uid = last.unique_id
        hold_uuid = first.page_uuid

        def hold_claim():
            try:
                with db.engine.connect() as conn:
                    trans = conn.begin()
                    conn.execute(
                        text(
                            "SELECT pg_advisory_xact_lock("
                            "hashtextextended(:instance_id, 0))"
                        ),
                        {"instance_id": instance_id},
                    )
                    claim_held.set()
                    if not release_claim.wait(timeout=5):
                        raise TimeoutError("Last-arrival GET did not finish.")
                    trans.rollback()
            except Exception as err:  # pragma: no cover - surfaced by the caller
                holder_error.append(err)

        holder = threading.Thread(target=hold_claim, daemon=True)
        holder.start()
        assert claim_held.wait(timeout=2)
        thread, result, errors = _route_timeline_in_thread(exp, last_uid)
        thread.join(timeout=0.3)
        assert thread.is_alive()
        release_claim.set()
        thread.join(timeout=5)
        holder.join(timeout=5)
        assert holder_error == []
        assert errors == []
        assert not thread.is_alive()
        assert result.get("status") == 200
        last = Participant.query.get(last.id)
        assert last.sync_group is not None
        _assert_cursor_unchanged(first.id, hold_uuid)
        _catch_up_until_action(exp, [first.id, last.id])
    finally:
        release_claim.set()
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_follows_poller_release_after_claim_wait(
    in_experiment_directory, db_session
):
    """If the poller already released the visit, last-arrival must skip that hold.

    Last-arrival waits for the visit claim on a separate connection. The poller
    releases links without advancing waiters. This GET then skips its own
    released hold instead of first-painting it.
    """
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_poller_skip_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(
        group_type, group_size=3, hold_content="Waiting for your group"
    )
    claim_held = threading.Event()
    last_joined = threading.Event()
    holder_error = []
    try:
        first, second, last = _working_participants(exp, 3)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        assert _json_timeline(exp, second).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        first_page = exp.timeline.get_current_elt(exp, first)
        first_hold_id = getattr(first_page, "hold_id", None)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        last_uid = last.unique_id
        last_id = last.id
        first_id = first.id
        second_id = second.id

        def poller_release():
            try:
                _set_transaction_lock_timeout(
                    get_config().get("timeline_lock_timeout_seconds")
                )
                assert _claim_barrier_instance(instance_id, wait=True)
                claim_held.set()
                if not last_joined.wait(timeout=5):
                    raise TimeoutError("Last arriver did not join the visit.")
                instance = BarrierInstance.query.get(instance_id)
                assert _check_claimed_barrier_instance(instance, wait=False)
                db.session.commit()
            except Exception as err:  # pragma: no cover - surfaced by the caller
                holder_error.append(err)
                db.session.rollback()
            finally:
                db.session.remove()

        holder = threading.Thread(target=poller_release, daemon=True)
        holder.start()
        assert claim_held.wait(timeout=2)
        thread, result, errors = _route_timeline_in_thread(exp, last_uid)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not thread.is_alive():
                break
            with db.engine.connect() as conn:
                waiting = conn.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM participant_link_barrier
                        WHERE barrier_instance_id = :instance_id
                          AND released IS NOT true
                        """
                    ),
                    {"instance_id": instance_id},
                ).scalar()
            if waiting == 3:
                last_joined.set()
                break
            time.sleep(0.01)
        else:
            last_joined.set()
            raise AssertionError("Last arriver did not join the visit.")
        thread.join(timeout=5)
        holder.join(timeout=5)
        assert holder_error == []
        assert errors == []
        assert not thread.is_alive()
        assert result.get("status") == 200
        last = Participant.query.get(last_id)
        last_page = exp.timeline.get_current_elt(exp, last)
        assert last.sync_group is not None
        assert getattr(last_page, "hold_id", None) != first_hold_id or not getattr(
            last_page, "is_timeline_hold", False
        )
        _assert_still_on_hold(exp, [first_id, second_id])
        _catch_up_until_action(exp, [first_id, second_id, last_id])
    finally:
        last_joined.set()
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_concurrent_get_waits_for_claim_during_check(
    in_experiment_directory, db_session, monkeypatch
):
    """A concurrent GET must stay blocked on the visit claim until the check finishes."""
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_skip_claim_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    original_check = _check_held_instance
    pause = threading.Event()
    resume = threading.Event()
    paused = {"done": False}

    def pausing_check(instance_id, **kwargs):
        if not paused["done"]:
            paused["done"] = True
            pause.set()
            assert resume.wait(timeout=5)
        return original_check(instance_id, **kwargs)

    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).status_code == 200
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        last_uid = last.unique_id
        hold_uuid = first.page_uuid
        monkeypatch.setattr("psynet.sync._check_held_instance", pausing_check)
        last_thread, last_result, last_errors = _route_timeline_in_thread(exp, last_uid)
        assert pause.wait(timeout=5)
        claim_errors = []

        def wait_for_claim():
            try:
                _run_pending_barrier_checks([instance_id])
            except Exception as err:  # pragma: no cover - surfaced by the caller
                claim_errors.append(err)
            finally:
                db.session.remove()

        claim_thread = threading.Thread(target=wait_for_claim, daemon=True)
        claim_thread.start()
        claim_thread.join(timeout=0.4)
        assert claim_thread.is_alive()
        resume.set()
        last_thread.join(timeout=8)
        claim_thread.join(timeout=8)
        assert last_errors == []
        assert claim_errors == []
        assert not last_thread.is_alive()
        assert not claim_thread.is_alive()
        assert last_result.get("status") == 200
        _assert_cursor_unchanged(first.id, hold_uuid)
        _catch_up_until_action(exp, [first.id, last.id])
    finally:
        resume.set()
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_claim_timeout_returns_busy_503(
    in_experiment_directory, db_session, monkeypatch
):
    """A claim wait that hits lock_timeout must be HTTP 503, not a hold page."""
    _short_timeline_lock_timeout(monkeypatch, seconds=0.3)
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_claim_503_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    release_claim = threading.Event()
    claim_held = threading.Event()
    holder_error = []
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        last_uid = last.unique_id

        def hold_claim():
            try:
                with db.engine.connect() as conn:
                    trans = conn.begin()
                    conn.execute(
                        text(
                            "SELECT pg_advisory_xact_lock("
                            "hashtextextended(:instance_id, 0))"
                        ),
                        {"instance_id": instance_id},
                    )
                    claim_held.set()
                    release_claim.wait(timeout=5)
                    trans.rollback()
            except Exception as err:  # pragma: no cover - surfaced by the caller
                holder_error.append(err)

        holder = threading.Thread(target=hold_claim, daemon=True)
        holder.start()
        assert claim_held.wait(timeout=2)
        started = time.perf_counter()
        thread, result, errors = _route_timeline_via_route_in_thread(last_uid)
        thread.join(timeout=5)
        elapsed = time.perf_counter() - started
        release_claim.set()
        holder.join(timeout=5)
        assert holder_error == []
        assert errors == []
        assert not thread.is_alive()
        assert elapsed >= 0.25
        assert result.get("status") == 503
        assert result.get("payload", {}).get("status") == "busy"
        assert result.get("payload", {}).get("submission") == "busy"
    finally:
        release_claim.set()
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_waiter_unfilled_get_does_not_return_busy_503_for_held_claim(
    in_experiment_directory, db_session, monkeypatch
):
    """A waiter GET must first-paint the hold when last-arrival holds the claim."""
    _short_timeline_lock_timeout(monkeypatch, seconds=2.0)
    exp = get_experiment()
    original_timeline = exp.timeline
    group_type = f"stack_waiter_no_503_{uuid.uuid4().hex[:8]}"
    exp.timeline = _stacked_partner_timeline(group_type)
    release_claim = threading.Event()
    claim_held = threading.Event()
    holder_error = []
    try:
        first, last = _working_participants(exp, 2)
        assert _json_timeline(exp, first).get_json()["attributes"]["type"] == (
            "_BarrierHoldPage"
        )
        first = Participant.query.get(first.id)
        instance_id = next(iter(first.active_barriers.values())).barrier_instance_id
        first_uid = first.unique_id

        def hold_claim():
            try:
                with db.engine.connect() as conn:
                    trans = conn.begin()
                    conn.execute(
                        text(
                            "SELECT pg_advisory_xact_lock("
                            "hashtextextended(:instance_id, 0))"
                        ),
                        {"instance_id": instance_id},
                    )
                    claim_held.set()
                    release_claim.wait(timeout=5)
                    trans.rollback()
            except Exception as err:  # pragma: no cover - surfaced by the caller
                holder_error.append(err)

        holder = threading.Thread(target=hold_claim, daemon=True)
        holder.start()
        assert claim_held.wait(timeout=2)
        started = time.perf_counter()
        thread, result, errors = _route_timeline_via_route_in_thread(first_uid)
        thread.join(timeout=5)
        elapsed = time.perf_counter() - started
        release_claim.set()
        holder.join(timeout=5)
        assert holder_error == []
        assert errors == []
        assert not thread.is_alive()
        assert elapsed < 1.5
        assert result.get("status") == 200
        assert result.get("payload", {}).get("attributes", {}).get("type") == (
            "_BarrierHoldPage"
        )
    finally:
        release_claim.set()
        exp.timeline = original_timeline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_poller_orm_check_timeout_releases_visit_claim(
    in_experiment_directory, db_session, monkeypatch
):
    """A blocked poller check commit must time out and drop the extra claim."""
    _short_timeline_lock_timeout(monkeypatch, seconds=0.3)
    exp = get_experiment()
    baseline = _advisory_lock_count()
    participant = new_participant(exp)
    participant.status = "working"
    barrier = ReleaseAllBarrier(id_="orm_timeout_claim")
    barrier.receive_participant(participant)
    db.session.commit()
    instance_id = next(iter(participant.active_barriers.values())).barrier_instance_id

    with db.engine.connect() as conn:
        trans = conn.begin()
        conn.execute(
            text("SELECT id FROM barrier_instance WHERE id = :id FOR UPDATE"),
            {"id": instance_id},
        )
        started = time.perf_counter()
        deferred = _process_barrier_instance(instance_id)
        elapsed = time.perf_counter() - started
        trans.rollback()

    assert deferred is True
    assert elapsed >= 0.25
    assert elapsed < 3
    assert _advisory_lock_count() == baseline
    assert _participant_row_is_locked(participant.id) is False


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_skip_nowait_miss_still_releases_extra_claim(
    in_experiment_directory, db_session, monkeypatch
):
    """A locked waiter during skip must not leak the extra-connection claim."""
    exp = get_experiment()
    baseline = _advisory_lock_count()
    first, second, last = _sync_group_of(exp, db_session, 3)[0]
    barrier = GroupBarrier(id_="skip_nowait_claim", group_type="main")
    original_skip = _advance_released_hold_waiters_after_commit
    pause = threading.Event()
    resume = threading.Event()
    errors = []

    def paused_skip(participant_ids):
        if participant_ids:
            pause.set()
            assert resume.wait(timeout=5)
        return original_skip(participant_ids)

    monkeypatch.setattr(
        "psynet.sync._advance_released_hold_waiters_after_commit", paused_skip
    )
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, second)
    _commit_barrier_arrivals()
    _arrive_at_group_barrier(exp, barrier, last)
    checks = _commit_arrival_write()
    first_id = first.id

    def run_checks():
        try:
            instance_id = checks[0]
            with _hold_barrier_instance_claim(instance_id, wait=True):
                _check_and_skip_held_instance(instance_id)
        except Exception as err:  # pragma: no cover - surfaced by the caller
            errors.append(err)
        finally:
            db.session.remove()

    thread = threading.Thread(target=run_checks, daemon=True)
    thread.start()
    assert pause.wait(timeout=5)
    with db.engine.connect() as blocker:
        blocker_trans = blocker.begin()
        blocker.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": first_id},
        )
        resume.set()
        thread.join(timeout=8)
        blocker_trans.rollback()

    assert errors == []
    assert not thread.is_alive()
    assert _advisory_lock_count() == baseline
    assert _barrier_link_released(first_id, barrier.id) is True
    assert _barrier_link_released(second.id, barrier.id) is True
    assert _barrier_link_released(last.id, barrier.id) is True


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_skips_locked_waiters_and_continues(
    in_experiment_directory, db_session
):
    """A participant write must not block other barriers in the same poller sweep."""
    exp = get_experiment()
    locked_barrier = ReleaseAllBarrier(id_="a_locked")
    free_barrier = ReleaseAllBarrier(id_="b_free")
    locked_participant = new_participant(exp)
    free_participant = new_participant(exp)
    locked_participant.status = "working"
    free_participant.status = "working"
    locked_barrier.receive_participant(locked_participant)
    free_barrier.receive_participant(free_participant)
    db.session.commit()
    locked_id = locked_participant.id
    free_id = free_participant.id
    baseline = _advisory_lock_count()

    with db.engine.connect() as conn:
        trans = conn.begin()
        conn.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": locked_id},
        )
        check_barriers()
        locked_released = _barrier_link_released(locked_id, "a_locked")
        free_released = _barrier_link_released(free_id, "b_free")
        trans.rollback()

    assert locked_released is False
    assert free_released is True
    assert _advisory_lock_count() == baseline

    check_barriers()
    assert _barrier_link_released(locked_id, "a_locked") is True
    assert _advisory_lock_count() == baseline


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_two_pollers_process_one_barrier_instance_once(
    in_experiment_directory, db_session
):
    participant = new_participant(get_experiment())
    participant.status = "working"
    BlockingReleaseBarrier(id_="single_claim").receive_participant(participant)
    db_session.commit()
    two_poller_checks.clear()
    two_poller_check_started.clear()
    two_poller_check_can_finish.clear()
    errors = []

    def run_poller():
        try:
            check_barriers()
        except Exception as err:  # pragma: no cover - surfaced below
            errors.append(err)
        finally:
            db.session.remove()

    first = threading.Thread(target=run_poller, daemon=True)
    second = threading.Thread(target=run_poller, daemon=True)
    first.start()
    assert two_poller_check_started.wait(timeout=2)
    second.start()
    second.join(timeout=2)
    two_poller_check_can_finish.set()
    first.join(timeout=2)

    assert errors == []
    assert not first.is_alive()
    assert not second.is_alive()
    assert two_poller_checks == ["single_claim"]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_arrival_does_not_wait_for_poller_metadata_lock(
    in_experiment_directory, db_session
):
    """A blocked poller must not prevent another group entering the barrier."""
    import threading
    import time

    exp = get_experiment()
    blocked_participants, blocked_group = _pair_sync_group(exp, db_session)
    arriving_participants, _ = _pair_sync_group(exp, db_session)
    barrier = GroupBarrier(id_="independent_claim", group_type="main")
    for participant in blocked_participants:
        barrier.receive_participant(participant)
    db_session.commit()

    poller_pid = []
    poller_errors = []

    def run_poller():
        try:
            poller_pid.append(
                db.session.execute(text("SELECT pg_backend_pid()")).scalar()
            )
            check_barriers()
        except Exception as err:  # pragma: no cover - surfaced below
            poller_errors.append(err)
        finally:
            db.session.remove()

    with db.engine.connect() as blocker:
        transaction = blocker.begin()
        blocker.execute(
            text(
                """
                UPDATE sync_group
                SET last_barrier_pass_time = :timestamp
                WHERE id = :group_id
                """
            ),
            {"timestamp": timenow(), "group_id": blocked_group.id},
        )

        poller = threading.Thread(target=run_poller, daemon=True)
        poller.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if poller_pid:
                blocked = blocker.execute(
                    text(
                        """
                        SELECT cardinality(pg_blocking_pids(:pid)) > 0
                        """
                    ),
                    {"pid": poller_pid[0]},
                ).scalar()
                if blocked:
                    break
            time.sleep(0.01)
        else:
            raise AssertionError("Poller did not block on the held sync-group row.")

        started = time.perf_counter()
        barrier.receive_participant(arriving_participants[0])
        db_session.flush()
        elapsed = time.perf_counter() - started
        transaction.rollback()

    poller.join(timeout=2)
    assert elapsed < 1
    assert poller_errors == []
    assert not poller.is_alive()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_group_arrival_releases_without_poller(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    participants, group = _pair_sync_group(exp, db_session)
    first, last = participants
    group_id = group.id
    _group_release_calls.clear()
    barrier = GroupBarrier(
        id_="last_arrival",
        group_type="main",
        on_release=_count_group_release,
    )
    publications = _hold_wake_publications(monkeypatch)

    _arrive_at_group_barrier(exp, barrier, first)
    first_wake = first.timeline_holds[0].wake_token
    _commit_barrier_arrivals()
    assert barrier.id in first.active_barriers
    assert not barrier.waiting_logic.participant_can_resume(exp, first)
    assert _group_release_calls == []

    _arrive_at_group_barrier(exp, barrier, last)
    last_wake = last.timeline_holds[0].wake_token
    assert not barrier.waiting_logic.participant_can_resume(exp, last)
    _commit_barrier_arrivals()

    assert barrier.id not in first.active_barriers
    assert barrier.id not in last.active_barriers
    assert _group_release_calls == [group_id]
    assert barrier.waiting_logic.participant_can_resume(exp, last)
    release_targets = [
        target
        for _, payload in publications
        for target in payload["targets"]
        if target.get("reason") == "barrier_released"
    ]
    wake_tokens = {target["wake_token"] for target in release_targets}
    assert first_wake in wake_tokens
    assert last_wake in wake_tokens

    check_barriers()
    assert _group_release_calls == [group_id]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_arrival_does_not_keep_partner_rows_locked(
    in_experiment_directory, db_session
):
    """Arrival defers waiter locking until after the write transaction commits."""
    exp = get_experiment()
    participants, _group = _pair_sync_group(exp, db_session)
    first, last = participants
    barrier = GroupBarrier(id_="release_partner_locks", group_type="main")

    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    first_id = first.id
    last_id = last.id

    _arrive_at_group_barrier(exp, barrier, last)

    assert not _participant_row_is_locked(first_id)
    assert _participant_row_is_locked(last_id)
    _commit_barrier_arrivals()
    assert not _participant_row_is_locked(first_id)
    assert not _participant_row_is_locked(last_id)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_group_arrival_releases_explicit_waiting_logic_without_poller(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(
        id_="last_arrival_page",
        group_type="main",
        waiting_logic=WaitPage(wait_time=1),
    )

    barrier.receive_participant(first)
    _commit_barrier_arrivals()
    assert barrier.id in first.active_barriers

    barrier.receive_participant(last)
    _commit_barrier_arrivals()

    assert barrier.id not in first.active_barriers
    assert barrier.id not in last.active_barriers


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_last_group_arrival_defers_when_a_partner_is_locked(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(id_="locked_partner", group_type="main")
    _arrive_at_group_barrier(exp, barrier, first)
    _commit_barrier_arrivals()
    first_id = first.id
    last_id = last.id

    with db.engine.connect() as conn:
        trans = conn.begin()
        conn.execute(
            text("SELECT id FROM participant WHERE id = :id FOR UPDATE"),
            {"id": first_id},
        )
        _arrive_at_group_barrier(exp, barrier, last)
        _commit_barrier_arrivals()
        assert _barrier_link_released(first_id, "locked_partner") is False
        assert _barrier_link_released(last_id, "locked_partner") is False
        trans.rollback()

    check_barriers()
    assert _barrier_link_released(first_id, "locked_partner") is True
    assert _barrier_link_released(last_id, "locked_partner") is True


def test_default_group_barrier_arrival_message_copy():
    assert default_hold_progress(waiting_count=1, group_size=2) is None
    assert (
        default_hold_progress(waiting_count=1, group_size=3) == "2 of 3 not ready yet"
    )
    assert default_hold_progress(waiting_count=3, group_size=3) is None
    assert (
        default_group_barrier_arrival_message(
            kind="notice", waiting_count=1, group_size=2
        )
        == "Your partner is ready."
    )
    assert (
        default_group_barrier_arrival_message(
            kind="notice", waiting_count=1, group_size=3
        )
        == "1/3 of your group are ready."
    )
    assert (
        default_group_barrier_arrival_message(
            kind="notice", waiting_count=2, group_size=3
        )
        == "2/3 of your group are ready."
    )
    for kind, pair, group in [
        ("waited_too_long", "Your partner didn't", "Not everyone in your group"),
        ("late", "Your partner went on", "Your group went on"),
    ]:
        for size, start in [(2, pair), (3, group)]:
            message = default_group_barrier_arrival_message(
                kind=kind, waiting_count=0, group_size=size
            )
            assert message.startswith(start)


def test_on_arrival_message_customizes_or_turns_off_notices():
    barrier = GroupBarrier(
        id_="custom_notice",
        group_type="main",
        on_arrival_message=_custom_arrival_message,
    )
    assert (
        barrier._call_arrival_message(
            kind="notice", waiting_count=1, group_size=2, group=None
        )
        == "custom"
    )
    quiet = GroupBarrier(id_="quiet_notice", group_type="main", on_arrival_message=None)
    assert (
        quiet._call_arrival_message(kind="late", waiting_count=0, group_size=2) is None
    )


@pytest.mark.parametrize(
    "make, replacement",
    [
        (
            lambda: GroupBarrier("rc", "main", notify_arrivals=False),
            "on_arrival_message=None",
        ),
        (
            lambda: GroupBarrier("rc", "main", timeout_between_barriers_time=5),
            "renamed late_after",
        ),
        (
            lambda: StaticTrialMaker(sync_group_timeout_between_barriers_action="fail"),
            "renamed sync_group_late_action",
        ),
        (
            lambda: SimpleGrouper("main", initial_group_size=2, content="Wait"),
            "renamed waiting_message",
        ),
        (
            lambda: GroupBarrier("rc", "main", content="Wait"),
            "renamed waiting_message",
        ),
        (
            lambda: StaticTrialMaker(sync_group_wait_content="Wait"),
            "renamed sync_group_waiting_message",
        ),
    ],
)
def test_options_from_the_release_candidates_name_their_replacement(make, replacement):
    with pytest.raises(TypeError, match=replacement):
        make()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_arrival_notifies_partner_still_on_earlier_page(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(
        id_="notify_arrivals",
        group_type="main",
        waiting_message="Waiting for your partner",
    )
    publications = _hold_wake_publications(monkeypatch)

    _arrive_at_group_barrier(exp, barrier, first)
    db_session.commit()

    # The partner's browser fetches the notice after the commit.
    refreshed = [
        target.get("refresh")
        for _, payload in publications
        for target in payload["targets"]
    ]
    hold_messages = [
        target.get("hold_message")
        for _, payload in publications
        for target in payload["targets"]
    ]
    assert any(refreshed)
    assert all(
        not message or "psynet-timeline-hold-progress" not in message
        for message in hold_messages
    )
    assert pending_arrival_notice_for(last) == "Your partner is ready."
    assert arrival_notice_payload(last.unique_id) == {
        "notice": "Your partner is ready.",
        "group_ready": [
            {
                "group_id": first.active_sync_groups["main"].id,
                "seats": [0],
                "ran_out_of_time": [],
                "members": [0, 1],
            }
        ],
    }
    assert arrival_notice_payload(None) == {"notice": None, "group_ready": []}
    overlay = barrier.waiting_logic.overlay_html(first)
    assert "Waiting for your partner" in overlay
    assert "psynet-timeline-hold-progress" not in overlay


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_pending_arrival_notice_for_spec_error_returns_none(
    in_experiment_directory, db_session, monkeypatch
):
    """Page render must not 500 when a stored spec cannot be reconstructed."""
    exp = get_experiment()
    first, last = _pair_sync_group(exp, db_session)[0]
    barrier = GroupBarrier(
        id_="notify_spec_error",
        group_type="main",
        waiting_message="Waiting for your partner",
    )
    _arrive_at_group_barrier(exp, barrier, first)
    db_session.commit()

    def boom(self):
        raise BarrierSpecError("missing callback")

    monkeypatch.setattr(BarrierInstance, "get_barrier", boom)
    assert pending_arrival_notice_for(last) is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_hold_reports_how_many_are_not_ready_yet(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    first, second, third = _sync_group_of(exp, db_session, 3)[0]
    publications = _hold_wake_publications(monkeypatch)
    barrier = GroupBarrier(
        id_="group_hold_remaining",
        group_type="main",
        waiting_message="Waiting for the rest of your group",
    )

    _arrive_at_group_barrier(exp, barrier, first)
    db_session.commit()
    overlay = barrier.waiting_logic.overlay_html(first)
    assert "2 of 3 not ready yet" in overlay
    assert pending_arrival_notice_for(second) == "1/3 of your group are ready."
    assert pending_arrival_notice_for(third) == "1/3 of your group are ready."

    _arrive_at_group_barrier(exp, barrier, second)
    db_session.commit()
    overlay = barrier.waiting_logic.overlay_html(first)
    assert "1 of 3 not ready yet" in overlay
    assert "1 of 3 not ready yet" in _arrival_hold_messages(publications, first.id)[-1]
    assert pending_arrival_notice_for(third) == "2/3 of your group are ready."


def _chosen_waiting_text(waiting_count, group_size):
    return hold_message(
        "Waiting for the room", f"{waiting_count} of {group_size} have chosen"
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_hold_content_function_writes_its_own_progress_line(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first, second, _ = _sync_group_of(exp, db_session, 3)[0]
    barrier = GroupBarrier(
        id_="group_hold_custom_progress",
        group_type="main",
        waiting_message=_chosen_waiting_text,
    )

    _arrive_at_group_barrier(exp, barrier, first)
    db_session.commit()
    overlay = barrier.waiting_logic.overlay_html(first)
    assert "Waiting for the room" in overlay
    assert "1 of 3 have chosen" in overlay
    assert "not ready yet" not in overlay

    _arrive_at_group_barrier(exp, barrier, second)
    db_session.commit()
    assert "2 of 3 have chosen" in barrier.waiting_logic.overlay_html(first)


def _group_n_active(group_id):
    with db.engine.connect() as conn:
        return conn.execute(
            text("SELECT n_active_participants FROM sync_group WHERE id = :id"),
            {"id": group_id},
        ).scalar()


def test_scheduled_check_sync_groups_uses_experiment_override(monkeypatch):
    calls = []
    experiment = SimpleNamespace(
        check_sync_groups=lambda: calls.append("experiment override")
    )
    monkeypatch.setattr("psynet.experiment.is_experiment_launched", lambda: True)
    monkeypatch.setattr("psynet.experiment.get_experiment", lambda: experiment)
    monkeypatch.setattr(
        "psynet.sync.check_sync_groups", lambda: calls.append("module default")
    )

    Experiment._check_sync_groups()

    assert calls == ["experiment override"]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_sync_groups_does_not_commit_callers_transaction(
    in_experiment_directory, db_session
):
    DummyModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)

    with transaction(commit=False):
        db_session.add(DummyModel(id="unrelated-write"))
        Experiment.check_sync_groups()

    assert DummyModel.query.get("unrelated-write") is None


@pytest.mark.parametrize("accepts_top_ups", [True, False])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_sync_groups_closes_group_once_members_finish(
    in_experiment_directory, db_session, accepts_top_ups
):
    exp = get_experiment()
    participants, group = _sync_group_of(exp, db_session, 2)
    group.accepts_top_ups = accepts_top_ups
    for participant in participants:
        participant.status = "approved"
    db_session.commit()

    Experiment.check_sync_groups()

    db_session.refresh(group)
    assert not group.active
    assert group.end_time is not None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_sync_groups_keeps_a_group_open_for_its_pending_member(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    group, founders, _ = _society(exp, db_session)
    for founder in founders:
        founder.status = "approved"
    db_session.commit()

    for _ in range(2):
        check_sync_groups()

    db_session.refresh(group)
    assert group.active and group.n_active_participants == 0


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_sync_groups_corrects_counts_when_only_a_status_changed(
    in_experiment_directory, db_session
):
    """A member returning, with their group link unchanged, still updates the stored counts."""
    exp = get_experiment()
    (returner, _), shrunk = _sync_group_of(exp, db_session, 2)
    _, full = _sync_group_of(exp, db_session, 2)
    returner.status = "returned"
    full.below_quorum_since = timenow()
    db_session.commit()

    check_sync_groups()

    db_session.refresh(shrunk)
    db_session.refresh(full)
    assert (shrunk.n_active_participants, full.n_active_participants) == (1, 2)
    assert shrunk.below_quorum_since is not None
    assert full.below_quorum_since is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_sync_groups_skips_locked_group_and_continues(
    in_experiment_directory, db_session
):
    """A participant write that holds a group must not stall recounting others."""
    exp = get_experiment()
    locked_participant = new_participant(exp)
    free_participant = new_participant(exp)
    locked_participant.status = "working"
    free_participant.status = "working"

    locked_group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        quorum=1,
        n_active_participants=99,
        accepts_top_ups=False,
    )
    free_group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        quorum=1,
        n_active_participants=99,
        accepts_top_ups=False,
    )
    db_session.add_all([locked_group, free_group])
    locked_group.add_participant(locked_participant)
    free_group.add_participant(free_participant)
    locked_group.leader = locked_participant
    free_group.leader = free_participant
    db_session.commit()
    locked_id = locked_group.id
    free_id = free_group.id

    with db.engine.connect() as conn:
        trans = conn.begin()
        conn.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR UPDATE"),
            {"id": locked_id},
        )
        check_sync_groups()
        locked_count = _group_n_active(locked_id)
        free_count = _group_n_active(free_id)
        trans.rollback()

    assert locked_count == 99
    assert free_count == 1

    check_sync_groups()
    assert _group_n_active(locked_id) == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_check_barriers_publishes_release_after_commit(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"
    participant.page_uuid = "hold-page-uuid"
    barrier = ReleaseAllBarrier(id_="release_all")
    barrier.receive_participant(participant)
    hold = TimelineHoldRecord(
        participant=participant,
        page_uuid=participant.page_uuid,
        hold_id="barrier:release_all",
        started_at=timenow(),
        expected_wait=1.5,
        max_wait_time=20,
        fix_time_credit=False,
        actual_wait_seconds=0,
        credited_wait_seconds=0,
    )
    participant.active_barriers[barrier.id].timeline_hold = hold
    db_session.add(hold)
    db_session.commit()
    participant_id = participant.id
    barrier_id = barrier.id
    wake_token = hold.wake_token

    publications = []

    def publish(payload, participant_ids, scope=None):
        with db.engine.connect() as connection:
            released, released_at = connection.execute(
                text(
                    """
                    SELECT participant_link_barrier.released,
                           timeline_hold.released_at
                    FROM participant_link_barrier
                    JOIN timeline_hold
                      ON timeline_hold.id =
                         participant_link_barrier.timeline_hold_id
                    WHERE participant_link_barrier.participant_id = :participant_id
                      AND participant_link_barrier.barrier_id = :barrier_id
                    """
                ),
                {
                    "participant_id": participant_id,
                    "barrier_id": barrier_id,
                },
            ).one()
        assert released
        assert released_at is not None
        publications.append((payload, participant_ids))

    monkeypatch.setattr(sockets, "publish_to_participants", publish)

    check_barriers()

    assert publications == [
        (
            {
                "type": "timeline_hold_wake",
                "targets": [
                    {
                        "wake_token": wake_token,
                        "reason": "barrier_released",
                    }
                ],
            },
            [participant_id],
        )
    ]
    assert not db_session().in_transaction()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_timeline_hold_wake_is_discarded_on_rollback(
    in_experiment_directory, db_session, monkeypatch
):
    participant = new_participant(get_experiment())
    participant.page_uuid = "rolled-back"
    hold = TimelineHoldRecord(
        participant=participant,
        page_uuid=participant.page_uuid,
        hold_id="rollback",
        started_at=timenow(),
        expected_wait=1,
        max_wait_time=20,
        fix_time_credit=False,
    )
    db_session.add(hold)
    db_session.flush()
    publications = _hold_wake_publications(monkeypatch)

    _enqueue_timeline_hold_wake(participant.id, page_uuid="rolled-back")
    db_session.rollback()
    db_session.commit()

    assert publications == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_deferred_hold_wakes_publish_only_on_context_exit(
    in_experiment_directory, db_session, monkeypatch
):
    """Inner commits must not publish while hold wakes are deferred."""
    participant = new_participant(get_experiment())
    hold = _participant_hold(participant, "deferred-wake", "defer")
    publications = _hold_wake_publications(monkeypatch)

    with _defer_timeline_hold_wakes():
        _enqueue_timeline_hold_wake(
            participant.id,
            page_uuid="deferred-wake",
            reason="barrier_released",
        )
        db_session.commit()
        db_session.commit()
        assert publications == []

    assert _released_wake_count(publications) == 1
    assert publications[0][0] == participant.id
    assert publications[0][1]["targets"][0]["wake_token"] == hold.wake_token


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_savepoint_release_does_not_publish_hold_wakes(
    in_experiment_directory, db_session, monkeypatch
):
    """A nested SAVEPOINT commit is not durable until the root transaction commits."""
    participant = new_participant(get_experiment())
    hold = _participant_hold(participant, "nested-wake", "nested")
    publications = _hold_wake_publications(monkeypatch)

    with db_session.begin_nested():
        _enqueue_timeline_hold_wake(
            participant.id,
            page_uuid="nested-wake",
            reason="barrier_released",
            hold=hold,
        )
        assert publications == []

    assert publications == []
    db_session.commit()
    assert _released_wake_count(publications) == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_savepoint_then_outer_rollback_does_not_publish_hold_wakes(
    in_experiment_directory, db_session, monkeypatch
):
    """Wakes queued under a SAVEPOINT must not publish after the root rolls back."""
    participant = new_participant(get_experiment())
    hold = _participant_hold(participant, "nested-rollback", "nested-rollback")
    publications = _hold_wake_publications(monkeypatch)

    with _defer_timeline_hold_wakes():
        with db_session.begin_nested():
            _enqueue_timeline_hold_wake(
                participant.id,
                page_uuid="nested-rollback",
                reason="barrier_released",
                hold=hold,
            )
        db_session.rollback()
        assert publications == []

    assert publications == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_session_close_discards_uncommitted_hold_wakes(
    in_experiment_directory, db_session, monkeypatch
):
    """``Session.close()`` fires no ``after_rollback``, so wakes must not leak."""
    participant = new_participant(get_experiment())
    hold = _participant_hold(participant, "closed-wake", "closed")
    publications = _hold_wake_publications(monkeypatch)

    _enqueue_timeline_hold_wake(
        participant.id,
        page_uuid="closed-wake",
        reason="barrier_released",
        hold=hold,
    )
    db_session.close()
    db_session.commit()

    assert publications == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_nested_rollback_keeps_wakes_queued_before_the_savepoint(
    in_experiment_directory, db_session, monkeypatch
):
    """A SAVEPOINT rollback must not drop wakes queued in the outer transaction."""
    participant = new_participant(get_experiment())
    outer = _participant_hold(participant, "outer-wake", "outer")
    inner = TimelineHoldRecord(
        participant=participant,
        page_uuid="inner-wake",
        hold_id="inner",
        started_at=timenow(),
        expected_wait=1,
        max_wait_time=20,
        fix_time_credit=False,
    )
    db.session.add(inner)
    db.session.flush()
    publications = _hold_wake_publications(monkeypatch)

    _enqueue_timeline_hold_wake(
        participant.id,
        page_uuid="outer-wake",
        reason="barrier_released",
        hold=outer,
    )
    try:
        with db_session.begin_nested():
            _enqueue_timeline_hold_wake(
                participant.id,
                page_uuid="inner-wake",
                reason="barrier_released",
                hold=inner,
            )
            raise RuntimeError("savepoint failed")
    except RuntimeError:
        pass
    db_session.commit()

    tokens = [
        target.get("wake_token")
        for _, payload in publications
        for target in payload.get("targets", [])
    ]
    assert tokens == [outer.wake_token]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_deferred_hold_wakes_keep_committed_payloads_after_later_rollback(
    in_experiment_directory, db_session, monkeypatch
):
    """A later rollback must not drop wakes that already committed."""
    participant = new_participant(get_experiment())
    hold = _participant_hold(participant, "deferred-rollback", "defer-rollback")
    publications = _hold_wake_publications(monkeypatch)

    with _defer_timeline_hold_wakes():
        _enqueue_timeline_hold_wake(
            participant.id,
            page_uuid="deferred-rollback",
            reason="barrier_released",
        )
        db_session.commit()
        _queue_arrival_update(participant.id, notice="Your partner is ready.")
        db_session.rollback()
        assert publications == []

    assert _released_wake_count(publications) == 1
    reasons = [
        target.get("reason")
        for _, payload in publications
        for target in payload.get("targets", [])
    ]
    assert reasons == ["barrier_released"]
    assert publications[0][1]["targets"][0]["wake_token"] == hold.wake_token


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_deferred_hold_wakes_flush_when_the_deferred_block_fails(
    in_experiment_directory, db_session, monkeypatch
):
    """Committed releases must still wake partners if a later check fails."""
    participant = new_participant(get_experiment())
    _participant_hold(participant, "deferred-error", "defer-error")
    publications = _hold_wake_publications(monkeypatch)

    with pytest.raises(RuntimeError, match="stacked check failed"):
        with _defer_timeline_hold_wakes():
            _enqueue_timeline_hold_wake(
                participant.id,
                page_uuid="deferred-error",
                reason="barrier_released",
            )
            db_session.commit()
            raise RuntimeError("stacked check failed")

    assert _released_wake_count(publications) == 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stacked_finalize_publishes_hold_wakes_at_check_commit(
    in_experiment_directory, db_session, monkeypatch
):
    """Last-arrival publishes partner wakes as soon as the release commits."""
    _assert_stacked_finalize_publishes_wakes(
        get_experiment(), monkeypatch, group_size=2
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_trio_stacked_finalize_publishes_wakes_for_every_waiter(
    in_experiment_directory, db_session, monkeypatch
):
    """Both waiting members are woken at the last-arrival check commit."""
    _assert_stacked_finalize_publishes_wakes(
        get_experiment(), monkeypatch, group_size=3
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_quartet_stacked_finalize_publishes_wakes_for_every_waiter(
    in_experiment_directory, db_session, monkeypatch
):
    """Three waiting members are woken at the last-arrival check commit."""
    _assert_stacked_finalize_publishes_wakes(
        get_experiment(), monkeypatch, group_size=4
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_shared_barrier_id_preserves_each_visit_waiting_mode(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    held_participant, page_participant = [new_participant(exp) for _ in range(2)]
    for participant in [held_participant, page_participant]:
        participant.status = "working"

    publications = _hold_wake_publications(monkeypatch)

    held_barrier = WaitForTwoBarrier(id_="shared")
    held_barrier.receive_participant(held_participant)
    held_barrier.waiting_logic.consume(exp, held_participant)
    page_barrier = WaitForTwoBarrier(id_="shared", waiting_logic=WaitPage(wait_time=1))
    page_barrier.receive_participant(page_participant)
    held_wake_token = held_participant.timeline_holds[0].wake_token
    _commit_barrier_arrivals()

    release_targets = [
        target
        for _, payload in publications
        for target in payload["targets"]
        if target.get("reason") == "barrier_released"
    ]
    assert [target["wake_token"] for target in release_targets] == [held_wake_token]
    assert all("page_uuid" not in target for target in release_targets)

    check_barriers()
    assert [
        target["wake_token"]
        for _, payload in publications
        for target in payload["targets"]
        if target.get("reason") == "barrier_released"
    ] == [held_wake_token]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_barrier_hold_releases_link_before_pending_redirect(
    in_experiment_directory, db_session
):
    participant = new_participant(get_experiment())
    participant.status = "working"
    participant.page_uuid = "redirect-hold"
    barrier = ReleaseAllBarrier(id_="redirect")
    barrier.receive_participant(participant)
    hold_page = barrier.waiting_logic
    hold_page.consume(get_experiment(), participant)
    participant.pending_redirect = "unsuccessful_end"

    hold_page.prepare_to_resume(participant)

    assert participant.barrier_links[0].released
    assert participant.barrier_links[0].timeline_hold.released_at is not None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_barrier_hold_creates_new_record_after_resume(
    in_experiment_directory, db_session
):
    participant = new_participant(get_experiment())
    participant.status = "working"
    barrier = ReleaseAllBarrier(id_="new_loop")
    barrier.receive_participant(participant)
    hold_page = barrier.waiting_logic
    hold_page.consume(get_experiment(), participant)
    first_record = participant.active_barriers[barrier.id].timeline_hold
    assert first_record.deadline_at is not None
    hold_page.account_wait(participant, settle=True)

    hold_page.consume(get_experiment(), participant)
    db_session.flush()

    assert (
        TimelineHoldRecord.query.filter_by(participant_id=participant.id).count() == 2
    )
    assert participant.active_barriers[barrier.id].timeline_hold is not first_record


def test_group_barrier_rejects_bound_method():
    class Dummy:
        def handler(
            self, group, participants
        ):  # pragma: no cover - used for validation
            return None

    with pytest.raises(ValueError, match="module-level"):
        GroupBarrier(id_="bad", group_type="group", on_release=Dummy().handler)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_accepts_orm_instance_method(in_experiment_directory, db_session):
    DummyModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    instance = DummyModel(id=get_random_id())
    db_session.add(instance)
    db_session.flush()

    barrier = GroupBarrier(
        id_="orm_method",
        group_type="group",
        on_release=instance.on_release,
    )
    assert isinstance(barrier.on_release, SerializedCallable)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_deleted_orm_callback_receiver_is_rejected(in_experiment_directory, db_session):
    DummyModel.__table__.create(bind=db_session.get_bind(), checkfirst=True)
    instance = DummyModel(id=get_random_id())
    db_session.add(instance)
    db_session.flush()
    serialized = barrier_spec_json(
        GroupBarrier(
            id_="orm_gone",
            group_type="group",
            on_release=instance.on_release,
        )
    )
    db_session.delete(instance)
    db_session.flush()

    with pytest.raises(BarrierSpecError, match="no longer exists"):
        barrier_from_spec_json(serialized)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_async_job_events_wake_timeline_holds(
    in_experiment_directory, db_session, monkeypatch, caplog
):
    wakes = []
    monkeypatch.setattr(
        "psynet.timeline_hold._queue_timeline_hold_wake",
        lambda participant_id, reason=None, **kwargs: wakes.append(reason),
    )

    participant = new_participant(get_experiment())
    db_session.flush()
    # Saved without enqueue() so that the test runs the jobs itself.
    finished = LocalAsyncJob(async_job_noop, participant=participant)
    timed_out = WorkerAsyncJob(async_job_noop, participant=participant, timeout=30)
    cancelled = WorkerAsyncJob(async_job_noop, participant=participant)
    db_session.add_all([finished, timed_out, cancelled])
    timed_out.timeout_scheduled_for = datetime.now() - timedelta(seconds=1)
    db_session.flush()
    finished_id = finished.id
    cancelled_id = cancelled.id
    with caplog.at_level("WARNING", logger="psynet"):
        db_session.commit()
    assert caplog.text.count("never enqueued") == 3

    LocalAsyncJob.call_function(finished_id)
    WorkerAsyncJob.check_timeouts()
    WorkerAsyncJob.query.get(cancelled_id).cancel()

    assert wakes == [
        "async_job_finished",
        "async_job_timed_out",
        "async_job_cancelled",
    ]


def test_group_barrier_late_after_rejects_bad_action():
    with pytest.raises(ValueError, match="late_action"):
        GroupBarrier(
            id_="late_after_bad_action",
            group_type="group",
            late_after=5,
            late_action="remove",
        )


def test_group_barrier_max_wait_time_with_late_after():
    def barrier(**kwargs):
        return GroupBarrier(id_="round", group_type="group", **kwargs)

    def late_barrier(**kwargs):
        return barrier(late_after=30, late_action="fail", **kwargs)

    assert barrier().max_wait_time == 20
    assert barrier(max_wait_time=None).max_wait_time is None
    assert late_barrier().max_wait_time is None
    assert late_barrier(max_wait_time=None).max_wait_time is None
    for max_wait_time in (300, _shrinking_max_wait_time):
        with pytest.raises(ValueError, match="Leave max_wait_time unset"):
            late_barrier(max_wait_time=max_wait_time)
    with pytest.raises(ValueError, match="late_after must be positive"):
        barrier(late_after=0, late_action="fail")
    with pytest.raises(ValueError, match="use late_action instead"):
        late_barrier(max_wait_action="leave_group")
    with pytest.raises(ValueError, match="Pass late_action with late_after"):
        barrier(late_after=30)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_make_late_now_needs_a_waiting_bot_and_late_after(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    waiter, quiet = [new_participant(exp) for _ in range(2)]
    group = SimpleSyncGroup(group_type="main", initial_group_size=2)
    db_session.add(group)
    for p in (waiter, quiet):
        p.status = "working"
        group.add_participant(p)
    db_session.commit()
    bots = [SimpleNamespace(id=p.id) for p in (waiter, quiet)]
    with pytest.raises(ValueError, match="None of the bots is waiting at 'round'"):
        make_late_now(bots, "round")
    _arrive_at_group_barrier(exp, GroupBarrier("round", group_type="main"), waiter)
    db_session.commit()
    with pytest.raises(ValueError, match="'round' has no late_after"):
        make_late_now(bots, "round")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("passed_before", [True, False])
def test_make_late_now_keeps_who_left_since_the_last_pass(
    in_experiment_directory, db_session, monkeypatch, passed_before
):
    """An earlier leaver counts in ``left`` only if they left after the group's last pass, or its creation."""
    monkeypatch.setattr(psynet.bot, "advance_past_wait_pages", lambda *a, **k: None)
    exp = get_experiment()
    waiter, quiet, earlier = [new_participant(exp) for _ in range(3)]
    group = SimpleSyncGroup(group_type="main", initial_group_size=3, quorum=2)
    db_session.add(group)
    for p in (waiter, quiet, earlier):
        p.status = "working"
        group.add_participant(p)
    group.remove_participant(earlier, reason="late")
    if passed_before:
        group.last_barrier_pass_time = timenow()
    barrier = GroupBarrier(
        "round", group_type="main", late_after=30, late_action="fail"
    )
    _arrive_at_group_barrier(exp, barrier, waiter)
    db_session.commit()
    group_id, earlier_id = group.id, earlier.id

    make_late_now([SimpleNamespace(id=waiter.id)], "round")

    group = SyncGroup.query.get(group_id)
    since = group.last_barrier_pass_time or group.creation_time
    left = [p.id for p in group._members_who_left_since(since)]
    assert left == ([] if passed_before else [earlier_id])


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("quorum", [2, 3])
def test_group_barrier_late_after_removes_missing_participants(
    in_experiment_directory, db_session, monkeypatch, quorum
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="late_after_leave_group",
        group_type="main",
        late_after=5,
        late_action="leave_group",
    )

    # Create 4 participants in the same sync group, but only 2 "reach" this barrier.
    participants = [new_participant(exp) for _ in range(4)]
    for p in participants:
        p.status = "working"
    waiting_participants = participants[:2]
    missing_participants = participants[2:]

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=4,
        max_group_size=4,
        quorum=quorum,
        n_active_participants=4,
        accepts_top_ups=False,
        below_quorum="fail",
    )
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    _set_group_clocks_in_the_past(group, seconds=10)
    db_session.commit()
    publications = _hold_wake_publications(monkeypatch)

    for missing_participant in missing_participants:
        missing_participant.page_uuid = f"round-page-{missing_participant.id}"
    barrier.check_waiting_participants(waiting_participants)
    for missing_participant in missing_participants:
        late_answer = InfoPage("Your move").process_response(
            raw_answer=None,
            blobs={},
            metadata={"too_late_for_group": False},
            experiment=exp,
            participant=missing_participant,
        )
        assert late_answer.too_late_for_group
    if quorum == 3:
        # Both are removed for being late before the group dissolves.
        assert all(p.failed for p in waiting_participants)
        for missing_participant in missing_participants:
            assert missing_participant.sync_group_links[0].removal_reason == "late"
            assert pending_arrival_notice_for(missing_participant).startswith(
                "Your group went on without you"
            )
        return
    released = barrier.choose_who_to_release(waiting_participants)
    db_session.commit()

    assert set(released) == set(waiting_participants)
    removal = {
        "notice": "Your group went on without you. Please continue.",
        "removed": True,
    }
    assert removal in [
        {key: target.get(key) for key in removal}
        for participant_id, payload in publications
        if participant_id == missing_participants[0].id
        for target in payload["targets"]
    ]
    for missing_participant in missing_participants:
        assert missing_participant not in group.active_participants
        assert missing_participant.sync_group_links[0].removal_reason == "late"
        assert arrival_notice_payload(missing_participant.unique_id)["removed"]
    missing_participants[0].page_uuid = "next-page"
    assert pending_arrival_notice_for(missing_participants[0]) is None
    on_time_answer = InfoPage("Your move").process_response(
        raw_answer=None,
        blobs={},
        metadata={"too_late_for_group": True},
        experiment=exp,
        participant=waiting_participants[0],
    )
    assert not on_time_answer.too_late_for_group


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_also_leave_removes_a_late_member_from_the_listed_groups_only(
    in_experiment_directory, db_session
):
    """A member late for their pair also leaves the cohort and stays in groups of unlisted types."""
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="round",
        group_type="pair",
        late_after=5,
        late_action="leave_group",
        also_leave=["cohort"],
    )
    late, on_time, other = [new_participant(exp) for _ in range(3)]
    groups = {}
    for group_type, members in [
        ("cohort", [late, on_time, other]),
        ("pair", [late, on_time]),
        ("chat", [late, other]),
    ]:
        group = SimpleSyncGroup(
            group_type=group_type,
            initial_group_size=len(members),
            max_group_size=len(members),
            quorum=1,
            n_active_participants=len(members),
            accepts_top_ups=False,
            below_quorum="continue_without_group",
        )
        db_session.add(group)
        for p in members:
            p.status = "working"
            group.add_participant(p)
        _set_group_clocks_in_the_past(group, seconds=10)
        groups[group_type] = group
    db_session.commit()

    barrier.check_waiting_participants([on_time])
    db_session.commit()

    assert late not in groups["pair"].active_participants
    assert set(groups["cohort"].active_participants) == {on_time, other}
    assert late.sync_group_removal_reason("cohort") == "late"
    assert set(late.active_sync_groups) == {"chat"}


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            dict(late_action="fail", also_leave=["cohort"]),
            "only takes effect with late_action='leave_group'",
        ),
        (dict(late_action="leave_group", also_leave="cohort"), "must be a list"),
        (dict(late_action="leave_group", also_leave=["pair"]), "own group type"),
        (
            dict(late_action="leave_group", also_leave=["cohort", "cohort"]),
            "more than once",
        ),
        (dict(late_action="leave_all_groups"), "late_action must be one of"),
    ],
)
def test_also_leave_is_validated(kwargs, message):
    with pytest.raises(ValueError, match=message):
        GroupBarrier(id_="round", group_type="pair", late_after=5, **kwargs)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("both_pairs_late", [False, True])
def test_late_member_leaving_the_cohort_can_fail_it_with_a_warning(
    in_experiment_directory, db_session, caplog, both_pairs_late
):
    """Leaving a cohort at full quorum fails its other members, but never another late member."""
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="round",
        group_type="pair",
        late_after=5,
        late_action="leave_group",
        also_leave=["cohort"],
    )
    late_a, on_time_a, b1, b2 = [new_participant(exp) for _ in range(4)]
    for group_type, members, below_quorum in [
        ("cohort", [late_a, on_time_a, b1, b2], "fail"),
        ("pair", [late_a, on_time_a], "continue_without_group"),
        ("pair", [b1, b2], "continue_without_group"),
    ]:
        group = SimpleSyncGroup(
            group_type=group_type,
            initial_group_size=len(members),
            max_group_size=len(members),
            quorum=len(members) if group_type == "cohort" else 1,
            accepts_top_ups=False,
            below_quorum=below_quorum,
        )
        db_session.add(group)
        for p in members:
            p.status = "working"
            group.add_participant(p)
        _set_group_clocks_in_the_past(group, seconds=10)
    db_session.commit()

    waiting = [on_time_a, b2] if both_pairs_late else [on_time_a, b1, b2]
    with caplog.at_level("WARNING", logger="psynet"):
        barrier.check_waiting_participants(waiting)
    db_session.commit()

    late = [late_a, b1] if both_pairs_late else [late_a]
    assert all(not p.failed for p in late)
    assert all(p.sync_group_removal_reason("cohort") == "late" for p in late)
    assert all(p.failed for p in waiting)
    assert "below_quorum='continue_without_group'" in caplog.text


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("passed_a_barrier", [False, True])
def test_late_after_counts_from_joining_the_group(
    in_experiment_directory, db_session, passed_a_barrier
):
    """A GroupBarrier removes members late since grouping or the last barrier, but not a newcomer."""
    exp = get_experiment()
    grouper = SimpleGrouper("main", initial_group_size=3, quorum=2, below_quorum="fail")
    participants = _working_participants(exp, 3)
    for participant in participants:
        _arrive_at_group_barrier(exp, grouper, participant)
    _commit_barrier_arrivals()
    group = participants[0].sync_group
    assert group.last_barrier_pass_time is None
    for link in group.participant_links:
        link.arrival_time -= timedelta(seconds=10)
        link.admitted_at -= timedelta(seconds=10)
    if passed_a_barrier:
        group.last_barrier_pass_time = timenow() - timedelta(seconds=10)
    (newcomer,) = _working_participants(exp, 1)
    group.add_participant(newcomer)
    barrier = GroupBarrier(
        id_="first_after_grouper",
        group_type="main",
        late_after=5,
        late_action="leave_group",
    )
    waiting, late = participants[:2], participants[2]

    barrier.check_waiting_participants(waiting)
    released = barrier.choose_who_to_release(waiting)

    assert late not in group.active_participants
    assert newcomer in group.active_participants
    assert released == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_late_after_follows_a_timed_page(
    in_experiment_directory, db_session, monkeypatch
):
    """A between-barrier timeout waits for a timed page's answer, but no longer."""
    exp = get_experiment()
    grouper = SimpleGrouper("main", initial_group_size=7, quorum=2, below_quorum="fail")
    participants = _working_participants(exp, 7)
    (
        waiting,
        deciding,
        moved_on,
        left_timed_page,
        no_time_limit,
        before_joining,
        at_other_barrier,
    ) = participants

    _start_timed_page(exp, before_joining, 60)
    for participant in participants:
        _arrive_at_group_barrier(exp, grouper, participant)
    _commit_barrier_arrivals()
    group = participants[0].sync_group
    for link in group.participant_links:
        link.arrival_time -= timedelta(seconds=30)
        link.admitted_at -= timedelta(seconds=30)
    for participant, time_limit in [
        (deciding, 25),
        (moved_on, 14),
        (left_timed_page, 8),
        (at_other_barrier, 25),
    ]:
        _start_timed_page(exp, participant, time_limit)
    # Another barrier on the way doesn't end this group's round.
    _arrive_at_group_barrier(
        exp, SimpleGrouper("other", initial_group_size=2), at_other_barrier
    )
    later = timenow() + timedelta(seconds=20)
    monkeypatch.setattr("psynet.sync.timenow", lambda: later)
    barrier = GroupBarrier(
        id_="after_timed_page",
        group_type="main",
        late_after=20,
        late_action="leave_group",
    )

    barrier.check_waiting_participants([waiting])

    assert set(group.active_participants) == {
        waiting,
        deciding,
        moved_on,
        at_other_barrier,
    }
    for participant in (left_timed_page, no_time_limit, before_joining):
        assert participant.sync_group_links[0].removal_reason == "late"


def _start_timed_page(exp, participant, time_limit):
    # Test arrivals skip the timeline step that ends a barrier's waiting.
    participant.waiting_barrier_id = None
    ModularPage("choose", "Pick", time_limit=time_limit, time_estimate=5).consume(
        exp, participant
    )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_group_barrier_pass_forgets_earlier_timed_pages(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first, second = _working_participants(exp, 2)
    for participant in (first, second):
        _arrive_at_group_barrier(
            exp, SimpleGrouper("main", initial_group_size=2), participant
        )
    _commit_barrier_arrivals()
    group = first.sync_group
    _start_timed_page(exp, first, 60)
    for participant in (first, second):
        _arrive_at_group_barrier(
            exp, GroupBarrier("passed", group_type="main"), participant
        )
    _commit_barrier_arrivals()
    group.last_barrier_pass_time -= timedelta(seconds=30)
    for link in group.participant_links:
        link.arrival_time -= timedelta(seconds=30)
        link.admitted_at -= timedelta(seconds=30)
    barrier = GroupBarrier(
        id_="next",
        group_type="main",
        late_after=10,
        late_action="leave_group",
    )
    barrier.check_waiting_participants([second])
    assert first not in group.active_participants


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_time_out_before_joining_an_open_group_gives_no_dash(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "main",
        initial_group_size=2,
        max_group_size=None,
        join_existing_groups=True,
        use_admission_points=False,
    )
    founders = _working_participants(exp, 2)
    for participant in founders:
        _arrive_at_group_barrier(exp, grouper, participant)
    _commit_barrier_arrivals()
    (newcomer,) = _working_participants(exp, 1)
    _start_timed_page(exp, newcomer, 10)
    newcomer.page_deadline = timenow() - timedelta(seconds=10)
    ModularPage("choose", "Pick", time_limit=10, time_estimate=5).process_response(
        raw_answer=None,
        blobs=None,
        metadata={"time_limit_reached": True},
        experiment=exp,
        participant=newcomer,
    )
    assert newcomer.timed_out_since_barrier
    grouper._join_existing_groups(newcomer)
    _arrive_at_group_barrier(exp, GroupBarrier("next", group_type="main"), newcomer)
    assert not newcomer.active_barriers["next"].ran_out_of_time


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_skipping_a_group_barrier_forgets_a_time_out(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    (kicked,) = _working_participants(exp, 1)
    kicked.timed_out_since_barrier = True
    skipped = GroupBarrier("decided", group_type="pair", late_action="leave_group")
    elts = skipped.resolve()
    (switch,) = [
        elt
        for elt in elts
        if hasattr(elt, "branch_start_elts") and elt.label.endswith(":in_group")
    ]
    skip = elts[elts.index(switch.branch_start_elts[False]) + 1]
    assert isinstance(skip, CodeBlock)
    skip.consume(exp, kicked)
    grouper = SimpleGrouper("pair", initial_group_size=2)
    _arrive_at_group_barrier(exp, grouper, kicked)
    assert not kicked.active_barriers[grouper.id].ran_out_of_time


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_late_after_removal_releases_waiters_after_dissolution(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="late_after_leave_group_below_quorum",
        group_type="main",
        late_after=5,
        late_action="leave_group",
    )

    participants = [new_participant(exp) for _ in range(3)]
    for p in participants:
        p.status = "working"
    waiting_participants = participants[:2]
    missing_participant = participants[2]

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=3,
        n_active_participants=3,
        accepts_top_ups=False,
        below_quorum="continue_without_group",
    )
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    _set_group_clocks_in_the_past(group, seconds=10)
    db_session.commit()

    barrier.check_waiting_participants(waiting_participants)
    released = barrier.choose_who_to_release(waiting_participants)

    assert group.active_participants == []
    assert missing_participant not in released
    assert set(released) == set(waiting_participants)
    # Everyone carries on alone. The late member is told they were too slow,
    # on the page they are on; the others are told why on their next page.
    assert pending_arrival_notice_for(missing_participant).startswith(
        "Your group went on without you"
    )
    for p in waiting_participants:
        InfoPage("Next").consume(exp, p)
        assert _removed_from_group_notice(p).startswith("Too few members")


def test_groups_that_can_shrink_need_an_explicit_below_quorum():
    with pytest.raises(ValueError, match="Pass below_quorum"):
        SimpleGrouper("team", initial_group_size=3, quorum=2)
    SimpleGrouper("team", initial_group_size=3, quorum=2, below_quorum="fail")

    def make_timeline(pair, late_action="leave_group", cohort=None, also_leave=None):
        return Timeline(
            SimpleGrouper(
                "cohort", initial_group_size=4, quorum=4, below_quorum=cohort
            ),
            SimpleGrouper("pair", initial_group_size=2, below_quorum=pair),
            GroupBarrier(
                id_="round",
                group_type="pair",
                late_after=30,
                late_action=late_action,
                also_leave=also_leave,
            ),
            InfoPage("Done", time_estimate=1),
        )

    with pytest.raises(ValueError, match="Pass below_quorum to SimpleGrouper"):
        make_timeline(pair=None, late_action="fail")
    make_timeline(pair="fail", late_action="fail")
    with pytest.raises(ValueError, match="carry on alone"):
        make_timeline(pair="fail")
    # A late member also leaves the groups in also_leave.
    ok = "continue_without_group"
    with pytest.raises(ValueError, match="Pass below_quorum to SimpleGrouper"):
        make_timeline(pair=ok, also_leave=["cohort"])
    with pytest.raises(ValueError, match="carry on alone"):
        make_timeline(pair=ok, also_leave=["cohort"], cohort="fail")
    make_timeline(pair=ok, also_leave=["cohort"], cohort=ok)


def test_a_custom_grouper_s_group_without_a_quorum_passes_its_barrier():
    member = SimpleNamespace(id=1)
    group = SyncGroup(group_type="custom")
    assert _group_barrier_outcome(group, [member], {1}, "round") == "release"


@pytest.mark.parametrize(
    "use_admission_points, admission_point, top_up_wait, stopped_before, raises",
    [
        (False, False, None, False, True),
        (False, False, 60, False, False),
        (False, False, None, True, False),
        (True, False, None, False, False),
        (True, True, None, False, True),
    ],
)
def test_late_after_barriers_need_a_top_up_wait_while_groups_take_newcomers(
    use_admission_points, admission_point, top_up_wait, stopped_before, raises
):
    lobby_admits = use_admission_points and not admission_point

    def make_timeline():
        return Timeline(
            SimpleGrouper(
                "team",
                initial_group_size=2,
                join_existing_groups=True,
                use_admission_points=use_admission_points,
                target_group_size=2 if use_admission_points else None,
                top_up_wait=top_up_wait,
                below_quorum="continue_without_group",
            ),
            GroupBarrier(
                "lobby",
                group_type="team",
                stop_top_ups=stopped_before,
                admission_point=lobby_admits,
                newcomer_max_wait=60 if lobby_admits else None,
            ),
            GroupBarrier(
                "round",
                group_type="team",
                late_after=30,
                late_action="leave_group",
                admission_point=admission_point,
                newcomer_max_wait=60 if admission_point else None,
            ),
            InfoPage("Done", time_estimate=1),
        )

    if raises:
        with pytest.raises(ValueError, match="Pass top_up_wait"):
            make_timeline()
    else:
        make_timeline()


@pytest.mark.parametrize(
    "reason, dissolved",
    [("finished", False), ("moved_on", False), ("removed_by_experimenter", True)],
)
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_members_who_finish_dont_dissolve_the_group(
    in_experiment_directory, db_session, reason, dissolved
):
    exp = get_experiment()
    first, second, last = [new_participant(exp) for _ in range(3)]
    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=2,
        accepts_top_ups=False,
        below_quorum="continue_without_group",
    )
    db_session.add(group)
    for p in (first, second, last):
        p.status = "working"
        group.add_participant(p)
    db_session.commit()

    group.remove_participant(first, reason="removed_by_experimenter")
    group.remove_participant(second, reason=reason)

    assert last.in_sync_group("main") is not dissolved
    InfoPage("Next").consume(exp, last)
    assert (_removed_from_group_notice(last) is not None) is dissolved


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_leave_group_takes_the_participant_out_as_finished(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    leaver, stayer = [new_participant(exp) for _ in range(2)]
    group = SimpleSyncGroup(
        group_type="main", initial_group_size=2, max_group_size=2, quorum=2
    )
    db_session.add(group)
    for p in (leaver, stayer):
        p.status = "working"
        group.add_participant(p)
    db_session.commit()

    step = leave_group("main")
    step.consume(exp, leaver)
    step.consume(exp, leaver)

    assert not leaver.in_sync_group("main")
    assert leaver.sync_group_removal_reason("main") == "finished"
    assert stayer.in_sync_group("main")
    for reason in ("bored", None):
        with pytest.raises(ValueError, match="reason must be one of"):
            leave_group("main", reason=reason)


@pytest.mark.parametrize("below_quorum", ["fail", "continue_without_group"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_removing_a_late_member_dissolves_a_group_without_top_ups(
    in_experiment_directory, db_session, below_quorum
):
    """``reason="late"``, as in the round-based recipe, dissolves a cohort without top-ups."""
    exp = get_experiment()
    late, partner = [new_participant(exp) for _ in range(2)]
    group = SimpleSyncGroup(
        group_type="cohort",
        initial_group_size=2,
        max_group_size=2,
        quorum=2,
        accepts_top_ups=False,
        below_quorum=below_quorum,
    )
    db_session.add(group)
    for p in (late, partner):
        p.status = "working"
        group.add_participant(p)
    db_session.commit()

    group.remove_participant(late, reason="late")

    assert not partner.in_sync_group("cohort")
    assert partner.failed == (below_quorum == "fail")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_late_member_leaving_a_pair_fails_the_partner_with_a_warning(
    in_experiment_directory, db_session, caplog
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="late_pair", group_type="main", late_after=5, late_action="leave_group"
    )
    on_time, late = new_participant(exp), new_participant(exp)
    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=2,
        max_group_size=2,
        quorum=2,
        accepts_top_ups=False,
        below_quorum="fail",
    )
    db_session.add(group)
    for p in (on_time, late):
        p.status = "working"
        group.add_participant(p)
    _set_group_clocks_in_the_past(group, seconds=10)
    db_session.commit()

    with caplog.at_level("WARNING", logger="psynet"):
        barrier.check_waiting_participants([on_time])
    db_session.commit()

    assert on_time.failed and not late.failed
    assert "below_quorum='continue_without_group'" in caplog.text
    assert pending_arrival_notice_for(late).startswith("Your partner went on")


@pytest.mark.parametrize("action", ["leave_group", "fail"])
@pytest.mark.parametrize("quorum", [2, 3])
@pytest.mark.parametrize("accepts_top_ups", [False, True])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_would_release_predicts_late_after(
    in_experiment_directory, db_session, action, quorum, accepts_top_ups
):
    """The release peek must see the late member the check will remove."""
    exp = get_experiment()
    barrier = GroupBarrier(
        id_=f"would_release_between_{action}_{quorum}_{accepts_top_ups}",
        group_type="main",
        late_after=5,
        late_action=action,
    )
    participants = [new_participant(exp) for _ in range(3)]
    for p in participants:
        p.status = "working"
    waiting_participants = participants[:2]
    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=quorum,
        n_active_participants=3,
        accepts_top_ups=accepts_top_ups,
        below_quorum="continue_without_group",
    )
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    _set_group_clocks_in_the_past(group, seconds=10)
    db_session.commit()
    # A group that accepts top-ups waits below its minimum instead of dissolving.
    expected = set() if accepts_top_ups and quorum == 3 else set(waiting_participants)

    assert barrier.would_release(waiting_participants) is bool(expected)
    assert len(group.active_participants) == 3
    assert not db_session.dirty

    barrier.check_waiting_participants(waiting_participants)
    assert set(barrier.choose_who_to_release(waiting_participants)) == expected


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_late_after_fail_missing_participants(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="late_after_fail",
        group_type="main",
        late_after=5,
        late_action="fail",
    )

    participants = [new_participant(exp) for _ in range(3)]
    for p in participants:
        p.status = "working"
    waiting_participants = participants[:2]
    missing_participant = participants[2]

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=2,
        n_active_participants=3,
        accepts_top_ups=False,
        below_quorum="fail",
    )
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    _set_group_clocks_in_the_past(group, seconds=10)
    db_session.commit()

    barrier.check_waiting_participants(waiting_participants)
    released = barrier.choose_who_to_release(waiting_participants)

    assert missing_participant.failed is True
    assert missing_participant not in group.active_participants
    assert set(released) == set(waiting_participants)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize(
    "below_quorum, failed",
    [
        ("fail", [True, True]),
        ("continue_without_group", [False, False]),
    ],
)
def test_group_barrier_below_quorum(
    in_experiment_directory, db_session, below_quorum, failed
):
    exp = get_experiment()
    barrier = GroupBarrier(id_="below_quorum", group_type="main")
    grouper = SimpleGrouper(
        "main", initial_group_size=3, quorum=3, below_quorum=below_quorum
    )

    participants = [new_participant(exp) for _ in range(2)]
    for p in participants:
        p.status = "working"

    # Configure group so it's below quorum and doesn't accept top-ups.
    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=3,
        n_active_participants=2,
        accepts_top_ups=False,
        below_quorum=grouper.below_quorum,
    )
    group.last_barrier_pass_time = timenow()
    other_group = SimpleSyncGroup(
        group_type="other",
        initial_group_size=2,
        max_group_size=2,
        quorum=1,
        accepts_top_ups=False,
    )
    db_session.add_all([group, other_group])
    for p in participants:
        group.add_participant(p)
        other_group.add_participant(p)
    db_session.commit()
    db_session.expire(group)

    released = barrier.choose_who_to_release(waiting_participants=participants)

    assert set(released) == set(participants)
    assert group.active_participants == []
    assert all(p.active_sync_groups.get("main") is None for p in participants)
    assert [p.failed for p in participants] == failed
    assert [p.sync_group_removal_reason("main") for p in participants] == [
        "group_dissolved"
    ] * len(participants)
    assert [p.sync_group_removal_reason("other") for p in participants] == [
        "left_experiment" if was_failed else None for was_failed in failed
    ]
    # Members who carry on alone are told why on their next page.
    for p, was_failed in zip(participants, failed):
        InfoPage("Next").consume(exp, p)
        notice = _removed_from_group_notice(p)
        assert (notice is None) == was_failed
        assert was_failed or notice.startswith("Your partner is no longer")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_below_min_size_only_releases_waiting_participants(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="below_min_size_partial_wait",
        group_type="main",
    )

    waiting_participant = new_participant(exp)
    non_waiting_participant = new_participant(exp)
    for participant in [waiting_participant, non_waiting_participant]:
        participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        quorum=3,
        n_active_participants=2,
        accepts_top_ups=False,
        below_quorum="fail",
    )
    db_session.add(group)
    group.add_participant(waiting_participant)
    group.add_participant(non_waiting_participant)
    db_session.commit()

    released = barrier.choose_who_to_release(waiting_participants=[waiting_participant])

    assert released == [waiting_participant]
    assert waiting_participant.failed
    assert non_waiting_participant.failed
    assert group.active_participants == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("below_quorum", ["fail", "continue_without_group"])
def test_waiter_leaving_a_pair_after_max_wait(
    in_experiment_directory, db_session, below_quorum
):
    exp = get_experiment()
    waiter, absent = new_participant(exp), new_participant(exp)
    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=2,
        max_group_size=2,
        quorum=2,
        accepts_top_ups=False,
        below_quorum=below_quorum,
    )
    db_session.add(group)
    for p in (waiter, absent):
        p.status = "working"
        group.add_participant(p)
    barrier = GroupBarrier(
        id_="pair_max_wait", group_type="main", max_wait_action="leave_group"
    )
    barrier.receive_participant(waiter)
    db_session.commit()

    barrier.handle_max_wait_timeout(waiter)
    db_session.commit()

    assert not waiter.failed
    assert absent.failed == (below_quorum == "fail")
    assert waiter.sync_group_removal_reason("main") == "waited_too_long"
    InfoPage("Next").consume(exp, waiter)
    assert _removed_from_group_notice(waiter).startswith("Your partner didn't")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("waiting_page", [False, True])
def test_poller_failing_a_waiter_after_max_wait(
    in_experiment_directory, db_session, waiting_page
):
    exp = get_experiment()
    (waiter, absent), _ = _pair_sync_group(exp, db_session)
    barrier = GroupBarrier(
        id_="abandoned",
        group_type="main",
        max_wait_time=300,
        waiting_logic=InfoPage("Filler", time_estimate=5) if waiting_page else None,
    )
    _arrive_at_group_barrier(exp, barrier, waiter)
    db.session.commit()
    rows = ParticipantLinkBarrier if waiting_page else TimelineHoldRecord
    rows.query.filter_by(participant_id=waiter.id).update({"deadline_at": timenow()})
    db.session.commit()
    ids = waiter.id, absent.id

    check_barriers()
    db.session.expire_all()

    waiter, absent = (Participant.query.get(i) for i in ids)
    hold = "while_loop" if waiting_page else "timeline_hold"
    assert set(waiter.failure_tags) == {f"{hold}:barrier:abandoned", "fail_on_timeout"}
    assert waiter.sync_group_removal_reason("main") == "waited_too_long"
    assert absent.sync_group_removal_reason("main") == "group_dissolved"
    assert absent.failure_tags == ["sync group below quorum"]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stopping_top_ups_dissolves_a_group_below_quorum(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    members = [new_participant(exp) for _ in range(3)]
    group = SimpleSyncGroup(
        group_type="team",
        initial_group_size=3,
        max_group_size=3,
        quorum=3,
        accepts_top_ups=True,
        below_quorum="continue_without_group",
    )
    db_session.add(group)
    for p in members:
        p.status = "working"
        group.add_participant(p)
    db_session.commit()

    members[0].fail("quit")
    assert group.active
    assert [p.in_sync_group("team") for p in members[1:]] == [True, True]

    group.stop_top_ups()
    db_session.commit()

    assert not any(p.failed for p in members[1:])
    assert [p.sync_group_removal_reason("team") for p in members] == [
        "left_experiment",
        "group_dissolved",
        "group_dissolved",
    ]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_top_up_wait_limits_how_long_a_group_waits_for_newcomers(
    in_experiment_directory, db_session
):
    with pytest.raises(ValueError, match="join_existing_groups"):
        SimpleGrouper("team", initial_group_size=2, top_up_wait=10)
    exp = get_experiment()
    grouper = SimpleGrouper(
        "team",
        initial_group_size=2,
        join_existing_groups=True,
        use_admission_points=False,
        below_quorum="continue_without_group",
        top_up_wait=10,
    )
    barrier = GroupBarrier(id_="game_starts", group_type="team")
    quitter, waiter = [new_participant(exp) for _ in range(2)]
    for p in (quitter, waiter):
        p.status = "working"
    group = grouper._make_group([quitter, waiter], initial_group_size=2)
    db_session.commit()

    quitter.fail("quit")
    group.below_quorum_since -= timedelta(seconds=11)
    _arrive_at_group_barrier(exp, barrier, waiter)
    # The wait starts once the remaining members are all at the barrier.
    assert barrier.choose_who_to_release([waiter]) == []
    waiter.active_barriers["game_starts"].arrival_time -= timedelta(seconds=11)
    assert barrier.choose_who_to_release([waiter]) == [waiter]
    assert not waiter.failed and not group.accepts_top_ups
    assert group.top_ups_stopped_at is not None
    assert waiter.sync_group_removal_reason("team") == "group_dissolved"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_top_up_wait_starts_when_the_last_remaining_member_arrives(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "team",
        initial_group_size=3,
        quorum=3,
        join_existing_groups=True,
        use_admission_points=False,
        below_quorum="continue_without_group",
        top_up_wait=10,
    )
    barrier = GroupBarrier(id_="game_starts", group_type="team")
    quitter, early, late = [new_participant(exp) for _ in range(3)]
    for p in (quitter, early, late):
        p.status = "working"
    group = grouper._make_group([quitter, early, late], initial_group_size=3)
    db_session.commit()

    quitter.fail("quit")
    group.below_quorum_since -= timedelta(seconds=30)
    _arrive_at_group_barrier(exp, barrier, early)
    early.active_barriers["game_starts"].arrival_time -= timedelta(seconds=30)
    assert barrier.choose_who_to_release([early]) == []
    _arrive_at_group_barrier(exp, barrier, late)
    assert barrier.choose_who_to_release([early, late]) == []
    late.active_barriers["game_starts"].arrival_time -= timedelta(seconds=11)
    late.active_barriers["game_starts"].released = True
    assert barrier.choose_who_to_release([early]) == []
    late.active_barriers["game_starts"].released = False
    assert set(barrier.choose_who_to_release([early, late])) == {early, late}
    assert late.sync_group_removal_reason("team") == "group_dissolved"


def _lobby_recipe():
    """The grouper and barrier of the "fill a team until the game starts" recipe."""
    grouper = SimpleGrouper(
        "team",
        initial_group_size=4,
        quorum=2,
        start_short_after=60,
        max_wait_time=120,
        join_existing_groups=True,
        use_admission_points=False,
        top_up_wait=60,
        below_quorum="continue_without_group",
    )
    game_starts = GroupBarrier(
        id_="game_starts",
        group_type="team",
        stop_top_ups=True,
        late_after=120,
        late_action="leave_group",
    )
    return grouper, game_starts


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_latecomers_fill_a_team_until_it_passes_game_starts(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper, game_starts = _lobby_recipe()
    assert game_starts.max_wait_time is None
    first, second, latecomer, too_late = [new_participant(exp) for _ in range(4)]
    for p in (first, second, latecomer, too_late):
        p.status = "working"
    group = grouper._make_group([first, second], initial_group_size=4)
    db_session.commit()

    grouper._join_existing_groups(latecomer)
    assert latecomer.in_sync_group("team")
    assert game_starts.choose_who_to_release([first, second]) == []
    released = game_starts.choose_who_to_release([first, second, latecomer])
    assert set(released) == {first, second, latecomer}
    assert not group.accepts_top_ups
    grouper._join_existing_groups(too_late)
    assert not too_late.in_sync_group("team")

    starters = [new_participant(exp) for _ in range(2)]
    for p in starters:
        p.status = "working"
    at_quorum = grouper._make_group(starters, initial_group_size=4)
    assert set(game_starts.choose_who_to_release(starters)) == set(starters)
    assert not at_quorum.accepts_top_ups

    *on_time, slow = [new_participant(exp) for _ in range(3)]
    for p in (*on_time, slow):
        p.status = "working"
    grouper._make_group(on_time, initial_group_size=4)
    grouper._join_existing_groups(slow)
    for link in slow.sync_group_links:
        link.arrival_time -= timedelta(seconds=121)
        link.admitted_at -= timedelta(seconds=121)
    game_starts.check_waiting_participants(on_time)
    assert slow.sync_group_removal_reason("team") == "late"
    assert set(game_starts.choose_who_to_release(on_time)) == set(on_time)

    lone, slow = [new_participant(exp) for _ in range(2)]
    for p in (lone, slow):
        p.status = "working"
    below_quorum = grouper._make_group([lone, slow], initial_group_size=4)
    for link in slow.sync_group_links:
        link.arrival_time -= timedelta(seconds=121)
        link.admitted_at -= timedelta(seconds=121)
    game_starts.check_waiting_participants([lone])
    assert slow.sync_group_removal_reason("team") == "late"
    assert game_starts.choose_who_to_release([lone]) == []
    assert lone.in_sync_group("team") and below_quorum.accepts_top_ups


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_member_who_left_or_whose_group_ended_keeps_it_as_latest(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "team",
        initial_group_size=2,
        max_group_size=3,
        quorum=2,
        join_existing_groups=True,
        use_admission_points=False,
    )
    founder, other, newcomer, outsider = _working_participants(exp, 4)
    group = grouper._make_group([founder, other], initial_group_size=2)
    db_session.commit()
    grouper._join_existing_groups(newcomer)
    assert group.active_participants == [founder, other, newcomer]

    group.remove_participant(newcomer, reason="late")
    assert "team" not in newcomer.active_sync_groups
    assert newcomer.latest_sync_group("team") == group
    group.remove_participant(founder, reason="finished")
    group.close()
    assert founder.latest_sync_group("team") == group
    assert founder.sync_group_link("team").removal_reason == "finished"
    assert outsider.latest_sync_group("team") is None


_ADMITTED_AT_RELEASE = []


def _record_admitted(admitted):
    _ADMITTED_AT_RELEASE.append([p.id for p in admitted])


def _society(exp, db_session, *, target_group_size=2, n_newcomers=1):
    """Return a society of two founders that admits newcomers at admission points, and its newcomers."""
    grouper = SimpleGrouper(
        "society",
        initial_group_size=2,
        max_group_size=4,
        quorum=2,
        target_group_size=target_group_size,
        join_existing_groups=True,
        use_admission_points=True,
        top_up_wait=30,
        below_quorum="continue_without_group",
    )
    founders = _working_participants(exp, 2)
    group = grouper._make_group(founders, initial_group_size=2)
    db_session.commit()
    newcomers = _working_participants(exp, n_newcomers)
    for newcomer in newcomers:
        grouper._join_existing_groups(newcomer)
    db_session.commit()
    return group, founders, newcomers


@pytest.mark.parametrize(
    "kwargs, error",
    [
        (dict(join_existing_groups=True), FutureWarning),
        (dict(use_admission_points=False), ValueError),
        (
            dict(join_existing_groups=True, use_admission_points=True),
            ValueError,
        ),
        (
            dict(
                join_existing_groups=True,
                use_admission_points=True,
                target_group_size=5,
            ),
            ValueError,
        ),
        (dict(max_groups=0), ValueError),
    ],
)
def test_simple_grouper_checks_its_admission_options(kwargs, error):
    options = dict(initial_group_size=2, max_group_size=4, quorum=2) | kwargs
    if not options.get("join_existing_groups"):
        options["max_group_size"] = "initial_group_size"
    if error is FutureWarning:
        with pytest.warns(FutureWarning, match="use_admission_points"):
            assert not SimpleGrouper("team", **options).use_admission_points
    else:
        with pytest.raises(error):
            SimpleGrouper("team", **options)
    with pytest.raises(ValueError, match="newcomer_max_wait"):
        GroupBarrier("start", group_type="team", admission_point=True)
    with pytest.raises(TypeError, match="PageMaker"):
        GroupBarrier(
            "start",
            group_type="team",
            admission_point=True,
            newcomer_max_wait=60,
            newcomer_page=lambda participant: None,
        )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_pending_member_is_admitted_only_at_an_admission_point(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    group, founders, (newcomer,) = _society(exp, db_session)
    assert group.pending_participants == [newcomer]
    assert group.active_participants == founders
    assert newcomer.sync_group_link("society").admitted_at is None
    assert newcomer.id not in group_seats(group)

    ordinary = GroupBarrier("round_ends", group_type="society")
    assert not ordinary._waits_here(newcomer)
    for founder in founders:
        _arrive_at_group_barrier(exp, ordinary, founder)
    _commit_barrier_arrivals()
    assert all(ordinary.can_participant_exit(p) for p in founders)
    assert group.pending_participants == [newcomer]

    _ADMITTED_AT_RELEASE.clear()
    start = GroupBarrier(
        "generation_start",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=60,
        on_release=_record_admitted,
    )
    for participant in [*founders, newcomer]:
        _arrive_at_group_barrier(exp, start, participant)
    _commit_barrier_arrivals()
    assert _ADMITTED_AT_RELEASE == [[newcomer.id]]
    assert group.active_participants == [*founders, newcomer]
    assert group.pending_participants == []
    assert group_seats(group)[newcomer.id] == 2
    assert start._just_admitted(newcomer) and not start._just_admitted(founders[0])
    assert [
        p.sync_group_link("society").admission_points_passed
        for p in [*founders, newcomer]
    ] == [1, 1, 1]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_release_does_not_admit_a_pending_member_past_newcomer_max_wait(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    group, founders, (newcomer,) = _society(exp, db_session)
    newcomer.sync_group_link("society").arrival_time -= timedelta(seconds=61)
    _ADMITTED_AT_RELEASE.clear()
    start = GroupBarrier(
        "generation_start",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=60,
        on_release=_record_admitted,
    )
    for participant in [*founders, newcomer]:
        _arrive_at_group_barrier(exp, start, participant)
    _commit_barrier_arrivals()
    assert _ADMITTED_AT_RELEASE == [[]]
    assert group.active_participants == founders
    assert newcomer.id not in [p.id for p in group.active_participants]


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_pending_member_at_an_admission_point_sees_arrivals(
    in_experiment_directory, db_session, monkeypatch
):
    exp = get_experiment()
    group, founders, (newcomer,) = _society(exp, db_session)
    publications = _hold_wake_publications(monkeypatch)
    start = GroupBarrier(
        "generation_start",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=60,
        waiting_message="Waiting for the rest of your group",
    )
    _arrive_at_group_barrier(exp, start, newcomer)
    db_session.commit()
    before = len(_arrival_hold_messages(publications, newcomer.id))
    _arrive_at_group_barrier(exp, start, founders[0])
    db_session.commit()
    assert len(_arrival_hold_messages(publications, newcomer.id)) == before + 1


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_pending_member_gets_no_notice_for_a_barrier_they_pass_through(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    group, founders, (newcomer,) = _society(exp, db_session)
    answered = GroupBarrier("answered", group_type="society")
    _arrive_at_group_barrier(exp, answered, founders[0])
    db_session.commit()
    assert pending_arrival_notice_for(founders[1]) is not None
    assert pending_arrival_notice_for(newcomer) is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_newcomer_joins_the_group_with_the_most_free_seats(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    with_pending, _, _ = _society(exp, db_session)
    without_pending, _, (newcomer,) = _society(exp, db_session)
    assert newcomer.active_sync_groups["society"] == without_pending
    assert with_pending.id < without_pending.id


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_pending_member_alone_at_an_admission_point_makes_nobody_late(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    group, founders, (newcomer,) = _society(exp, db_session)
    start = GroupBarrier(
        "round_starts",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=600,
        late_after=30,
        late_action="leave_group",
    )
    _set_group_clocks_in_the_past(group, 120)
    _arrive_at_group_barrier(exp, start, newcomer)
    _commit_barrier_arrivals()
    check_barriers()
    assert group.active_participants == founders
    assert start._participant_is_waiting(newcomer)


@pytest.mark.parametrize("how", ["newcomer_max_wait", "stop_top_ups", "closed"])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_pending_member_is_turned_away_without_failing(
    in_experiment_directory, db_session, how
):
    exp = get_experiment()
    group, founders, (newcomer,) = _society(exp, db_session)
    start = GroupBarrier(
        "generation_start",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=60,
    )
    if how == "newcomer_max_wait":
        newcomer.sync_group_link("society").arrival_time -= timedelta(seconds=61)
        assert start._max_wait_time_for(newcomer) == 0
        _arrive_at_group_barrier(exp, start, newcomer)
        start.handle_max_wait_timeout(newcomer)
    elif how == "stop_top_ups":
        group.stop_top_ups()
    else:
        group.close()
    db_session.commit()
    assert newcomer.sync_group_removal_reason("society") == "not_admitted"
    assert not newcomer.failed
    assert "couldn't add you to a group" in newcomer.group_removal_notice["text"]
    assert group.pending_participants == []


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_an_admission_point_waits_for_the_target_group_size_up_to_top_up_wait(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    group, founders, _ = _society(exp, db_session, target_group_size=3, n_newcomers=0)
    start = GroupBarrier(
        "generation_start",
        group_type="society",
        admission_point=True,
        newcomer_max_wait=60,
    )
    for founder in founders:
        _arrive_at_group_barrier(exp, start, founder)
    _commit_barrier_arrivals()
    assert not any(start.can_participant_exit(p) for p in founders)
    for founder in founders:
        founder.active_barriers[start.id].arrival_time -= timedelta(seconds=31)
    assert set(start.choose_who_to_release(founders)) == set(founders)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_max_groups_caps_the_groups_a_grouper_forms(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper = SimpleGrouper("team", initial_group_size=2, quorum=2, max_groups=1)
    waiting = _working_participants(exp, 4)
    assert len(grouper.choose_who_to_release(waiting)) == 2
    db_session.flush()
    assert grouper.choose_who_to_release(waiting[2:]) == []


@pytest.mark.parametrize("stop_top_ups", [False, True])
@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_counts_a_newcomer_joining_in_another_request(
    in_experiment_directory, db_session, stop_top_ups
):
    """A barrier check on a group that accepts top-ups doesn't release it during a join in progress, and later counts the newcomer."""
    exp = get_experiment()
    grouper = SimpleGrouper(
        "team",
        initial_group_size=4,
        quorum=2,
        join_existing_groups=True,
        use_admission_points=False,
        below_quorum="fail",
    )
    game_starts = GroupBarrier(
        id_="game_starts", group_type="team", stop_top_ups=stop_top_ups
    )
    *starters, newcomer, peeked = _working_participants(exp, 4)
    group = grouper._make_group(starters, initial_group_size=4)
    db_session.commit()
    assert len(group.active_participants) == 2

    def still_waiting():
        db_session.expire_all()
        return [p for p in starters if not game_starts.can_participant_exit(p)]

    poller_pid, deferred, errors = [], [], []

    def poll_barriers():
        try:
            poller_pid.append(
                db.session.execute(text("SELECT pg_backend_pid()")).scalar()
            )
            deferred.append(_process_barrier_instance(instance_id))
        except Exception as err:  # pragma: no cover - surfaced below
            errors.append(err)
        finally:
            db.session.remove()

    for participant in starters:
        _arrive_at_group_barrier(exp, game_starts, participant)
    db_session.commit()
    _take_pending_barrier_checks()
    instance_id = starters[0].active_barriers[game_starts.id].barrier_instance_id
    with Session(bind=db.engine) as joiner:
        joiner.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR NO KEY UPDATE"),
            {"id": group.id},
        )
        joiner.add(
            ParticipantLinkSyncGroup(
                participant_id=newcomer.id,
                sync_group_id=group.id,
                active=True,
                arrival_time=timenow(),
                admitted_at=timenow(),
            )
        )
        joiner.flush()
        poller = threading.Thread(target=poll_barriers)
        poller.start()
        # The check finds the group busy and defers. A check that counted
        # the members without the lock would instead block on its UPDATE of
        # the group; the join then commits, and that check releases the
        # starters without the newcomer.
        deadline = time.monotonic() + 10
        while poller.is_alive() and time.monotonic() < deadline:
            blocked = (
                poller_pid
                and joiner.execute(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                    {"pid": poller_pid[0]},
                ).scalar()
            )
            if blocked:
                break
            time.sleep(0.05)
        joiner.commit()
    poller.join(30)
    assert errors == []
    assert deferred == [True]
    assert still_waiting() == starters

    check_barriers()
    assert still_waiting() == starters
    assert newcomer.in_sync_group("team") and group.accepts_top_ups

    # A peek, which takes no lock, also counts a newcomer who joined meanwhile.
    _arrive_at_group_barrier(exp, game_starts, newcomer)
    with Session(bind=db.engine) as other:
        other.add(
            ParticipantLinkSyncGroup(
                participant_id=peeked.id,
                sync_group_id=group.id,
                active=True,
                arrival_time=timenow(),
                admitted_at=timenow(),
            )
        )
        other.commit()
    assert not game_starts.would_release([*starters, newcomer])
    _arrive_at_group_barrier(exp, game_starts, peeked)
    _commit_barrier_arrivals()
    assert still_waiting() == []
    assert group.accepts_top_ups != stop_top_ups


def _top_up_team_waiting_at(exp, db_session, barrier, n_starters=2):
    """Return a team of ``n_starters`` that accepts top-ups, all waiting at ``barrier``, and the pending checks."""
    grouper = SimpleGrouper(
        "team",
        initial_group_size=4,
        quorum=2,
        join_existing_groups=True,
        use_admission_points=False,
        below_quorum="fail",
    )
    starters = _working_participants(exp, n_starters)
    group = grouper._make_group(starters, initial_group_size=4)
    for participant in starters:
        _arrive_at_group_barrier(exp, barrier, participant)
    db_session.commit()
    return starters, group, _take_pending_barrier_checks()


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_check_on_a_busy_top_up_group_is_deferred_and_retried(
    in_experiment_directory, db_session
):
    """The last arrival and the poller report a check deferred while the group is busy, so they retry it."""
    exp = get_experiment()
    barrier = GroupBarrier(id_="game_starts", group_type="team")
    starters, group, checks = _top_up_team_waiting_at(exp, db_session, barrier)
    with db.engine.connect() as joiner, joiner.begin():
        joiner.execute(
            text("SELECT id FROM sync_group WHERE id = :id FOR NO KEY UPDATE"),
            {"id": group.id},
        )
        assert _run_pending_barrier_checks(checks) is False
        assert _process_barrier_instance(checks[0])
    assert _run_pending_barrier_checks(checks)
    db_session.expire_all()
    assert all(barrier.can_participant_exit(p) for p in starters)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_check_counts_a_newcomer_who_joined_after_it_loaded_the_group(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(id_="game_starts", group_type="team")
    starters, group, checks = _top_up_team_waiting_at(exp, db_session, barrier)
    (newcomer,) = _working_participants(exp, 1)
    assert len(group.active_participants) == 2
    with Session(bind=db.engine) as other:
        other.add(
            ParticipantLinkSyncGroup(
                participant_id=newcomer.id,
                sync_group_id=group.id,
                active=True,
                arrival_time=timenow(),
                admitted_at=timenow(),
            )
        )
        other.commit()
    barrier._check_instance(checks[0])
    db_session.commit()
    assert not any(barrier.can_participant_exit(p) for p in starters)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_stop_top_ups_barrier_waits_for_a_team_below_quorum_and_the_method_dissolves_it(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper, game_starts = _lobby_recipe()

    def team_that_lost_a_member():
        quitter, waiter = [new_participant(exp) for _ in range(2)]
        for p in (quitter, waiter):
            p.status = "working"
        group = grouper._make_group([quitter, waiter], initial_group_size=4)
        db_session.commit()
        quitter.fail("quit")
        return group, waiter

    group, waiter = team_that_lost_a_member()
    _arrive_at_group_barrier(exp, game_starts, waiter)
    assert game_starts.choose_who_to_release([waiter]) == []
    assert group.accepts_top_ups and waiter.in_sync_group("team")
    group.below_quorum_since -= timedelta(seconds=61)
    waiter.active_barriers["game_starts"].arrival_time -= timedelta(seconds=61)
    assert game_starts.choose_who_to_release([waiter]) == [waiter]
    assert waiter.sync_group_removal_reason("team") == "group_dissolved"

    group, waiter = team_that_lost_a_member()
    group.stop_top_ups()
    assert waiter.sync_group_removal_reason("team") == "group_dissolved"
    assert not waiter.failed


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_a_closed_join_criterion_doesnt_stop_top_ups(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    grouper = SimpleGrouper(
        "team",
        initial_group_size=2,
        join_existing_groups=True,
        use_admission_points=False,
        join_criterion=lambda group, participant: False,
        below_quorum="continue_without_group",
    )
    barrier = GroupBarrier(id_="game_starts", group_type="team")
    quitter, waiter, newcomer = [new_participant(exp) for _ in range(3)]
    for p in (quitter, waiter, newcomer):
        p.status = "working"
    group = grouper._make_group([quitter, waiter], initial_group_size=2)
    db_session.commit()

    quitter.fail("quit")
    grouper._join_existing_groups(newcomer)
    assert not newcomer.in_sync_group("team")
    assert group.accepts_top_ups
    assert barrier.choose_who_to_release([waiter]) == []
    assert waiter.in_sync_group("team")

    group.stop_top_ups()
    assert not waiter.failed
    assert waiter.sync_group_removal_reason("team") == "group_dissolved"


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_grouper_lets_an_ungrouped_participant_carry_on(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"
    with pytest.raises(ValueError, match="continue_without_group"):
        SimpleGrouper("pair", initial_group_size=2, max_wait_action="leave_group")
    with pytest.raises(ValueError, match="continue_without_group"):
        SimpleGrouper("pair", initial_group_size=2, below_quorum="leave_group")
    grouper = SimpleGrouper(
        "pair", initial_group_size=2, max_wait_action="continue_without_group"
    )
    grouper.receive_participant(participant)
    db_session.commit()

    grouper.handle_max_wait_timeout(participant)
    db_session.commit()

    assert not participant.failed
    assert not participant.in_sync_group("pair")
    assert participant.sync_group_removal_reason("pair") == "no_group_formed"
    InfoPage("Next").consume(exp, participant)
    assert _removed_from_group_notice(participant) == (
        "We couldn't find a partner for you in time. Please continue."
    )
    assert _removed_from_group(participant, "pair")
    assert not _removed_from_group(new_participant(exp), "pair")


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_max_wait_leave_group_releases_barrier_link(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        quorum=1,
        n_active_participants=1,
        accepts_top_ups=False,
        below_quorum="fail",
    )
    db_session.add(group)
    group.add_participant(participant)

    barrier = GroupBarrier(
        id_="max_wait_leave_group",
        group_type="main",
        max_wait_action="leave_group",
    )
    barrier.receive_participant(participant)
    db_session.commit()

    assert "main" in participant.active_sync_groups
    assert "max_wait_leave_group" in participant.active_barriers

    barrier.handle_max_wait_timeout(participant)
    db_session.commit()

    assert participant.active_sync_groups.get("main") is None
    assert "max_wait_leave_group" not in participant.active_barriers
    assert not participant.failed
    # The page they move on to says why they are on their own.
    assert _removed_from_group_notice(participant) is None
    InfoPage("Next").consume(exp, participant)
    assert _removed_from_group_notice(participant) == (
        "Your partner didn't arrive in time. Please continue."
    )
    InfoPage("After").consume(exp, participant)
    assert _removed_from_group_notice(participant) is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_on_release_is_told_who_left_since_the_last_barrier(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participants, group = _sync_group_of(exp, db_session, 4)
    group.quorum = 2
    late, quitter, *stayers = participants
    group.remove_participant(late, reason="late")
    quitter.fail("returned")
    db_session.commit()
    _left_at_release.clear()

    for round_ in (1, 2):
        barrier = GroupBarrier(
            id_=f"round_{round_}", group_type="main", on_release=_record_who_left
        )
        for stayer in stayers:
            _arrive_at_group_barrier(exp, barrier, stayer)
        _commit_barrier_arrivals()

    assert _left_at_release == [
        [(late.id, "late"), (quitter.id, "left_experiment")],
        [],
    ]

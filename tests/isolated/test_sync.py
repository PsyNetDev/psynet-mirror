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
from dallinger.models import timenow
from flask import Flask
from sqlalchemy import Column, String, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.inspection import inspect as sa_inspect

from psynet.barrier_spec import (
    BarrierSpecError,
    barrier_from_spec_json,
    barrier_spec_json,
)
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
from psynet.process import AsyncProcess, LocalAsyncProcess, WorkerAsyncProcess
from psynet.pytest_psynet import path_to_test_experiment
from psynet.serialize import SerializedCallable
from psynet.sqlalchemy_profiling import assert_query_count
from psynet.sync import (
    _BARRIER_FROM_SPEC_CACHE_KEY,
    Barrier,
    BarrierDefinition,
    BarrierInstance,
    GroupBarrier,
    SimpleGrouper,
    SimpleSyncGroup,
    _advance_released_hold_waiters_after_commit,
    _check_and_skip_held_instance,
    _check_claimed_barrier_instance,
    _check_held_instance,
    _claim_barrier_instance,
    _has_active_sync_group,
    _hold_barrier_instance_claim,
    _hold_instance_id_for_page,
    _pending_checks_should_wait_for_claim,
    _process_barrier_instance,
    _queue_barrier_check,
    _queue_released_hold_waiters,
    _run_pending_barrier_checks,
    _take_pending_barrier_checks,
    _take_released_hold_waiter_ids,
    _visit_check_would_release,
    arrival_notice_payload,
    check_barriers,
    check_sync_groups,
    pending_arrival_notice_for,
)
from psynet.timeline import Page, Timeline
from psynet.timeline_hold import (
    TimelineHoldRecord,
    _defer_timeline_hold_wakes,
    _enqueue_timeline_hold_wake,
    _queue_arrival_update,
    _timeline_hold_channel,
    _TimelineHoldPage,
    default_group_barrier_arrival_message,
)
from psynet.utils import get_config

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


def async_process_noop():
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


def test_max_wait_action_kick_requires_group_barrier():
    with pytest.raises(TypeError, match="max_wait_action"):
        Barrier(id_="plain_barrier", max_wait_action="kick")

    with pytest.raises(TypeError, match="max_wait_action"):
        RecordingBarrier(id_="recording_barrier", max_wait_action="kick")

    barrier = GroupBarrier(
        id_="group_barrier",
        group_type="main",
        max_wait_action="kick",
    )
    assert barrier.max_wait_action == "kick"


def test_group_barrier_preserves_positional_timeout_arguments():
    barrier = GroupBarrier(
        "group_barrier",
        "main",
        None,
        3,
        20,
        "fail",
        None,
        False,
        5,
        "kick",
    )

    assert barrier.timeout_between_barriers_time == 5
    assert barrier.timeout_between_barriers_action == "kick"
    assert barrier.expected_wait == 1.5


def test_default_barrier_uses_timeline_hold():
    barrier = ReleaseAllBarrier(id_="hold")

    assert barrier.waiting_logic.is_timeline_hold
    assert barrier.waiting_logic.barrier_id == barrier.id
    assert barrier.waiting_logic.time_estimate == 1.5
    assert barrier.waiting_logic.content is None
    assert barrier.waiting_logic.message_kind == "barrier"
    assert not isinstance(barrier.waiting_logic, WaitPage)


def test_barrier_accepts_custom_hold_content():
    barrier = GroupBarrier(
        id_="wait_for_partner",
        group_type="pair",
        content="Waiting for your partner",
    )
    hold = barrier.waiting_logic

    assert hold.content == "Waiting for your partner"
    assert hold.message_kind is None
    assert hold.translated_content() == "Waiting for your partner"


def test_explicit_barrier_waiting_logic_is_preserved():
    waiting_logic = WaitPage(wait_time=1)
    barrier = ReleaseAllBarrier(id_="page_wait", waiting_logic=waiting_logic)

    assert barrier.waiting_logic is waiting_logic


def test_expected_wait_rejects_explicit_waiting_logic():
    with pytest.raises(ValueError, match="expected_wait"):
        ReleaseAllBarrier(
            id_="page_wait",
            waiting_logic=WaitPage(wait_time=1),
            expected_wait=2,
        )


def test_content_rejects_explicit_waiting_logic():
    with pytest.raises(ValueError, match="content"):
        ReleaseAllBarrier(
            id_="page_wait",
            waiting_logic=WaitPage(wait_time=1),
            content="Waiting for your partner",
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
    instance_id = participant.active_barriers[barrier.id].barrier_instance_id

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
        max_wait_action="kick",
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
    grouper = SimpleGrouper(group_type="main", initial_group_size=3)
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
        content="Waiting for your partner",
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
    grouper = SimpleGrouper(group_type="main", initial_group_size=3, batch_size=2)
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
        min_group_size=1,
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
        min_group_size=1,
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
        min_group_size=1,
        n_active_participants=1,
        accepts_top_ups=True,
    )
    secondary_group = SimpleSyncGroup(
        group_type="secondary",
        initial_group_size=1,
        max_group_size=2,
        min_group_size=1,
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
        min_group_size=1,
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
    assert group.active


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
        min_group_size=3,
        n_active_participants=3,
        accepts_top_ups=False,
        fail_participants_below_min_size=fail_below_min_size,
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
        min_group_size=1,
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
        min_group_size=1,
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

        def mutating(self, waiting):
            instance = BarrierInstance.query.get(instance_id)
            instance.active = False
            waiting[0].progress = original_progress + 1
            db.session.flush()
            return True

        monkeypatch.setattr(GroupBarrier, "would_release", mutating)
        assert _visit_check_would_release(instance_id) is True
        instance = BarrierInstance.query.get(instance_id)
        first = Participant.query.get(first.id)
        assert instance.active is True
        assert first.progress == original_progress
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
        min_group_size=n,
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
    grouper = SimpleGrouper(group_type="waitlist", initial_group_size=3)
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

    with pytest.raises(RuntimeError, match="has no active sync group"):
        BarrierInstance.for_arrival(barrier, participant)


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
    grouper = SimpleGrouper(group_type="reuse_ungrouped", initial_group_size=3)
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
    grouper = SimpleGrouper(group_type="split_ungrouped", initial_group_size=3)
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
def test_leftover_ungrouped_waiter_joins_the_active_pool_and_can_proceed(
    in_experiment_directory, db_session
):
    """A leftover waiter must join the live pool in time to be grouped."""
    exp = get_experiment()
    first, second, third = [new_participant(exp) for _ in range(3)]
    for participant in (first, second, third):
        participant.status = "working"
    db.session.commit()
    grouper = SimpleGrouper(group_type="migrate_join", initial_group_size=3)
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


def _arrival_hold_messages(publications, participant_id):
    """Return arrival-update overlay HTML published to one participant."""
    channel = _timeline_hold_channel(participant_id)
    return [
        target.get("hold_message")
        for published_channel, payload in publications
        if published_channel == channel
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
    """Return how many advisory locks the database currently holds."""
    with db.engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
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
            content="Waiting for your partner",
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
            content="Waiting for your partner",
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
    publications = []
    monkeypatch.setattr(
        db.redis_conn,
        "publish",
        lambda channel_name, data: publications.append(
            (channel_name, json.loads(data))
        ),
    )

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
    assert (
        default_group_barrier_arrival_message(
            kind="hold", waiting_count=1, group_size=2
        )
        is None
    )
    assert (
        default_group_barrier_arrival_message(
            kind="hold", waiting_count=1, group_size=3
        )
        == "2 of 3 not ready yet"
    )
    assert (
        default_group_barrier_arrival_message(
            kind="hold", waiting_count=2, group_size=3
        )
        == "1 of 3 not ready yet"
    )
    assert (
        default_group_barrier_arrival_message(
            kind="hold", waiting_count=3, group_size=3
        )
        is None
    )
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


def test_group_barrier_notify_arrivals_defaults_on():
    barrier = GroupBarrier(id_="default_notice", group_type="main")
    assert barrier.notify_arrivals is True

    quiet = GroupBarrier(id_="quiet_notice", group_type="main", notify_arrivals=False)
    assert quiet.notify_arrivals is False


def test_on_arrival_message_enables_notify_arrivals():
    barrier = GroupBarrier(
        id_="custom_notice",
        group_type="main",
        on_arrival_message=_custom_arrival_message,
    )
    assert barrier.notify_arrivals is True
    assert (
        barrier._call_arrival_message(
            kind="notice", waiting_count=1, group_size=2, recipient=None, group=None
        )
        == "custom"
    )


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
        content="Waiting for your partner",
    )
    publications = []
    monkeypatch.setattr(
        db.redis_conn,
        "publish",
        lambda channel_name, data: publications.append(
            (channel_name, json.loads(data))
        ),
    )

    _arrive_at_group_barrier(exp, barrier, first)
    db_session.commit()

    notices = [
        target.get("notice")
        for _, payload in publications
        for target in payload["targets"]
    ]
    hold_messages = [
        target.get("hold_message")
        for _, payload in publications
        for target in payload["targets"]
    ]
    assert "Your partner is ready." in notices
    assert all(
        not message or "psynet-timeline-hold-progress" not in message
        for message in hold_messages
    )
    assert pending_arrival_notice_for(last) == "Your partner is ready."
    assert arrival_notice_payload(last.id) == {"notice": "Your partner is ready."}
    assert arrival_notice_payload(None) == {"notice": None}
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
        content="Waiting for your partner",
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
    in_experiment_directory, db_session
):
    exp = get_experiment()
    first, second, third = _sync_group_of(exp, db_session, 3)[0]
    barrier = GroupBarrier(
        id_="group_hold_remaining",
        group_type="main",
        content="Waiting for the rest of your group",
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
    assert pending_arrival_notice_for(third) == "2/3 of your group are ready."


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
        min_group_size=1,
        n_active_participants=99,
        accepts_top_ups=False,
    )
    free_group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        min_group_size=1,
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

    def publish(channel_name, data):
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
        publications.append((json.loads(data), channel_name))

    monkeypatch.setattr(db.redis_conn, "publish", publish)

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
            _timeline_hold_channel(participant_id),
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
    publications = []
    monkeypatch.setattr(
        db.redis_conn,
        "publish",
        lambda *args, **kwargs: publications.append((args, kwargs)),
    )

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
    assert publications[0][0] == _timeline_hold_channel(participant.id)
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

    publications = []
    monkeypatch.setattr(
        db.redis_conn,
        "publish",
        lambda channel_name, data: publications.append(json.loads(data)),
    )

    held_barrier = WaitForTwoBarrier(id_="shared")
    held_barrier.receive_participant(held_participant)
    held_barrier.waiting_logic.consume(exp, held_participant)
    page_barrier = WaitForTwoBarrier(id_="shared", waiting_logic=WaitPage(wait_time=1))
    page_barrier.receive_participant(page_participant)
    held_wake_token = held_participant.timeline_holds[0].wake_token
    _commit_barrier_arrivals()

    release_targets = [
        target
        for payload in publications
        for target in payload["targets"]
        if target.get("reason") == "barrier_released"
    ]
    assert [target["wake_token"] for target in release_targets] == [held_wake_token]
    assert all("page_uuid" not in target for target in release_targets)

    check_barriers()
    assert [
        target["wake_token"]
        for payload in publications
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
def test_async_process_events_wake_timeline_holds(
    in_experiment_directory, db_session, monkeypatch
):
    wakes = []
    monkeypatch.setattr(AsyncProcess, "add_to_launch_queue", lambda self: None)
    monkeypatch.setattr(
        "psynet.timeline_hold._queue_timeline_hold_wake",
        lambda participant_id, reason=None, **kwargs: wakes.append(reason),
    )
    monkeypatch.setattr(
        "psynet.process.Job.fetch",
        lambda *args, **kwargs: SimpleNamespace(cancel=lambda: None),
    )

    participant = new_participant(get_experiment())
    db_session.flush()
    finished = LocalAsyncProcess(async_process_noop, participant=participant)
    timed_out = WorkerAsyncProcess(
        async_process_noop, participant=participant, timeout=30
    )
    cancelled = WorkerAsyncProcess(async_process_noop, participant=participant)
    timed_out.timeout_scheduled_for = datetime.now() - timedelta(seconds=1)
    db_session.flush()
    finished_id = finished.id
    cancelled_id = cancelled.id
    db_session.commit()

    LocalAsyncProcess.call_function(finished_id)
    WorkerAsyncProcess.check_timeouts()
    WorkerAsyncProcess.query.get(cancelled_id).cancel()

    assert wakes == [
        "async_process_finished",
        "async_process_timed_out",
        "async_process_cancelled",
    ]


def test_group_barrier_timeout_between_barriers_rejects_bad_action():
    with pytest.raises(ValueError, match="timeout_between_barriers_action"):
        GroupBarrier(
            id_="timeout_between_barriers_bad_action",
            group_type="group",
            timeout_between_barriers_time=5,
            timeout_between_barriers_action="remove",
        )


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_timeout_between_barriers_kick_missing_participants(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="timeout_between_barriers_kick",
        group_type="main",
        timeout_between_barriers_time=5,
        timeout_between_barriers_action="kick",
    )

    # Create 3 participants in the same sync group, but only 2 "reach" this barrier.
    participants = [new_participant(exp) for _ in range(3)]
    for p in participants:
        p.status = "working"
    waiting_participants = participants[:2]
    missing_participant = participants[2]

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        min_group_size=2,
        n_active_participants=3,
        accepts_top_ups=False,
        fail_participants_below_min_size=True,
    )
    group.last_barrier_pass_time = timenow() - timedelta(seconds=10)
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    db_session.commit()

    barrier.check_waiting_participants(waiting_participants)
    released = barrier.choose_who_to_release(waiting_participants)

    assert missing_participant not in group.active_participants
    assert missing_participant not in released
    assert set(released) == set(waiting_participants)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_timeout_between_barriers_kick_releases_waiters_after_dissolution(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="timeout_between_barriers_kick_below_min",
        group_type="main",
        timeout_between_barriers_time=5,
        timeout_between_barriers_action="kick",
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
        min_group_size=3,
        n_active_participants=3,
        accepts_top_ups=False,
        fail_participants_below_min_size=False,
    )
    group.last_barrier_pass_time = timenow() - timedelta(seconds=10)
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    db_session.commit()

    barrier.check_waiting_participants(waiting_participants)
    released = barrier.choose_who_to_release(waiting_participants)

    assert group.active_participants == []
    assert missing_participant not in released
    assert set(released) == set(waiting_participants)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_timeout_between_barriers_fail_missing_participants(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="timeout_between_barriers_fail",
        group_type="main",
        timeout_between_barriers_time=5,
        timeout_between_barriers_action="fail",
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
        min_group_size=2,
        n_active_participants=3,
        accepts_top_ups=False,
        fail_participants_below_min_size=True,
    )
    group.last_barrier_pass_time = timenow() - timedelta(seconds=10)
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    db_session.commit()

    barrier.check_waiting_participants(waiting_participants)
    released = barrier.choose_who_to_release(waiting_participants)

    assert missing_participant.failed is True
    assert missing_participant not in group.active_participants
    assert set(released) == set(waiting_participants)


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
@pytest.mark.parametrize("fail_below_min_size", [True, False])
def test_group_barrier_fail_participants_below_min_size(
    in_experiment_directory, db_session, fail_below_min_size
):
    exp = get_experiment()
    barrier = GroupBarrier(
        id_="fail_participants_below_min_size",
        group_type="main",
    )

    participants = [new_participant(exp) for _ in range(2)]
    for p in participants:
        p.status = "working"

    # Configure group so it's below min size and doesn't accept top-ups.
    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=3,
        max_group_size=3,
        min_group_size=3,
        n_active_participants=2,
        accepts_top_ups=False,
        fail_participants_below_min_size=fail_below_min_size,
    )
    group.last_barrier_pass_time = timenow()
    db_session.add(group)
    for p in participants:
        group.add_participant(p)
    db_session.commit()

    released = barrier.choose_who_to_release(waiting_participants=participants)

    assert set(released) == set(participants)
    assert group.active_participants == []
    assert all(p.active_sync_groups.get("main") is None for p in participants)
    assert all(p.failed == fail_below_min_size for p in participants)


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
        min_group_size=3,
        n_active_participants=2,
        accepts_top_ups=False,
        fail_participants_below_min_size=True,
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
def test_group_barrier_participant_kick(in_experiment_directory, db_session):
    participant = Participant(
        experiment=get_experiment(),
        recruiter_id="hotair",
        worker_id=str(uuid.uuid4()),
        hit_id="XYZ",
        assignment_id=str(uuid.uuid4()),
        mode="debug",
    )
    participant.status = "working"
    db_session.add(participant)

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        min_group_size=1,
        n_active_participants=1,
        accepts_top_ups=False,
        fail_participants_below_min_size=True,
    )
    db_session.add(group)
    group.add_participant(participant)
    db_session.commit()

    assert "main" in participant.active_sync_groups
    GroupBarrier._kick_participant_after_max_wait(
        participant=participant, group_type="main"
    )
    db_session.commit()

    assert participant.active_sync_groups.get("main") is None


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_barrier_max_wait_kick_releases_barrier_link(
    in_experiment_directory, db_session
):
    exp = get_experiment()
    participant = new_participant(exp)
    participant.status = "working"

    group = SimpleSyncGroup(
        group_type="main",
        initial_group_size=1,
        max_group_size=1,
        min_group_size=1,
        n_active_participants=1,
        accepts_top_ups=False,
        fail_participants_below_min_size=True,
    )
    db_session.add(group)
    group.add_participant(participant)

    barrier = GroupBarrier(
        id_="max_wait_kick",
        group_type="main",
        max_wait_action="kick",
    )
    barrier.receive_participant(participant)
    db_session.commit()

    assert "main" in participant.active_sync_groups
    assert "max_wait_kick" in participant.active_barriers

    barrier.handle_max_wait_timeout(participant)
    db_session.commit()

    assert participant.active_sync_groups.get("main") is None
    assert "max_wait_kick" not in participant.active_barriers
    assert not participant.failed

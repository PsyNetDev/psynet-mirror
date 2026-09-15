import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from dallinger import db
from dallinger.models import timenow
from sqlalchemy import Column, String

from psynet.dashboard.sync_groups import (
    _fail_sync_group_participant,
    _get_grouper_progress,
    _index_waiting_barriers,
    _kick_sync_group_participant,
    _summarize_waiting_at_barriers,
)
from psynet.data import SQLBase
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment
from psynet.serialize import SerializedCallable
from psynet.sync import (
    Barrier,
    BarrierRecord,
    GroupBarrier,
    SimpleGrouper,
    SimpleSyncGroup,
    check_barriers,
)
from psynet.timeline import CodeBlock, GoTo


def get_random_id():
    return str(uuid.uuid4())


def new_participant(experiment):
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=get_random_id(),
        hit_id="XYZ",
        assignment_id=get_random_id(),
        mode="debug",
    )
    db.session.add(participant)
    return participant


processed_barriers = []


class ExplodingBarrier(Barrier):
    def check(self):
        raise RuntimeError("boom")


class RecordingBarrier(Barrier):
    def check(self):
        processed_barriers.append(self.id)


class RecordingTimeoutGroupBarrier(GroupBarrier):
    def handle_max_wait_timeout(self, participant):
        participant.timeout_callback_ran = True


class DummyModel(SQLBase):
    __tablename__ = "dummy_model"

    id = Column(String, primary_key=True)

    def on_release(
        self, group, participants, participant=None, barrier=None, experiment=None
    ):
        return None


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


def test_group_barrier_resolved_timeout_uses_overridden_handler():
    barrier = RecordingTimeoutGroupBarrier(
        id_="group_barrier",
        group_type="main",
        max_wait_action="kick",
    )
    elts = barrier.resolve()
    timeout_callbacks = [
        elt
        for elt, next_elt in zip(elts, elts[1:])
        if isinstance(elt, CodeBlock) and isinstance(next_elt, GoTo)
    ]
    participant = SimpleNamespace(timeout_callback_ran=False, module_state=None)

    assert len(timeout_callbacks) == 1
    timeout_callbacks[0].consume(experiment=None, participant=participant)
    assert participant.timeout_callback_ran


@pytest.mark.parametrize(
    "experiment_directory", [path_to_test_experiment("consents")], indirect=True
)
def test_group_allocator(in_experiment_directory, db_session):
    exp = get_experiment()
    grouper = SimpleGrouper(group_type="main", initial_group_size=3)
    participants = [new_participant(exp) for _ in range(6)]

    assert len(grouper.get_waiting_participants()) == 0

    grouper.receive_participant(participants[0])
    db.session.commit()

    assert len(grouper.get_waiting_participants()) == 1
    assert BarrierRecord.query.get("main_grouper") is not None
    assert "main_grouper" in participants[0].active_barriers
    assert "main_grouper" not in participants[1].active_barriers
    assert not grouper.can_participant_exit(participants[0])

    for participant in participants:
        assert participant.sync_group is None

    grouper.receive_participant(participants[1])
    db.session.commit()

    assert len(grouper.get_waiting_participants()) == 2
    assert not grouper.can_participant_exit(participants[0])

    for participant in participants:
        assert participant.sync_group is None

    grouper.receive_participant(participants[2])
    grouper.check()

    db.session.commit()

    assert grouper.can_participant_exit(participants[0])
    assert len(grouper.get_waiting_participants()) == 0

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
            "barrier_id": "main_grouper",
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
def test_barrier_registry_strips_waiting_logic(db_session):
    barrier = GroupBarrier(id_="strip_wait", group_type="group")
    barrier_record = BarrierRecord(
        id=barrier.id,
        barrier_class=barrier.__class__,
        barrier=barrier.for_registry(),
    )
    db_session.add(barrier_record)
    db_session.commit()

    loaded = BarrierRecord.query.get("strip_wait")
    assert loaded.barrier.waiting_logic is None


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
    assert barrier.get_waiting_participants() == []
    assert not participant.failed

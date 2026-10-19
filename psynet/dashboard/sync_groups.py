from collections import defaultdict

from dallinger.experiment_server.utils import error_response, success_response
from flask import render_template
from sqlalchemy.orm import joinedload

from psynet.participant import Participant
from psynet.sync import (
    Grouper,
    ParticipantLinkBarrier,
    ParticipantLinkSyncGroup,
    SimpleSyncGroup,
    SyncGroup,
)
from psynet.utils import get_logger

TEMPLATE_NAME = "dashboard_sync_groups.html"
MANUAL_FAILURE_REASON = "manual_failure"
MANUAL_KICK_REASON = "manual_kick"
logger = get_logger()


def _get_grouper_progress():
    """
    Return list of dicts describing each Grouper in the timeline.

    Used as static configuration for the "Grouper progress" table.
    """
    try:
        from psynet.experiment import get_experiment

        exp = get_experiment()
    except Exception:
        logger.warning(
            "Could not load experiment timeline for sync groups dashboard.",
            exc_info=True,
        )
        return []

    groupers = {}
    for elt in exp.timeline.all_elts:
        links = getattr(elt, "links", None) or {}
        barrier = links.get("barrier")
        if isinstance(barrier, Grouper) and barrier.id not in groupers:
            groupers[barrier.id] = {
                "barrier_id": barrier.id,
                "group_type": barrier.group_type,
                "batch_size": getattr(barrier, "batch_size", None),
                "initial_group_size": getattr(barrier, "initial_group_size", None),
            }

    return list(groupers.values())


def _get_waiting_by_participant_and_barrier():
    """Return list of (participant_id, barrier_id) for all participants currently waiting at a barrier."""
    return (
        ParticipantLinkBarrier.query.join(Participant)
        .filter(
            ~ParticipantLinkBarrier.released,
            ~Participant.failed,
            Participant.status == "working",
        )
        .with_entities(
            ParticipantLinkBarrier.participant_id,
            ParticipantLinkBarrier.barrier_id,
        )
        .all()
    )


def manual_fail_sync_group_participant(
    participant_id, sync_group_id, fail_reason=MANUAL_FAILURE_REASON
):
    try:
        participant = _fail_sync_group_participant(
            participant_id, sync_group_id, fail_reason
        )
    except ValueError as err:
        return error_response(str(err))

    return success_response(participant_id=participant.id)


def manual_kick_sync_group_participant(
    participant_id, sync_group_id, kick_reason=MANUAL_KICK_REASON
):
    try:
        participant = _kick_sync_group_participant(
            participant_id, sync_group_id, kick_reason
        )
    except ValueError as err:
        return error_response(str(err))

    return success_response(participant_id=participant.id)


def _fail_sync_group_participant(participant_id, sync_group_id, fail_reason):
    if fail_reason != MANUAL_FAILURE_REASON:
        raise ValueError(f"Invalid fail reason: {fail_reason}")

    participant, _ = _get_active_sync_group_participant_link(
        participant_id, sync_group_id
    )

    if participant.failed or participant.status != "working":
        raise ValueError("Only active working participants can be failed manually.")

    participant.fail(MANUAL_FAILURE_REASON)
    return participant


def _kick_sync_group_participant(participant_id, sync_group_id, kick_reason):
    if kick_reason != MANUAL_KICK_REASON:
        raise ValueError(f"Invalid kick reason: {kick_reason}")

    participant, active_group_link = _get_active_sync_group_participant_link(
        participant_id, sync_group_id
    )

    if participant.failed or participant.status != "working":
        raise ValueError("Only active working participants can be kicked manually.")

    active_group_link.sync_group.remove_participant(participant)
    return participant


def _get_active_sync_group_participant_link(participant_id, sync_group_id):
    participant = (
        Participant.query.with_for_update(of=Participant)
        .populate_existing()
        .get(participant_id)
    )
    if participant is None:
        raise ValueError(f"No participant found with ID {participant_id}.")

    active_group_link = (
        ParticipantLinkSyncGroup.query.join(SyncGroup)
        .filter(
            ParticipantLinkSyncGroup.participant_id == participant_id,
            ParticipantLinkSyncGroup.sync_group_id == sync_group_id,
            ParticipantLinkSyncGroup.active,
            SyncGroup.active,
        )
        .with_for_update(of=[ParticipantLinkSyncGroup, SyncGroup])
        .first()
    )
    if active_group_link is None:
        raise ValueError(
            "This participant is not currently active in the selected sync group."
        )

    return participant, active_group_link


def report_sync_groups():
    """Render the sync groups dashboard page with active and recent sync groups."""
    grouper_configs = _get_grouper_progress()

    groups = (
        SyncGroup.query.options(
            joinedload(SyncGroup.participant_links).joinedload(
                ParticipantLinkSyncGroup.participant
            ),
            joinedload(SyncGroup.leader),
        )
        .order_by(SyncGroup.id.desc())
        .limit(500)
        .all()
    )

    waiting_by_participant, waiting_by_barrier = _index_waiting_barriers(
        _get_waiting_by_participant_and_barrier()
    )

    group_rows = [_group_row(group, waiting_by_participant) for group in groups]
    has_simple_groups = any(r["min_group_size"] is not None for r in group_rows)

    return render_template(
        TEMPLATE_NAME,
        title="Sync groups",
        groups=group_rows,
        has_simple_groups=has_simple_groups,
        grouper_progress=_grouper_progress_rows(grouper_configs, waiting_by_barrier),
    )


def _index_waiting_barriers(waiting_links):
    """Index waiting barrier links by participant and by barrier."""
    waiting_by_participant = defaultdict(list)
    participants_by_barrier = defaultdict(list)

    for participant_id, barrier_id in waiting_links:
        waiting_by_participant[participant_id].append(barrier_id)
        participants_by_barrier[barrier_id].append(participant_id)

    waiting_by_barrier = {
        barrier_id: (len(participant_ids), sorted(participant_ids))
        for barrier_id, participant_ids in participants_by_barrier.items()
    }
    return waiting_by_participant, waiting_by_barrier


def _summarize_waiting_at_barriers(participant_ids, waiting_by_participant):
    """Return per-barrier waiting counts for the selected participants."""
    participants_by_barrier = defaultdict(list)
    for participant_id in participant_ids:
        for barrier_id in waiting_by_participant.get(participant_id, []):
            participants_by_barrier[barrier_id].append(participant_id)

    return [
        {
            "barrier_id": barrier_id,
            "waiting_count": len(participant_ids),
            "participant_ids": sorted(participant_ids),
        }
        for barrier_id, participant_ids in sorted(participants_by_barrier.items())
    ]


def _participant_row(link, group):
    """Build the dashboard row data for one participant/group link."""
    participant = link.participant
    active_in_group = getattr(link, "active", True)
    failure_tags = getattr(participant, "failure_tags", None)

    return {
        "id": participant.id,
        "failed": participant.failed,
        "status": getattr(participant, "status", None) or "—",
        "failed_reason": ", ".join(failure_tags) if failure_tags else None,
        "active_in_group": active_in_group,
        "can_fail_manually": (
            active_in_group
            and not participant.failed
            and participant.status == "working"
            and group.active
        ),
    }


def _simple_group_fields(group):
    """Return SimpleSyncGroup-only dashboard fields."""
    if not isinstance(group, SimpleSyncGroup):
        return {
            "min_group_size": None,
            "max_group_size": None,
            "initial_group_size": None,
            "accepts_top_ups": None,
        }

    return {
        "min_group_size": group.min_group_size,
        "max_group_size": group.max_group_size,
        "initial_group_size": group.initial_group_size,
        "accepts_top_ups": group.accepts_top_ups,
    }


def _group_row(group, waiting_by_participant):
    """Build the dashboard row data for one sync group."""
    participant_ids = {participant.id for participant in group.participants}
    participants = sorted(
        [_participant_row(link, group) for link in group.participant_links],
        key=lambda participant: participant["id"],
    )

    row = {
        "id": group.id,
        "group_type": group.group_type or "—",
        "active": group.active,
        "n_active_participants": group.n_active_participants,
        "leader_id": group.leader_id,
        "leader_worker_id": group.leader.worker_id if group.leader else "—",
        "end_time": group.end_time,
        "last_barrier_pass_time": group.last_barrier_pass_time,
        "participants": participants,
        "waiting_at_barriers": _summarize_waiting_at_barriers(
            participant_ids, waiting_by_participant
        ),
    }
    row.update(_simple_group_fields(group))
    return row


def _grouper_progress_rows(grouper_configs, waiting_by_barrier):
    """Combine timeline grouper config with live waiting counts."""
    rows = []
    for config in grouper_configs:
        barrier_id = config["barrier_id"]
        waiting_count, participant_ids = waiting_by_barrier.get(barrier_id, (0, []))
        rows.append(
            {
                "barrier_id": barrier_id,
                "group_type": config["group_type"],
                "batch_size": config.get("batch_size"),
                "initial_group_size": config.get("initial_group_size"),
                "waiting_count": waiting_count,
                "participant_ids": participant_ids,
            }
        )
    return rows

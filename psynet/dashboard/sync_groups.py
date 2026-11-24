"""The dashboard's Sync groups tab: groupers' progress, recent groups, and failing a member.

The tab only reads group state, apart from the Fail action, which fails the
participant through :meth:`~psynet.participant.Participant.fail` like any
other failure. Some of what it shows is derived rather than stored, such as a
group being *finished* (see ``_group_status``), so keep such display rules
here rather than adding columns that the framework would have to maintain.
"""

from collections import defaultdict

from dallinger.experiment_server.utils import error_response, success_response
from flask import render_template
from sqlalchemy.orm import joinedload

from psynet.participant import Participant, _lock_and_load_participant
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


def _fail_sync_group_participant(participant_id, sync_group_id, fail_reason):
    """Fail a working participant who is active in the given sync group."""
    if fail_reason != MANUAL_FAILURE_REASON:
        raise ValueError(f"Invalid fail reason: {fail_reason}")

    participant = _get_active_sync_group_participant(participant_id, sync_group_id)

    if not _is_taking_part(participant):
        raise ValueError(
            "Only participants still taking part can be failed manually; this "
            "participant has already failed, finished, or reached the end of "
            "the experiment."
        )

    participant.fail(MANUAL_FAILURE_REASON)
    return participant


def _get_active_sync_group_participant(participant_id, sync_group_id):
    """Lock and return a participant who is active in the given active sync group."""
    participant = _lock_and_load_participant(Participant.query, participant_id)
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

    return participant


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
    has_simple_groups = any(r["quorum"] is not None for r in group_rows)

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


def _is_taking_part(participant):
    """Return whether ``participant`` is still working through the main timeline.

    Every timeline branch other than ``"main"`` is end logic, such as the
    "That's the end!" page shown before the participant clicks Finish.
    """
    return (
        not participant.failed
        and participant.status == "working"
        and (participant.elt_id or ["main"])[0] == "main"
    )


def _members_taking_part(group, *, current_only):
    """Return the group's members who are still taking part (see ``_is_taking_part``).

    With ``current_only``, only admitted members who are still in the group;
    otherwise also pending members and members who have left it.
    """
    return [
        link.participant
        for link in group.participant_links
        if _is_taking_part(link.participant)
        and (not current_only or (link.active and link.admitted_at is not None))
    ]


def _group_status(group):
    """Return ``"active"``, ``"finished"`` or ``"closed"`` for the Status column.

    Groups only close when their last member leaves, so a group whose members
    all reached the end of the experiment, or were failed, stays active in the
    database; the dashboard shows it as finished instead, unless newcomers
    can still join it.
    """
    if not group.active:
        return "closed"
    if (
        group.participant_links
        and not group.accepts_top_ups
        and not _members_taking_part(group, current_only=False)
    ):
        return "finished"
    return "active"


def _finish_time(group):
    """Return when the last member of a finished group ended, or ``None`` if unknown."""
    end_times = [link.participant.end_time for link in group.participant_links]
    if not end_times or None in end_times:
        return None
    return max(end_times)


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
        "removal_reason": None if active_in_group else link.removal_reason,
        "can_fail_manually": (
            active_in_group and _is_taking_part(participant) and group.active
        ),
    }


def _simple_group_fields(group):
    """Return SimpleSyncGroup-only dashboard fields."""
    if not isinstance(group, SimpleSyncGroup):
        return {
            "quorum": None,
            "max_group_size": None,
            "initial_group_size": None,
            "accepts_top_ups": None,
            "top_ups_stopped_at": None,
        }

    return {
        "quorum": group.quorum,
        "max_group_size": group.max_group_size,
        "initial_group_size": group.initial_group_size,
        "accepts_top_ups": group.accepts_top_ups,
        "top_ups_stopped_at": group.top_ups_stopped_at,
    }


def _group_row(group, waiting_by_participant):
    """Build the dashboard row data for one sync group."""
    participant_ids = {participant.id for participant in group.participants}
    participants = sorted(
        [_participant_row(link, group) for link in group.participant_links],
        key=lambda participant: participant["id"],
    )

    status = _group_status(group)
    row = {
        "id": group.id,
        "group_type": group.group_type or "—",
        "status": status,
        "n_active_participants": len(_members_taking_part(group, current_only=True)),
        "leader_id": group.leader_id,
        "leader_worker_id": group.leader.worker_id if group.leader else "—",
        "end_time": _finish_time(group) if status == "finished" else group.end_time,
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

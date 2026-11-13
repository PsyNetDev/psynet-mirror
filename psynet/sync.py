"""
Synchronization primitives for coordinating participants.

This module contains the core building blocks for synchronous experiments.
If you have not seen PsyNet's synchronization features before, the key idea is
simple: participants move through a timeline, sometimes waiting for other
participants to arrive at the same point. We implement that waiting logic with
barriers, and we implement grouping logic with groupers and sync groups.

Glossary
--------
Barrier
    A timeline element that pauses participants until some release condition is
    satisfied (for example, "wait until two participants arrive"). Barriers are
    subclasses of ``Barrier``/``GroupBarrier``. By default the browser preserves
    the current page and shows a lightweight hold indicator while it waits.

Grouper and sync group
    A ``SimpleGrouper`` (or other grouper) is a timeline element that forms
    ``SyncGroup`` rows once enough participants are available. Group barriers
    rely on these groups to decide who to release together. A ``Regrouper``
    forms new groups every round, optionally within an existing group. Each
    group records the grouper that formed it and its ``within`` group, and
    each member's link records their role, so round counts, roles and when
    each pool was last split are read from these rows.

Barrier definition and instance
    A ``BarrierDefinition`` identifies the public waiting area. A
    ``BarrierInstance`` stores the stable behavior for one group visit.
    ``ParticipantLinkBarrier`` rows attach participants to that visit. At most
    one active instance exists per group visit, and ungrouped barriers share
    one active pool per barrier ID. Keeping definition, visit, and work-claim
    identities separate lets multiple worker processes cooperate without using
    mutable metadata as a mutex.

Whom a group barrier waits for
    A ``GroupBarrier`` waits for every active member of its group, wherever
    they are in the timeline; nothing about their position is inferred. A
    member stops being waited for only by leaving the group (``leave_group``,
    ``late_action``, ``max_wait_action``, failing or finishing). The
    release's round, if any, is the ``SyncGroupRound`` that every released
    member's unfinished trial is in (``_common_round``). If every member is
    waiting, but no barrier of the group has them all, nothing can pass:
    each ``check_barriers`` sweep looks for such groups
    (``_report_divergences``) and records each as an error once, with a
    token naming the group and the barriers, so later sweeps skip it until
    the group diverges at other barriers.

Where this shows up in a timeline
---------------------------------
The most common pattern is:

1. A grouper runs early in the timeline to create sync groups.
2. A ``GroupBarrier`` appears later in the timeline to pause participants until
   the group is ready.
3. After release, the timeline continues with shared or individual tasks.

How processing works
--------------------
When a participant reaches a barrier, ``Barrier.receive_participant``:

- Registers the definition and resolves a stable instance in the request's
  transaction. Group barriers use one instance per sync-group visit; groupers
  retain a shared waiting-pool instance.
- Inserts a ``ParticipantLinkBarrier`` row marking the participant as waiting.

A scheduled task in ``Experiment._check_barriers`` calls ``check_barriers`` in
this module. That loop:

- Dissolves sync groups whose dissolution waited because a member was busy
  in their own request (see ``SyncGroup._dissolve``).
- Applies ``max_wait_time`` to waiters whose hold or waiting-page deadline has
  passed. Their own request normally does this, so waiters who left would
  otherwise stay.
- Finds waiting barrier instances and checks them least recently checked
  first, new or changed ones with a head start, within a per-sweep time budget.
- Claims each with a PostgreSQL advisory transaction lock on a dedicated
  connection, leaving definition and instance metadata available to arrival
  requests. That extra transaction stays open until this poller's
  skip-after-commit finishes.
- Locks waiters, and their groups that accept top-ups, with ``NOWAIT``. If a
  waiter or top-up group is already locked (for example by
  ``POST /response`` or a newcomer joining), it skips that barrier this tick
  instead of blocking the poller.
- Evaluates the barrier's release hooks in an isolated transaction, then
  skips waiters **this poller** released, one row at a time, after that commit.
- Logs and skips failures per barrier so one bad barrier does not stall others.
- Keeps hold-wake publishes unpublished until the sweep returns.
- Reports groups whose members wait at different barriers of the group.

Each default barrier visit links to a durable ``TimelineHoldRecord``. Releasing
the link accounts waiting through the release time and queues a targeted browser
wake. After the database transaction commits, PsyNet sends that wake with
``publish_to_participants`` to the participant's checked connections; the
browser then rechecks the authoritative link state. See "Timeline holds" in
:doc:`/developer/page_lifecycle`.

``Barrier`` also queues those hooks when a participant arrives. After the
arrival transaction commits, the response route evaluates the barrier in a
short coordination transaction before rendering. That lets a ``Grouper`` form
groups and a ``GroupBarrier`` release the group without waiting for the poller.
Arrivals submitted with Next at a ``Regrouper`` with ``every`` are usually the
exception: they cannot make the pool ready, so they queue no check and the
poller normally enacts each due tick. An arrival or reload in ``GET /timeline``
still checks the waiter's visit (see PsyNet issue #1159).
Ungrouped arrivals at a ``within`` regrouper, and subclasses that override
``choose_who_to_release`` or ``check_waiting_participants``, keep the arrival
check; see
:meth:`Regrouper._queue_check_on_arrival`.
Last-arrival does not skip partner timeline cursors after that commit; partners
leave on overlay wake (or this poller, if it won the release). Waiter and
top-up group rows stay ``NOWAIT`` during the check so a locked partner or group
cannot stall that request for ``lock_timeout``.

Callable attributes on barriers (e.g., ``on_release``) persist through
:mod:`psynet.barrier_spec` so each ``BarrierInstance`` keeps stable release
behavior without pickling waiting pages. The reconstructed object is a
release/callback receiver, not a wait page. See :class:`Barrier` for which
methods are live-only.
"""

import inspect
import logging
import random
import time
import uuid
import warnings
from contextlib import contextmanager
from datetime import timedelta
from functools import partial
from math import ceil, floor
from typing import (
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    get_args,
)

from dallinger import db
from dallinger.models import timenow
from markupsafe import Markup
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    and_,
    distinct,
    exists,
    func,
    or_,
    select,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import (
    Session,
    backref,
    deferred,
    foreign,
    joinedload,
    lazyload,
    object_session,
    relationship,
    selectinload,
    undefer,
)
from sqlalchemy.orm.attributes import set_committed_value

from psynet.barrier_spec import (
    BarrierSpecError,
    barrier_from_spec_json,
    barrier_spec_json,
    behavior_hash_from_json,
)
from psynet.data import SQLBase, SQLMixin, register_table
from psynet.db import (
    _lock_timeout,
    _SessionQueue,
    _set_transaction_lock_timeout,
    is_transient_transaction_error,
    transaction,
)
from psynet.error import ErrorRecord
from psynet.field import PythonClass, PythonDict, PythonObject
from psynet.page import UnsuccessfulEndPage
from psynet.participant import Participant, _lock_and_load_participant
from psynet.serialize import SerializedCallable, serialize_callable
from psynet.timeline import (
    TIME_LIMIT_GRACE_SECONDS,
    CodeBlock,
    EltCollection,
    _is_timeline_hold,
    _trial_owning_page,
    conditional,
    join,
)
from psynet.timeline_hold import (
    HoldMessage,
    TimelineHoldRecord,
    _defer_timeline_hold_wakes,
    _queue_arrival_update,
    _queue_countdown_update,
    _queue_timeline_hold_wake,
    _reject_countdown,
    _TimelineHoldPage,
    compose_hold_overlay_html,
    default_group_barrier_arrival_message,
    default_hold_progress,
)
from psynet.utils import (
    NoArgumentProvided,
    call_if_callable,
    get_config,
    get_logger,
    get_translator,
    warn_from_caller,
)

logger = get_logger()

_BARRIER_FROM_SPEC_CACHE_KEY = "psynet_barrier_from_spec"


def _forget_barrier_from_spec(instance_id):
    """Drop a reconstructed barrier so a later check cannot reuse peek mutations.

    The visit-claim peek rolls back its savepoint, which undoes ORM writes.
    Python attributes on the cached registry object would otherwise survive.
    """
    session = db.session
    if session is None or instance_id is None:
        return
    cache = session.info.get(_BARRIER_FROM_SPEC_CACHE_KEY)
    if cache:
        cache.pop(instance_id, None)


# Shared cap for last-arrival finalize, ready-hold skip, and the poller sweep.
# Each pass can mint a fresh visit; without a bound those walks occupy a worker.
# Walkers observe once more after the last work unit so a walk that settles on
# the cap still succeeds.
_MAX_BARRIER_WALK_PASSES = 32

# Cap on the pages that a release skips in one pass of waiting_logic. While_loops
# in the pass end at their next check during the walk, so only for_loops and
# sequences repeat pages; reaching the cap means one of them is very long.
_MAX_RELEASE_WALK_STEPS = 1000


# The 0.5 s poller stops starting overdue timeouts, and separately visit
# checks, once each step has run this long; the rest wait for later sweeps.
_POLLER_SWEEP_BUDGET_SECONDS = 0.2

# How much sooner a new or changed visit is re-checked than an unchanged one.
_POLLER_CHANGE_HEAD_START_SECONDS = 5.0

# Poller-process memory: instance id -> (fingerprint, monotonic check time).
_poller_checked_visits = {}

# Poller-process memory: overdue waiters whose last timeout attempt raised.
_poller_failed_timeouts = set()


def _barrier_walk_budget():
    """Yield True for each allowed work unit, then False to observe the result.

    Callers must return if the walk has already settled, and raise if this
    yield is False and more work remains. That extra observation is what lets
    a walk that finishes on the last allowed unit succeed.
    """
    for _ in range(_MAX_BARRIER_WALK_PASSES):
        yield True
    yield False


class BarrierBehaviorMismatch(ValueError):
    """A participant arrived at a barrier whose waiting pool was started by a
    barrier with the same ID and different behavior."""


class _BarrierAuthorHookError(Exception):
    """Author ``on_release`` failed; last-arrival keeps the group waiting."""


# Read by the request after its transaction commits. A savepoint rollback
# restores them, so a later instance's waiter ``NOWAIT`` miss does not wipe
# stacked checks queued by an earlier skip in the same sweep.
_pending_barrier_checks = _SessionQueue("pending_barrier_checks", set)
_released_hold_waiter_ids = _SessionQueue("released_hold_waiter_ids", set)


def _queue_barrier_check(barrier_instance_id):
    """Queue one instance for checking after the arrival transaction commits."""
    _pending_barrier_checks.get().add(barrier_instance_id)


def _take_pending_barrier_checks():
    """Take the barrier checks queued by the preceding successful transaction."""
    return sorted(_pending_barrier_checks.take())


def _queue_released_hold_waiters(participants):
    """Remember released waiters so the poller can skip them after its own check."""
    _released_hold_waiter_ids.get().update(
        participant.id for participant in participants
    )


def _take_released_hold_waiter_ids():
    """Take waiter ids queued by the barrier check that just ran."""
    return sorted(_released_hold_waiter_ids.take())


def _rollback_preserving_barrier_queues():
    """Roll back without dropping queued post-commit barrier work.

    Skip-after-commit may ``NOWAIT``-miss a waiter whose own request already
    holds the row. PostgreSQL aborts that transaction, so the session must
    roll back before the next waiter. ``after_rollback`` would otherwise
    discard stacked checks queued by a waiter this loop already skipped.
    """
    pending = _pending_barrier_checks.peek()
    released = _released_hold_waiter_ids.peek()
    db.session.rollback()
    _pending_barrier_checks.replace(pending)
    _released_hold_waiter_ids.replace(released)


def _hold_instance_id_for_page(participant, page):
    """Return the unreleased hold instance for this page, if any."""
    if not _is_timeline_hold(page):
        return None
    barrier_id = getattr(page, "barrier_id", None)
    if barrier_id is None:
        return None
    barriers = getattr(participant, "active_barriers", None)
    if not barriers:
        return None
    link = barriers.get(barrier_id)
    if link is None or link.released or link.barrier_instance_id is None:
        return None
    return link.barrier_instance_id


def _visit_check_would_release(instance_id):
    """Return whether evaluating this visit would release waiters.

    Read-only: used before deciding to wait for the visit claim. Spec errors
    match the check path (do not wait, do not fail the arriver). Other
    non-transient peek failures wait so last-arrival still skips in one GET.
    Transient database errors propagate so the request can return HTTP 503.
    """
    try:
        nested = db.session.begin_nested()
        try:
            instance = BarrierInstance.query.get(instance_id)
            if instance is None:
                result = False
            else:
                barrier = instance.get_barrier()
                if not isinstance(barrier, Barrier):
                    result = True
                else:
                    waiting = _get_waiting_participants(
                        instance.barrier_id,
                        instance.id,
                        for_update=False,
                        nowait=False,
                    )
                    result = bool(barrier.would_release(waiting))
        finally:
            nested.rollback()
            _forget_barrier_from_spec(instance_id)
        return result
    except BarrierSpecError:
        logger.exception(
            "Barrier instance %s failed a side-effect-free release peek "
            "because of a spec error.",
            instance_id,
        )
        return False
    except Exception as err:
        if is_transient_transaction_error(err):
            raise
        logger.exception(
            "Barrier instance %s failed a side-effect-free release peek.",
            instance_id,
        )
        return True


def _pending_checks_should_wait_for_claim(instance_ids):
    """Return whether this request may block on the visit claim for these checks.

    Waiter arrivals that cannot release must not occupy a worker behind
    last-arrival. A filled visit still waits so stacked holds skip in one
    request. ``GET /timeline`` and ``POST /response`` both use this peek.
    """
    return any(_visit_check_would_release(instance_id) for instance_id in instance_ids)


def _execute_advisory_xact_lock(bind, instance_id, *, wait):
    """Take or try the visit xact claim on ``bind``.

    ``pg_advisory_xact_lock`` returns void, so a blocking claim must not use
    ``bool(scalar())`` — that would look like a missed claim after a wait.
    """
    if wait:
        bind.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:instance_id, 0))"),
            {"instance_id": instance_id},
        )
        return True
    return bool(
        bind.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:instance_id, 0))"),
            {"instance_id": instance_id},
        ).scalar()
    )


def _pool_claim_key(barrier_id, group_id):
    """Return the claim key held while a waiting pool is created or reactivated.

    The pool's partial unique index allows one active instance, so every
    write that makes an instance active must hold this key.
    """
    if group_id is None:
        return barrier_id
    return f"{barrier_id}:group:{group_id}"


def _claim_barrier_instance(instance_id, *, wait=False):
    """Claim one barrier visit on the ORM session.

    Instance *creation* uses this on a scope key distinct from the visit id.
    Check-and-skip holds the visit id on a dedicated connection instead, so
    the ORM session does not wait on itself.
    """
    return _execute_advisory_xact_lock(db.session, instance_id, wait=wait)


@contextmanager
def _hold_barrier_instance_claim(instance_id, *, wait=False):
    """Hold the visit xact claim on a dedicated connection until the caller exits.

    Check and skip run on ``db.session`` and must not acquire this same key
    while the extra transaction is open. Ending this transaction drops the
    claim even if skip raises, so the lock cannot leak into the pool.
    """
    with db.engine.connect() as conn:
        with conn.begin():
            if wait:
                # A try-lock never waits, so it needs no lock timeout.
                _set_transaction_lock_timeout(
                    get_config().get("timeline_lock_timeout_seconds"), session=conn
                )
            acquired = _execute_advisory_xact_lock(conn, instance_id, wait=wait)
            yield acquired


def _get_waiting_participants(
    barrier_id: str,
    barrier_instance_id: str,
    *,
    for_update: bool,
    nowait: bool,
) -> List[Participant]:
    """Return active waiters for one persisted barrier visit.

    Per-waiter collections use ``selectinload``, not extra ``joinedload`` on
    this query. The lock clause already targets the link and participant
    rows; joining ``timeline_hold`` or those collections would add more
    outer joins to a ``FOR UPDATE`` statement (a PostgreSQL footgun) or a
    cartesian product. ``Participant._current_trial`` is already
    ``lazy="joined"``, so this query inherits one outer join to ``trial``;
    that alias is not in the ``OF`` list. The follow-up ``IN`` queries do
    not take extra row locks.

    ``active_barriers`` and ``sync_group_links`` are populated separately;
    see ``_populate_active_barriers`` and ``_populate_sync_group_links``.

    A locked load that waited would join the waiters' trials as they were
    before the wait (see :func:`psynet.participant._load_participant_for_update`).
    So unless ``nowait`` is set, a bare statement takes the locks first and
    the joined load, limited to the links it locked, then runs with
    ``NOWAIT``, which cannot fail on rows already held.
    """
    criteria = [
        ParticipantLinkBarrier.barrier_id == barrier_id,
        ParticipantLinkBarrier.barrier_instance_id == barrier_instance_id,
        ~ParticipantLinkBarrier.released,
        ~Participant.failed,
        Participant.status == "working",
    ]
    if for_update and not nowait:
        locked_link_ids = (
            db.session.execute(
                select(ParticipantLinkBarrier.id)
                .join(Participant)
                .where(*criteria)
                .order_by(Participant.id)
                .with_for_update(of=[ParticipantLinkBarrier, Participant])
            )
            .scalars()
            .all()
        )
        if not locked_link_ids:
            return []
        criteria.append(ParticipantLinkBarrier.id.in_(locked_link_ids))
        nowait = True
    query = (
        ParticipantLinkBarrier.query.join(Participant)
        .filter(*criteria)
        .options(
            joinedload(ParticipantLinkBarrier.participant, innerjoin=True).options(
                lazyload(Participant.active_barriers),
            ),
            selectinload(ParticipantLinkBarrier.timeline_hold),
        )
        .order_by(Participant.id)
    )
    if for_update:
        query = query.with_for_update(
            of=[ParticipantLinkBarrier, Participant],
            nowait=nowait,
        ).populate_existing()
    links = query.all()
    waiters = [link.participant for link in links]
    _populate_active_barriers(waiters)
    _populate_sync_group_links(waiters)
    # Without row locks, another request can release a waiter between the
    # two queries, and they may already be waiting at a later visit.
    return [
        p
        for p in waiters
        if barrier_id in p.active_barriers
        and p.active_barriers[barrier_id].barrier_instance_id == barrier_instance_id
    ]


def _arrival_time(barrier, participant):
    """Return when this participant arrived at the barrier they are waiting at."""
    return participant.active_barriers[barrier.id].arrival_time


def _populate_active_barriers(participants):
    """Batch-load ``active_barriers`` without a relationship loader option.

    The waiter links are themselves members of ``active_barriers``. A nested
    loader under ``populate_existing`` reloads those same links and resets
    their eager-loaded ``timeline_hold``, so releasing each waiter lazy-loads
    it and flushes its UPDATEs one row at a time. An explicit ``IN`` query
    returns the identity-mapped links unchanged, provided the caller still
    holds them: the identity map is weak.
    """
    if not participants:
        return
    grouped = {participant.id: [] for participant in participants}
    for link in ParticipantLinkBarrier.query.filter(
        ParticipantLinkBarrier.participant_id.in_(list(grouped)),
        ~ParticipantLinkBarrier.released,
    ):
        grouped[link.participant_id].append(link)
    for participant in participants:
        set_committed_value(participant, "active_barriers", grouped[participant.id])


def _load_link_participants(links):
    """Batch-load ``link.participant`` for group links that have not loaded it.

    Group walks would otherwise lazy-load each member, plus that member's
    select-in collections, once per member.
    """
    unloaded = [
        link
        for link in links
        if "participant" in sa_inspect(link).unloaded and link.participant_id
    ]
    if not unloaded:
        return
    session = db.session()
    mapper = sa_inspect(Participant)
    by_id = {}
    for link in unloaded:
        key = mapper.identity_key_from_primary_key((link.participant_id,))
        cached = session.identity_map.get(key)
        if cached is not None and not sa_inspect(cached).expired:
            by_id[link.participant_id] = cached
    missing_ids = {link.participant_id for link in unloaded} - set(by_id)
    if len(missing_ids) > 1:
        by_id.update(
            (participant.id, participant)
            for participant in Participant.query.filter(Participant.id.in_(missing_ids))
        )
    for link in unloaded:
        if link.participant_id in by_id:
            set_committed_value(link, "participant", by_id[link.participant_id])


def _prime_timeline_hold_records(participants, barrier_id):
    """Batch-load waiters' hold records so per-member hold lookups skip SQL."""
    links = {p.id: p.active_barriers.get(barrier_id) for p in participants}
    hold_ids = {
        link.timeline_hold_id
        for link in links.values()
        if link is not None
        and link.timeline_hold_id
        and "timeline_hold" in sa_inspect(link).unloaded
    }
    if len(hold_ids) < 2:
        return
    records = {
        record.id: record
        for record in TimelineHoldRecord.query.filter(
            TimelineHoldRecord.id.in_(hold_ids)
        )
    }
    for participant in participants:
        link = links[participant.id]
        record = records.get(link.timeline_hold_id) if link is not None else None
        if record is None:
            continue
        set_committed_value(link, "timeline_hold", record)
        if record.page_uuid == participant.page_uuid:
            participant._timeline_hold_record = record


def _populate_sync_group_links(participants):
    """Batch-load ``sync_group_links`` without a relationship loader option.

    ``selectinload(Participant.sync_group_links)`` on the waiter query makes
    later group walks lazy-load that collection once per member, which shows
    up as extra statements in arrival-notice lookups. An explicit ``IN``
    query plus ``set_committed_value`` keeps the check O(1) without that
    side effect.

    Call this before ``add_participant`` in the same transaction, or after
    ``expire_all``. ``set_committed_value`` replaces the collection and drops
    pending in-session links that have not been flushed.
    """
    if not participants:
        return
    grouped = {participant.id: [] for participant in participants}
    for link in ParticipantLinkSyncGroup.query.filter(
        ParticipantLinkSyncGroup.participant_id.in_(list(grouped))
    ):
        grouped[link.participant_id].append(link)
    for participant in participants:
        set_committed_value(participant, "sync_group_links", grouped[participant.id])


_HAS_ACTIVE_SYNC_GROUP_ATTR = "_psynet_has_active_sync_group"


def _membership_cache():
    """Return the per-session membership memo, or ``None`` if no session."""
    session = db.session
    if session is None:
        return None
    return session.info.setdefault(_HAS_ACTIVE_SYNC_GROUP_ATTR, {})


def _remember_active_sync_group(participant, participant_id, result):
    """Memoize a membership check on the instance and the current session."""
    participant.__dict__[_HAS_ACTIVE_SYNC_GROUP_ATTR] = result
    cache = _membership_cache()
    if cache is not None:
        cache[participant_id] = result
    return result


def _forget_active_sync_group(participant):
    """Drop a stale membership memo after grouping changes."""
    participant_id = getattr(participant, "id", None)
    if participant_id is not None:
        participant.__dict__.pop(_HAS_ACTIVE_SYNC_GROUP_ATTR, None)
        cache = _membership_cache()
        if cache is not None:
            cache.pop(participant_id, None)


def _has_active_sync_group(participant):
    """Return whether this participant currently belongs to an active sync group.

    This is a cheap ``EXISTS`` query, memoized for the rest of the session so
    page rendering does not repeat it. Callers that already loaded
    ``sync_group_links`` should inspect ``active_sync_groups`` instead so
    ungrouped pages skip even this lookup.
    """
    participant_id = getattr(participant, "id", None)
    if participant_id is None:
        return False
    cache = _membership_cache()
    if cache is not None and participant_id in cache:
        return cache[participant_id]
    cached = participant.__dict__.get(_HAS_ACTIVE_SYNC_GROUP_ATTR)
    if cached is not None:
        return _remember_active_sync_group(participant, participant_id, cached)
    result = (
        db.session.query(ParticipantLinkSyncGroup.id)
        .join(ParticipantLinkSyncGroup.sync_group)
        .filter(
            ParticipantLinkSyncGroup.participant_id == participant_id,
            ParticipantLinkSyncGroup.active.is_(True),
            SyncGroup.active.is_(True),
        )
        .first()
        is not None
    )
    return _remember_active_sync_group(participant, participant_id, result)


class _BarrierHoldPage(_TimelineHoldPage):
    """Internal timeline checkpoint that preserves the preceding browser page."""

    def __init__(self, barrier):
        self.barrier = barrier
        self.barrier_id = barrier.id
        super().__init__(
            hold_id=f"barrier:{barrier.id}",
            expected_wait=barrier.expected_wait,
            max_wait_time=barrier._max_wait_time_for,
            fix_time_credit=barrier.fix_time_credit,
            check_interval=2.0,
            waiting_message=barrier.waiting_message,
            message_kind="barrier" if barrier.waiting_message is None else None,
            on_timeout=barrier.handle_max_wait_timeout,
            waiting_screen=barrier.waiting_screen,
        )

    @property
    def fail_on_timeout(self):
        return self.barrier._fails_on_timeout

    @staticmethod
    def failure_releases_hold(experiment, participant):
        """Release failed participants anywhere, because barriers never release them."""
        return participant.failed

    def participant_timed_out(self, participant):
        """Return whether the deadline passed before the barrier released the participant.

        A release counts even if it came after the deadline: the barrier
        released the participant together with others, for example into a
        new sync group, and failing them now would also fail the rest of
        that group.
        """
        record = self.get_hold_record(participant)
        if record is not None and record.released_at is not None:
            return False
        return super().participant_timed_out(participant)

    def participant_can_resume(self, experiment, participant):
        """Return whether the barrier released this participant.

        Check the in-session ``released`` flag. SQLAlchemy does not drop a
        just-released link from ``active_barriers`` until the collection
        expires, so membership alone would hide a same-request last-arrival
        release from ``_advance_past_ready_holds``.
        """
        link = participant.active_barriers.get(self.barrier_id)
        return link is None or bool(link.released)

    def on_hold_record_created(self, participant, record):
        link = participant.active_barriers.get(self.barrier_id)
        if link is None:
            raise RuntimeError(
                f"Participant {participant.id} has no active link for barrier "
                f"'{self.barrier_id}'."
            )
        link.timeline_hold = record
        self.barrier._queue_check_on_arrival(link.barrier_instance)
        self.barrier._notify_arrivals(participant)

    def hold_progress_text(self, participant, counts=None):
        """Return arrival progress for a participant waiting at this barrier."""
        if participant is None:
            return None
        return self.barrier._hold_progress_text(participant, counts)

    def overlay_html(
        self, participant=None, release_time=NoArgumentProvided, *, counts=None
    ):
        """Return hold copy, calling a ``waiting_message`` function and filling in ``{SECONDS}``.

        Parameters
        ----------
        participant : Participant, optional
            The waiting participant.
        release_time : float or None, optional
            Epoch seconds, or ``None`` if unknown. Defaults to the barrier's
            :meth:`~Barrier.expected_release_time`.
        counts : dict, optional
            The barrier's hold message counts for ``participant``
            (``waiting_count`` and ``group_size``). Callers
            that render the overlay for every member of a group pass them,
            so the group is not recounted per member.
        """
        if self._is_silent_for(participant):
            return compose_hold_overlay_html("", None)
        message = self.waiting_message
        message_is_function = isinstance(message, SerializedCallable)
        if not message_is_function and "{SECONDS}" not in str(message or ""):
            return compose_hold_overlay_html(
                self.translated_waiting_message(participant),
                self.hold_progress_text(participant, counts),
            )
        if release_time is NoArgumentProvided:
            release_time = (
                None
                if participant is None
                else self.barrier.expected_release_time(participant)
            )
        remaining_ms = (
            None if release_time is None else round((release_time - time.time()) * 1000)
        )
        seconds = None if remaining_ms is None else max(0, ceil(remaining_ms / 1000))
        if (
            remaining_ms is None
            and not message_is_function
            and isinstance(self.barrier, SimpleGrouper)
        ):
            # Until enough people wait to start short, the countdown has no
            # number, so show the default text; the grouper sends the
            # message again once the countdown starts.
            _p = get_translator(context=True)
            return compose_hold_overlay_html(
                _p("timeline_hold", "Waiting for other participants…"),
                self.hold_progress_text(participant, counts),
            )
        if message_is_function:
            if counts is None:
                counts = self.barrier._hold_message_counts(participant)
            context = {} if participant is None else {"participant": participant}
            message = message(
                barrier=self.barrier,
                seconds_left=seconds,
                **context,
                **counts,
            )
        html = compose_hold_overlay_html(
            message, self.hold_progress_text(participant, counts)
        )
        if "{SECONDS}" not in html:
            return html
        if remaining_ms is None or remaining_ms <= 0:
            # The span takes a countdown if the barrier later sends one.
            countdown = Markup(
                '<span class="psynet-timeline-hold-countdown">{}</span>'
            ).format("…" if remaining_ms is None else 0)
        else:
            # Screen readers get the starting value once, not a live region
            # that changes every second.
            countdown = Markup(
                '<span class="psynet-timeline-hold-countdown" aria-hidden="true"'
                ' data-release-in-ms="{}">{}</span>'
                '<span class="visually-hidden">{}</span>'
            ).format(remaining_ms, seconds, seconds)
        return Markup(html.replace("{SECONDS}", countdown))

    def prepare_to_resume(self, participant):
        if (
            participant.pending_redirect is not None or participant.failed
        ) and self.barrier_id in participant.active_barriers:
            participant.active_barriers[self.barrier_id].release()


class _ReadOnlyParticipantList(list):
    """A participant list whose membership must be changed through its group."""

    def _raise_mutation_error(self, *args, **kwargs):
        raise TypeError(
            "SyncGroup.participants is read-only; use group.add_participant() "
            "or group.remove_participant() instead."
        )

    append = clear = extend = insert = pop = remove = reverse = sort = (
        _raise_mutation_error
    )
    __delitem__ = __iadd__ = __imul__ = __setitem__ = _raise_mutation_error


def _expected_repetitions(waiting_logic, expected_wait, default):
    """Return how often ``waiting_logic`` is expected to run to fill ``expected_wait``.

    Called when the barrier is built, before the timeline multiplies the
    logic's own repetition estimates.
    """
    from psynet.timeline import estimate_duration

    if expected_wait is None:
        return default
    duration = estimate_duration(waiting_logic)
    if duration <= 0:
        return 1
    return max(1, ceil(expected_wait / duration - 1e-9))


def hold_message(title, progress=None):
    """Return a waiting message with its own progress line.

    By default, a :class:`GroupBarrier`'s waiting indicator shows its
    ``waiting_message`` with a smaller progress line underneath in groups of three or
    more ("1 of 3 not ready yet"). Return ``hold_message(title, progress)``
    from a ``waiting_message`` function to write that line yourself, or leave out
    ``progress`` to show no progress line. The message is redrawn as members
    arrive unless the barrier has ``on_arrival_message=None``.

    Parameters
    ----------
    title
        The waiting message, as for ``waiting_message``.
    progress
        Optional second line, for example ``f"{waiting_count} of {group_size}
        are ready"``.

    Examples
    --------
    ::

        def waiting_text(waiting_count, group_size):
            return hold_message(
                "Waiting for the rest of the room…",
                f"{waiting_count} of {group_size} have chosen",
            )

        GroupBarrier(id_="chosen", group_type="room", waiting_message=waiting_text)
    """
    return HoldMessage(title, progress)


class Barrier(EltCollection):
    """
    A barrier is a timeline construct that holds participants in a waiting area until certain conditions
    are satisfied to release them. The decision about which participants to release at any given point is taken by
    the ``choose_who_to_release`` method, which the user is expected to provide.

    Timeline construction and wait UI run on this live object. Barrier checks,
    ``on_release``, and arrival-notice lookups reconstruct a separate object
    from :func:`~psynet.barrier_spec.barrier_from_spec_json`. That reconstructed
    object has ``id``, custom release state, scalar presentation (``waiting_message``,
    timeouts), and notification settings. It does not include wait-page
    construction (``waiting_logic``, ``waiting_screen``,
    ``_uses_timeline_hold`` and the expected repetitions of
    ``waiting_logic``).

    Call :meth:`check_waiting_participants`, :meth:`choose_who_to_release`,
    and :meth:`release` on reconstructed objects. Keep
    :meth:`receive_participant` on the live timeline barrier; arrival overlay
    notify (``_notify_arrivals``) is live-only as well.

    Parameters
    ----------

    id_
        ID parameter for the barrier. Barriers with the same ID share waiting areas; this allows participants
        at different points in the timeline to share the same waiting areas.

    waiting_logic
        Either a single timeline element or a list of timeline elements (created by ``join``) that is to be displayed
        to the participant while they are waiting at the barrier. Use it to
        give participants something to do while they wait, such as filler
        trials, and ``waiting_screen`` to show them something. If left at the
        default value of ``None``, the participant sees ``waiting_screen``,
        or their current page beneath a lightweight waiting indicator.
        Several barriers can share the same elements. Keep it atomic, with
        one short trial or page per pass (the loop repeats it), such as
        ``PageMaker(trial_maker.cue_trial, ...)`` in the ``sync_quorum``
        demo: a release then fails at most the trial on screen and creates
        no unseen trials (see ``release_grace``). A barrier with
        ``waiting_logic`` can't be inside a trial's own pages, such as in
        ``Trial.show_trial``; use ``waiting_screen`` there.

    waiting_logic_expected_repetitions
        Deprecated; pass ``expected_wait`` instead. Expected repetitions of
        ``waiting_logic``.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded then the participant will be failed and sent to the end of the experiment.
        May also be a function of ``participant``, evaluated once when the participant arrives.
        This is a hard limit counted from arrival: with explicit ``waiting_logic``, the server applies it
        even while the participant is partway through a filler page, so make it long enough to cover long
        filler pages (for example trials used as filler).

    fix_time_credit
        If set to ``True``, award fixed expected time credit. Otherwise default
        holds credit actual visible waiting time up to ``max_wait_time``.

    expected_wait
        Seconds participants are expected to wait here, used for progress
        estimates and fixed time credit. Default: 1.5 seconds. With
        ``waiting_logic``, the estimate is instead as many whole passes of the
        waiting logic as fill this time (at least one), or three passes if omitted.

    waiting_message
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. If omitted, participants see
        "Waiting for other participants…". Plain strings are shown as text;
        pass ``markupsafe.Markup`` or a dominate tag for HTML. On barriers
        with a release time (:class:`SimpleGrouper` with ``start_short_after``,
        :class:`Regrouper` with ``deadline`` or ``every``, or a subclass that
        overrides :meth:`expected_release_time`), a ``{SECONDS}`` placeholder
        counts down to that time, showing "…" while it is unknown (a
        :class:`SimpleGrouper` shows "Waiting for other participants…" instead
        until enough people wait to start short); elsewhere it raises an error. ``waiting_message`` can also be a module-level function
        that returns the message, for example one that depends on the
        participant's role; it may take ``participant``, ``seconds_left``
        (whole seconds, or ``None`` while the release time is unknown) and
        ``barrier``, and on a :class:`GroupBarrier` also ``waiting_count``
        and ``group_size`` (both ``None`` if the participant has no group).
        It is called again whenever the release time changes, so for a live
        countdown return a literal ``"{SECONDS}"`` rather than formatting
        ``seconds_left`` into the text. Return :func:`hold_message` to set the
        progress line under the message yourself.

    waiting_screen
        What to show in place of the current page while the participant
        waits: a prompt, text or HTML (shown without a Next button), or a
        :class:`~psynet.modular_page.ModularPage` that nothing submits, for
        example with ``NullControl(show_next_button=False)``. Pass a
        module-level function to show each participant their own screen. It
        may take ``participant``, ``trial`` (their ``current_trial``, or
        ``None``) and ``group_round`` (that trial's
        :class:`SyncGroupRound`, or ``None`` if it is in no group's round),
        for example
        ``waiting_screen(trial, group_round)`` to show the player's answer and the
        round's state. At a grouper or :class:`Regrouper`, ``trial`` is the
        participant's previous trial, such as the previous round's, because
        ``current_trial`` only changes when the next trial is cued. It runs on each request (a page load
        or a check for the release), sometimes more than once, so base it on
        the participant's state
        rather than on chance. Returning ``None`` keeps the current page, as
        omitting ``waiting_screen`` does; if that page is another barrier's
        waiting screen, a plain waiting page replaces it. The ``waiting_message`` still shows
        on top. A page with a Next button, push buttons or ``auto_advance``,
        or one that needs a full page reload (for
        example deprecated ``js_links``) while
        ``inplace_timeline_transitions`` is on, raises ``ValueError`` when
        it is shown. Only used when ``waiting_logic`` is omitted.

    release_grace
        Seconds a participant on a ``waiting_logic`` page has to finish it
        once they are released; the page then ends without an answer,
        recorded with ``"interrupted": True`` in its response metadata.
        The rest of the participant's pass of ``waiting_logic`` is then run
        through without showing its pages (code blocks still run), and each
        ``while_loop`` in it ends at its next check. This includes the pages of trials in ``waiting_logic``, such as
        filler trials from a trial maker: a trial whose page ends this way,
        and any trial that the rest of the pass reaches, which is created
        but never shown, is failed with
        ``failed_reason="interrupted_by_release"``, so it isn't finalized,
        shows no feedback, and doesn't count towards the trial maker's
        targets of completed trials (it still counts towards
        ``max_trials_per_block`` and ``n_created_trials``).
        ``None`` lets each waiting page run to its end. Default: 3 seconds.
        Only used with ``waiting_logic``; passing it without raises an error.
    """

    # Reconstructed barriers skip ``__init__`` and never render a hold page.
    waiting_screen = None

    def __new__(cls, *args, **kwargs):
        _reject_release_candidate_options(
            cls.__name__, kwargs, _BARRIER_RELEASE_CANDIDATE_OPTIONS
        )
        return super().__new__(cls)

    def __init__(
        self,
        id_: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=None,
        max_wait_time=20,
        fix_time_credit=False,
        expected_wait=None,
        waiting_message=None,
        release_grace: Optional[float] = NoArgumentProvided,
        waiting_screen=None,
    ):
        self.id = id_
        self.max_wait_time = max_wait_time
        self.fix_time_credit = fix_time_credit
        if waiting_logic_expected_repetitions is not None:
            warn_from_caller(
                "waiting_logic_expected_repetitions is deprecated; pass expected_wait "
                "(in seconds) instead.",
                FutureWarning,
            )
            if expected_wait is not None:
                raise ValueError(
                    "Pass expected_wait or waiting_logic_expected_repetitions, not both."
                )
        self.waiting_logic_expected_repetitions = waiting_logic_expected_repetitions
        self.waiting_message = waiting_message
        self.waiting_screen = waiting_screen
        self._uses_timeline_hold = waiting_logic is None
        if waiting_logic is not None and waiting_message is not None:
            raise ValueError(
                "waiting_message only applies when waiting_logic is omitted."
            )
        if waiting_logic is not None and waiting_screen is not None:
            raise ValueError(
                "waiting_screen only applies when waiting_logic is omitted."
            )
        default_repetitions = (
            3
            if waiting_logic_expected_repetitions is None
            else waiting_logic_expected_repetitions
        )
        self.expected_wait = (
            0.5 * default_repetitions if expected_wait is None else expected_wait
        )
        if self.expected_wait < 0:
            raise ValueError("expected_wait must be non-negative.")
        if waiting_logic is None and release_grace is not NoArgumentProvided:
            raise ValueError(
                "release_grace only applies with waiting_logic: a participant on "
                "the default waiting indicator leaves as soon as they are released."
            )
        if release_grace is NoArgumentProvided:
            release_grace = 3
        if release_grace is not None and release_grace < 0:
            raise ValueError("release_grace must be non-negative or None.")
        self.release_grace = None if waiting_logic is None else release_grace
        self._waiting_logic_repetitions = (
            None
            if waiting_logic is None
            else _expected_repetitions(
                waiting_logic, expected_wait, default_repetitions
            )
        )
        if waiting_logic is None:
            waiting_logic = _BarrierHoldPage(self)

        self.waiting_logic = waiting_logic
        self.max_wait_action = "fail"

    def __setattr__(self, name, value):
        if name.startswith("on_") or (
            name == "waiting_message"
            and (inspect.isroutine(value) or isinstance(value, partial))
        ):
            value = serialize_callable(value, f"{self.__class__.__name__}.{name}")
        super().__setattr__(name, value)

    def choose_who_to_release(
        self, waiting_participants: List[Participant]
    ) -> List[Participant]:
        """
        Given a list of waiting participants, decides which of these participants should be released
        from the barrier.

        Runs on the reconstructed registry barrier during evaluation.

        Parameters
        ----------
        waiting_participants
            A list of waiting participants.

        Returns
        -------

        A list of participants to be released.
        """
        raise NotImplementedError

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        """Return whether evaluating this visit would release anyone.

        ``GET /timeline`` uses this to decide whether to wait for the visit
        claim. It must not mutate participants, groups, or the session.
        Last-arrival skip-in-one-GET waits only when this is true. Custom
        barriers that override :meth:`choose_who_to_release` should override
        this too. The default is ``True`` whenever anyone is waiting, so a
        missing override still waits rather than first-painting a hold.
        """
        return bool(waiting_participants)

    def resolve(self):
        from psynet.timeline import while_loop

        if not self._shows_countdown():
            _reject_countdown(
                self.waiting_message, f"{type(self).__name__} '{self.id}'"
            )
        if self._uses_timeline_hold:
            waiting_elts = self.waiting_logic
        else:
            waiting_elts = while_loop(
                label=f"barrier:{self.id}",
                condition=lambda participant: (
                    not self.can_participant_exit(participant)
                ),
                logic=self.waiting_logic,
                expected_repetitions=self._waiting_logic_repetitions,
                max_loop_time=self._arrival_max_wait_time,
                fix_time_credit=self.fix_time_credit,
                fail_on_timeout=self._fails_on_timeout,
                on_timeout=self.handle_max_wait_timeout,
            )

        leave = CodeBlock(_leave_waiting_logic)
        elts = join(
            CodeBlock(lambda participant: self.receive_participant(participant)),
            waiting_elts,
            leave,
            conditional(
                "participant_failed",
                condition=lambda participant: participant.failed,
                logic_if_true=UnsuccessfulEndPage(),
                time_estimate=0,
                log_chosen_branch=False,
            ),
        )
        for elt in elts:
            # Keep an inner barrier's link: its waiting pages belong to it.
            # ``leave`` gets the enclosing barrier's link, if any, to hand
            # the participant back to it.
            if elt is not leave:
                elt.links.setdefault("barrier", self)
        return elts

    def handle_max_wait_timeout(self, participant: Participant):
        """Release the participant's active barrier link after a max-wait timeout."""
        if self.id in participant.active_barriers:
            self.release(participant)

    @property
    def _fails_on_timeout(self) -> bool:
        """Whether the wait itself fails a waiter after :meth:`handle_max_wait_timeout`."""
        return self.max_wait_action == "fail"

    def _max_wait_time_for(self, participant, experiment=None):
        """Return the longest ``participant`` may wait here, in seconds, or ``None`` for no limit."""
        return call_if_callable(
            self.max_wait_time, participant=participant, experiment=experiment
        )

    def receive_participant(self, participant: Participant):
        """Register this participant on the live timeline barrier.

        Live timeline only. Default holds queue the release check from the
        hold page after the wait row exists.
        """
        if object_session(participant) is None:
            db.session.add(participant)
        if not self._uses_timeline_hold and _trial_owning_page(participant):
            raise ValueError(
                f"Barrier '{self.id}' has waiting_logic but is inside the pages "
                "of a trial, whose release would end that trial without an "
                "answer. Use waiting_screen for a barrier inside a trial."
            )

        barrier_instance = BarrierInstance.for_arrival(self, participant)

        now = timenow()
        link = ParticipantLinkBarrier(
            participant=participant,
            barrier_id=self.id,
            barrier_instance=barrier_instance,
            arrival_time=now,
            ran_out_of_time=bool(participant.timed_out_since_barrier),
        )
        participant.timed_out_since_barrier = False
        participant.waiting_barrier_id = self.id
        participant.active_barriers[self.id] = link
        if not self._uses_timeline_hold:
            max_wait_time = self._max_wait_time_for(participant)
            if max_wait_time is not None:
                link.deadline_at = now + timedelta(seconds=max_wait_time)
            self._queue_check_on_arrival(barrier_instance)
            self._notify_arrivals(participant)

    def _arrival_max_wait_time(self, participant):
        """Return the ``max_wait_time`` resolved when the participant arrived, in seconds."""
        link = participant.active_barriers.get(self.id)
        if link is None or link.deadline_at is None:
            return None
        return (link.deadline_at - link.arrival_time).total_seconds()

    def _queue_check_on_arrival(self, barrier_instance):
        """Schedule the fast release check for immediately after commit."""
        _queue_barrier_check(barrier_instance.id)

    def _notify_arrivals(self, arriving_participant):
        """Optionally tell the group that someone arrived at this barrier.

        Live timeline only. Overlay HTML comes from ``waiting_logic``.
        """

    def _hold_progress_text(self, participant, counts=None):
        """Return hold-overlay progress copy, if this barrier publishes arrivals.

        ``counts`` are :meth:`_hold_message_counts` for ``participant`` when
        the caller already has them.
        """
        return None

    def _hold_message_counts(self, participant):
        """Return extra arguments for a ``waiting_message`` function; groups add their counts."""
        return {}

    def expected_release_time(self, participant) -> Optional[float]:
        """Return when this participant will be released at the latest, in epoch seconds.

        Used for the ``{SECONDS}`` countdown in ``waiting_message``. ``None`` (default)
        means the release time is unknown.
        """
        return None

    def _shows_countdown(self) -> bool:
        """Return whether this barrier can have a release time for ``{SECONDS}``."""
        return type(self).expected_release_time is not Barrier.expected_release_time

    def _participant_is_waiting(self, participant):
        """Return whether this participant is still waiting at this barrier."""
        link = participant.active_barriers.get(self.id)
        return link is not None and not bool(link.released)

    def release(self, participant: Participant):
        link = participant.active_barriers.get(self.id, None)
        if link is None:
            raise RuntimeError(
                "Could not find an appropriate barrier link to release the participant from "
                f"(participant_id = {participant.id}, barrier_id = '{self.id}')."
            )
        link.release()

    def can_participant_exit(self, participant: "Participant"):
        """Return whether the participant may leave ``waiting_logic``.

        Checks the ``released`` flag, because a link released earlier in
        the same request stays in ``active_barriers`` until it expires.
        """
        return not self._participant_is_waiting(participant)

    def waiting_pool_group(self, participant) -> Optional["SyncGroup"]:
        """Return the group whose members wait together at this barrier, or ``None``.

        Each group gets its own waiting pool, with its own lock, so a busy
        member of one group never delays another group's release. ``None``
        (default) puts everyone in one pool.
        """
        return None

    def get_waiting_participants(self, participant=None, *, for_update: bool = False):
        """Return people currently waiting at this barrier visit.

        Pass ``participant`` to scope the list to that person's instance.
        Without one, this lists the pool of participants whose
        :meth:`waiting_pool_group` is ``None``. Grouped barriers require a participant; see
        :meth:`GroupBarrier.get_waiting_participants`. This listing does
        not take extra row locks unless ``for_update`` is true.

        Parameters
        ----------
        participant
            A waiter whose ``active_barriers`` link identifies the visit.
            Must be a participant, not a boolean; ``for_update`` is
            keyword-only.
        for_update
            Lock the waiter rows until the current transaction ends.

        Returns
        -------
        list of Participant
            Active, unreleased waiters at this visit.
        """
        if isinstance(participant, bool):
            raise TypeError(
                "get_waiting_participants() takes a Participant as the first "
                "argument; pass for_update as a keyword."
            )
        if participant is not None:
            link = participant.active_barriers.get(self.id)
            if link is None:
                return []
            instance_id = link.barrier_instance_id
        else:
            instance = BarrierInstance._active_instance(self.id, None)
            instance_id = None if instance is None else instance.id
        if instance_id is None:
            return []
        return _get_waiting_participants(
            self.id,
            instance_id,
            for_update=for_update,
            nowait=False,
        )

    def check_waiting_participants(self, waiting_participants: List[Participant]):
        """Run any side-effecting checks before deciding who to release.

        Runs on the reconstructed registry barrier during evaluation.
        """

    def _check_instance(self, barrier_instance_id: str):
        """Lock waiters, release whoever is ready, and return the locked waiters.

        Runs on the reconstructed registry barrier. An inactive leftover with
        waiters is moved onto the live pool before release runs, so those
        people join the active visit instead of stealing its unique index.
        Last-arrival keeps ``instance.active``, so looking for that other
        pool stays off the budgeted path.

        Released hold waiters are queued so partner row locks drop at the
        check commit. The poller then skip-advances waiters **it** released;
        last-arrival drains that queue without moving partner cursors.

        Returns
        -------
        list of Participant
            Participants locked for this check, including people who were not
            released. Last-arrival handling uses this to drop partner row locks
            before the rest of the HTTP request continues.
        """
        waiting_participants = _get_waiting_participants(
            self.id,
            barrier_instance_id,
            for_update=True,
            nowait=True,
        )
        waiting_participants.sort(key=lambda p: p.id)

        logger.debug(
            "Barrier '%s' currently has %i participant(s) waiting",
            self.id,
            len(waiting_participants),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Barrier '%s' waiting participant ids: %s",
                self.id,
                ", ".join([str(p.id) for p in waiting_participants]),
            )

        instance = BarrierInstance.query.get(barrier_instance_id)
        other = self._other_active_pool(instance)
        if other is not None:
            self._migrate_leftover_waiters(waiting_participants, other)
            instance.active = False
            db.session.flush()
            live = other.get_barrier()
            if not isinstance(live, Barrier):
                raise RuntimeError(
                    f"Barrier instance '{other.id}' is missing or invalid."
                )
            return live._check_instance(other.id)
        return self._release_ready_waiters(waiting_participants, instance)

    def _other_active_pool(self, instance):
        """Return the live visit that an inactive leftover must not steal.

        Last-arrival keeps ``instance.active`` true, so this lookup stays off
        that budgeted path.
        """
        if instance is None or instance.active:
            return None
        other = BarrierInstance._active_instance(instance.barrier_id, instance.group_id)
        if other is not None and other.id != instance.id:
            return other
        return None

    def _migrate_leftover_waiters(self, waiting_participants, other):
        """Move unreleased leftover waiters onto the live pool."""
        for participant in waiting_participants:
            link = participant.active_barriers.get(self.id)
            if link is None or link.released:
                continue
            if link.barrier_instance_id == other.id:
                continue
            link.barrier_instance_id = other.id

    def _release_ready_waiters(self, waiting_participants, instance):
        """Release whoever is ready and record whether the visit still waits."""
        self.check_waiting_participants(waiting_participants)
        participants_to_release = self.choose_who_to_release(waiting_participants)
        participants_to_release.sort(key=lambda p: p.id)

        if len(participants_to_release) > 0:
            logger.info(
                "Barrier '%s' is releasing %i participant(s) (ids = %s)",
                self.id,
                len(participants_to_release),
                ", ".join([str(p.id) for p in participants_to_release]),
            )

            for participant in participants_to_release:
                self.release(participant)
            _queue_released_hold_waiters(participants_to_release)
        if instance is not None:
            instance.active = any(
                not participant.active_barriers[self.id].released
                for participant in waiting_participants
                if self.id in participant.active_barriers
            )
            if not waiting_participants and not instance.active:
                # A locking SELECT can miss waiters that ``EXISTS`` still
                # sees. Do not mark the visit finished from that snapshot.
                instance.active = _barrier_instance_has_waiters(instance)
        return waiting_participants


def _advance_released_hold_waiters_after_commit(participant_ids):
    """Skip waiters this request just released, after their row locks drop.

    The 0.5 s poller uses this for visits **it** released. Last-arrival does
    not skip partner cursors; those partners leave on overlay wake. The
    waiter's later hold-resume POST still carries the hold page's uuid;
    ``process_response`` treats that as an in-place catch-up.

    Each waiter is locked alone so a partner ``GET /timeline`` or overlay
    POST can take ``FOR UPDATE`` on itself. ``NOWAIT`` skips a waiter whose
    own request already holds the row.
    """
    from .experiment import get_experiment

    if not participant_ids:
        return
    experiment = get_experiment()
    ids = list(participant_ids)
    for index, participant_id in enumerate(ids):
        remaining = ids[index + 1 :]
        try:
            _set_transaction_lock_timeout(
                get_config().get("timeline_lock_timeout_seconds")
            )
            participant = _lock_and_load_participant(
                experiment._participant_request_query(), participant_id, nowait=True
            )
        except Exception as err:
            _rollback_preserving_barrier_queues()
            if is_transient_transaction_error(err):
                logger.debug(
                    "Released waiter %s is advancing in another request.",
                    participant_id,
                )
                continue
            logger.exception(
                "Released-hold skip failed for waiter %s; remaining waiters %s "
                "will recover through overlay wake.",
                participant_id,
                remaining,
            )
            raise
        if participant is None:
            _rollback_preserving_barrier_queues()
            continue
        try:
            page = experiment.timeline.get_current_elt(experiment, participant)
            if _is_timeline_hold(page):
                experiment._advance_past_ready_holds(participant, page)
            db.session.commit()
        except Exception:
            _rollback_preserving_barrier_queues()
            logger.exception(
                "Released-hold skip failed for waiter %s; remaining waiters %s "
                "will recover through overlay wake.",
                participant_id,
                remaining,
            )
            raise


def _group_barrier_outcome(
    group, members, waiting_ids, barrier_id, admissible=(), admission_point=False
):
    """Return ``"dissolve"``, ``"release"`` or ``"wait"`` for one visit of ``group``.

    Read-only: ``GroupBarrier.would_release`` passes the members it projects will
    remain, and ``choose_who_to_release`` the live ones, so the peek and the
    real release share one decision. ``members`` (admitted) and
    ``admissible`` (pending members this admission point would admit) count
    towards the quorum, and the visit releases once all ``members`` are
    waiting. In a group that admits newcomers at admission points, only an
    admission point waits for newcomers, below the quorum or the
    ``target_group_size``.
    """
    candidates = [*members, *admissible]
    newcomers_can_help = group.accepts_top_ups and (
        admission_point or not group.uses_admission_points
    )
    if len(candidates) < (group.quorum or 1):
        waits_for_top_ups = newcomers_can_help and not _top_up_wait_over(
            group, candidates, barrier_id
        )
        return "wait" if waits_for_top_ups else "dissolve"
    if not all(p.id in waiting_ids for p in members):
        return "wait"
    if (
        newcomers_can_help
        and group.target_group_size is not None
        and len(candidates) < group.target_group_size
        and not _top_up_wait_over(group, candidates, barrier_id, below_target=True)
    ):
        return "wait"
    return "release"


#: Longest a newcomer's own request waits for a busy group's row before
#: waiting at the grouper for the barrier poller instead.
_JOIN_LOCK_WAIT_SECONDS = 1


def _lock_sync_group(
    group_id, *, session=None, skip_locked=False, nowait=False, wait_seconds=None
) -> Optional["SyncGroup"]:
    """Lock a sync group's row ``FOR NO KEY UPDATE`` and reload it, with its member links.

    ``populate_existing`` also reloads the member links this session has
    loaded, so they include members who joined or left in other requests.
    See the lock order in :doc:`/developer/synchronization_internals`.

    Parameters
    ----------
    group_id
        The group to lock.
    session
        The session to lock it in, by default ``db.session``.
    skip_locked
        Return ``None`` instead of waiting if another transaction holds the row.
    nowait
        Raise PostgreSQL's ``55P03`` (lock not available) instead of waiting.
    wait_seconds
        Wait at most this long, in a savepoint, then return ``None`` with
        the transaction intact; a deadlock also returns ``None``.

    Returns
    -------
    SyncGroup or None
        The locked group, or ``None`` if it doesn't exist or stayed busy.
    """
    if session is None:
        session = db.session
    query = (
        session.query(SyncGroup)
        .filter_by(id=group_id)
        .with_for_update(
            of=SyncGroup, key_share=True, skip_locked=skip_locked, nowait=nowait
        )
        .populate_existing()
    )
    if wait_seconds is None:
        return query.first()
    try:
        with _lock_timeout(wait_seconds, session=session):
            return query.first()
    except Exception as err:
        if not is_transient_transaction_error(err):
            raise
        logger.debug("Sync group %s stayed busy for %s s.", group_id, wait_seconds)
        return None


#: What a :class:`GroupBarrier` does with a member who is late reaching it; see ``late_action``.
LateAction = Literal["fail", "leave_group"]


_BARRIER_RELEASE_CANDIDATE_OPTIONS = {
    "content": "it was renamed waiting_message",
}

_GROUP_BARRIER_RELEASE_CANDIDATE_OPTIONS = {
    "notify_arrivals": (
        "pass on_arrival_message=None to turn arrival notices off, or leave it "
        "out to keep them"
    ),
    "timeout_between_barriers_time": "it was renamed late_after",
    "timeout_between_barriers_action": (
        "it was renamed late_action, which late_after now requires"
    ),
}

_TRIAL_MAKER_RELEASE_CANDIDATE_OPTIONS = {
    "sync_group_timeout_between_barriers_time": "it was renamed sync_group_late_after",
    "sync_group_timeout_between_barriers_action": (
        "it was renamed sync_group_late_action, which sync_group_late_after "
        "now requires"
    ),
    "sync_group_wait_content": "it was renamed sync_group_waiting_message",
}


def _reject_release_candidate_options(owner, kwargs, replacements):
    """Raise a ``TypeError`` naming the replacement for an option of the PsyNet 14.0 release candidates.

    Parameters
    ----------
    owner
        Name of the class the options were passed to.
    kwargs
        The keyword arguments passed.
    replacements
        Maps each retired option name to a description of its replacement.
    """
    for name, replacement in replacements.items():
        if name in kwargs:
            raise TypeError(
                f"{owner} no longer takes {name} (from the PsyNet 14.0 release "
                f"candidates): {replacement}."
            )


def _validate_admission_options(
    admission_point, newcomer_max_wait, newcomer_page, *, requires_max_wait=True
):
    """Check a GroupBarrier's admission-point options."""
    if not admission_point:
        for name, value in [
            ("newcomer_max_wait", newcomer_max_wait),
            ("newcomer_page", newcomer_page),
        ]:
            if value is not None:
                raise ValueError(f"{name} is only used with admission_point=True.")
        return
    if newcomer_max_wait is None and requires_max_wait:
        raise ValueError(
            "admission_point=True needs newcomer_max_wait: the longest a pending "
            "member may wait for this admission point, in seconds from joining "
            "the group, before they are turned away."
        )
    if newcomer_max_wait is not None and newcomer_max_wait <= 0:
        raise ValueError(
            f"newcomer_max_wait must be positive, got {newcomer_max_wait}."
        )
    if newcomer_page is not None and callable(newcomer_page):
        raise TypeError(
            "newcomer_page takes a page or other timeline logic, not a function; "
            "wrap a function that makes a page in PageMaker."
        )


def _validate_group_timeouts(
    max_wait_action,
    late_after,
    late_action,
    also_leave=None,
    group_type=None,
    prefix="",
):
    """Check a GroupBarrier's time-out options, naming them with ``prefix`` (e.g. ``"sync_group_"``)."""
    for name, value, allowed in [
        ("max_wait_action", max_wait_action, ("fail", "leave_group")),
        ("late_action", late_action, (None, *get_args(LateAction))),
    ]:
        name = prefix + name
        if value == "kick":
            raise ValueError(f"{name}='kick' was renamed {name}='leave_group'.")
        if value not in allowed:
            allowed = [option for option in allowed if option is not None]
            raise ValueError(
                f"{name} must be one of {', '.join(map(repr, allowed))}, got {value!r}."
            )
    if late_after is not None and late_after <= 0:
        raise ValueError(f"{prefix}late_after must be positive.")
    if late_after is not None and late_action is None:
        raise ValueError(
            f"Pass {prefix}late_action with {prefix}late_after: 'fail' fails a "
            "late member and sends them to the end of the experiment, and "
            "'leave_group' removes them from the group so the others go on "
            "without them."
        )
    if late_after is not None and max_wait_action != "fail":
        raise ValueError(
            f"{prefix}max_wait_action has no effect with {prefix}late_after, which "
            f"leaves no wait limit; use {prefix}late_action instead."
        )
    if not also_leave:
        return
    if late_action != "leave_group":
        raise ValueError(
            f"{prefix}also_leave only takes effect with "
            f"{prefix}late_action='leave_group'."
        )
    if not isinstance(also_leave, (list, tuple)) or not all(
        isinstance(other, str) for other in also_leave
    ):
        raise ValueError(
            f"{prefix}also_leave must be a list of group types, got {also_leave!r}."
        )
    if group_type in also_leave:
        raise ValueError(
            f"{prefix}also_leave lists the barrier's own group type "
            f"{group_type!r}, which a late member leaves anyway."
        )
    if len(set(also_leave)) < len(also_leave):
        raise ValueError(
            f"{prefix}also_leave lists a group type more than once: {also_leave!r}."
        )


def _group_max_wait_time(max_wait_time, late_after, default, prefix=""):
    """Return the ``max_wait_time`` to use: ``default`` if not passed, or no limit with ``late_after``.

    ``late_after`` moves slow members on. A limit on the members waiting for
    them, fixed when each arrives, could not know how long a slower member's
    timed page still runs, so it is rejected rather than risk timing out
    members who were on time.
    """
    if late_after is None:
        return default if max_wait_time is NoArgumentProvided else max_wait_time
    if max_wait_time is not NoArgumentProvided and max_wait_time is not None:
        raise ValueError(
            f"Leave {prefix}max_wait_time unset with {prefix}late_after: "
            f"{prefix}late_action moves late members on, and a limit on the "
            "members waiting for them could time them out while a slower "
            "member's timed page is still running."
        )
    return None


#: Why a member left a group, see :meth:`SyncGroup.remove_participant`.
RemovalReason = Literal[
    "removed_by_experimenter",
    "left_experiment",
    "late",
    "waited_too_long",
    "group_dissolved",
    "moved_on",
    "finished",
    "not_admitted",
]
REMOVAL_REASONS = get_args(RemovalReason)

#: Values of :attr:`~psynet.trial.main.Trial.sync_group_outcome` other than
#: ``None``: ``"stayed"`` once a barrier in the trial's pages releases the
#: group with the player in it, after which it doesn't change; before that,
#: the :data:`RemovalReason` they left with.
SyncGroupOutcome = Literal["stayed", RemovalReason]
# Reasons for leaving that don't dissolve a group below its quorum.
_KEEPS_GROUP_REASONS = ("finished", "moved_on")

_OLD_BELOW_QUORUM_NAMES = (
    "fail_participants_below_min_size",
    "fail_participants_below_quorum",
)


def _reject_old_below_quorum_names(kwargs):
    """Point a grouper given a 14.0 release-candidate name to ``below_quorum``."""
    for old in _OLD_BELOW_QUORUM_NAMES:
        if old in kwargs:
            raise TypeError(
                f"{old} was replaced by below_quorum: pass "
                f"below_quorum='continue_without_group' instead of {old}=False."
            )


def _removed_from_group(participant, group_type) -> bool:
    """Return whether the participant is in no group of ``group_type`` but left one, or a grouper let them continue without one."""
    if group_type in participant.active_sync_groups:
        return False
    if group_type in (getattr(participant, "ungrouped_group_types", None) or []):
        return True
    latest = _latest_sync_group_link(participant, group_type)
    return latest is not None and not latest.active


def _latest_sync_group_link(participant, group_type):
    """Return the participant's newest link to a group of ``group_type``, or ``None``."""
    links = [
        link
        for link in participant.sync_group_links
        if link.sync_group.group_type == group_type
    ]
    if not links:
        return None
    return max(links, key=lambda link: (link.id is None, link.id or 0))


class GroupBarrier(Barrier):
    """
    A GroupBarrier is a Barrier that waits until all participants in a given :class:`~psynet.sync.SyncGroup`
    have reached the Barrier. It also checks the group against its ``quorum``: a group below it
    can't proceed, and waits for newcomers or is dissolved (see :ref:`groups_below_quorum`).

    It waits for every active member of the group, wherever they are in the
    timeline, until they leave the group: with :func:`leave_group`,
    ``late_action`` or ``max_wait_action``, or by failing or finishing the
    experiment. So a member whose part ends before the group's, such as at
    the end of a loop that runs a different number of times for each member,
    must leave the group there (see :ref:`sync-leaving-a-group`). When every
    member it releases is inside the same round's trial of a
    :meth:`~psynet.trial.main.Trial.cue` with ``sync_group_type``, that is,
    at a barrier in ``show_trial``, the release closes that round to
    newcomers, whose cues then start the next round. If every member is
    waiting but at different barriers of the group, none of them can ever
    pass: PsyNet records and logs an error naming the barriers, bot tests
    fail with it, and ``late_after`` or ``max_wait_time`` ends the wait (see
    :ref:`members at different barriers <rounds-group-barriers-in-loops>`).

    After the arrival write commits, the same request evaluates the barrier in
    a short transaction so partners are released without waiting for the 0.5 s
    poller. On the default hold path that arriver then skips their own wait
    indicator. Partners leave on overlay wake; the poller skips waiters only
    when it won the release.
    ``on_release`` receives the reconstructed registry barrier; see
    :class:`Barrier` for the live-versus-reconstructed method split.

    A participant who was removed from their group of ``group_type``, for example by a timeout with ``"leave_group"``,
    and is in no other group of that type passes straight through, as does one whose grouper let them
    continue without a group (``max_wait_action="continue_without_group"``). Any other participant who
    was never in such a group gets an error, which usually means a grouper is missing from the timeline.

    Parameters
    ----------

    id_
        ID parameter for the Barrier. Barriers with the same ID share waiting areas; this allows participants
        at different points in the timeline to share the same waiting areas.

    group_type
        Identifies the kind of groups that the Barrier is operating over (see :class:`~psynet.sync.Grouper`).

    waiting_logic
        Either a single timeline element or a list of timeline elements (created by ``join``) that is to be displayed
        to the participant while they are waiting at the barrier, for
        example filler trials. If left at ``None``, the participant sees
        ``waiting_screen``, or their current page beneath a lightweight
        waiting indicator. Pass ``waiting_message`` to customize that indicator's
        message. See :class:`Barrier` for where ``waiting_logic`` can go.

    waiting_logic_expected_repetitions
        Deprecated; pass ``expected_wait`` instead. Expected repetitions of
        ``waiting_logic``.

    max_wait_time
        Acts on members waiting at this barrier: the longest each may wait, in seconds, counted from
        their arrival, before ``max_wait_action`` is applied to them. Defaults to 20 seconds, or to no limit
        with ``late_after``, which then moves slow members on; passing a number or a function together with
        ``late_after`` raises an error, because a limit fixed at each arrival can't know how long a slower
        member's timed page still runs, and could time out the members who were on time before
        ``late_after`` frees them. ``None`` means no limit. May also be a function of ``participant``,
        evaluated once when they arrive.
        This is a hard limit counted from arrival: with explicit ``waiting_logic``, the server applies it
        even while the participant is partway through a filler page, so make it long enough to cover long
        filler pages (for example trials used as filler).

    max_wait_action
        What happens to a member who waits longer than ``max_wait_time``. Either way they first leave the
        group, which records ``"waited_too_long"`` as their removal reason and, unless a release has
        already made it ``"stayed"``, the ``sync_group_outcome`` of their trial in the group's round. ``"fail"`` (default) then fails them, after they leave their other groups as
        ``"left_experiment"``, and sends them to the end of the experiment; with ``"leave_group"`` they carry on with the
        experiment without the group (see :ref:`sync-leaving-a-group`).
        With ``"leave_group"``, their next page says "Your partner didn't arrive in time. Please continue." in a pair (see
        ``on_arrival_message`` for larger groups); for how a :class:`~psynet.group_prompt.GroupPrompt`
        shows them, see :ref:`sync-showing-the-group`. It is the waiting member who leaves, not the absent ones; to move on
        without slow members, use ``late_after`` and ``late_action`` instead. If that takes
        the group below its quorum, see :ref:`groups_below_quorum` for whether it
        is dissolved.

    late_after
        Acts on members who haven't reached this barrier yet: the longest each may take to reach it, in seconds,
        counted from the group's previous barrier pass or from when the group admitted them, whichever is later,
        before ``late_action`` is applied to them; pending members are never late, and nobody is late while
        only pending members wait here. ``None`` (default) never treats anyone as late. A member on a
        page with a ``time_limit`` is never late before that limit has run out plus 10 seconds, so that an
        answer sent at the deadline can arrive; this timeout therefore need not cover the pages' time limits.
        The same holds for a page whose :meth:`~psynet.timeline.Page.ends_by` says when it ends at the
        latest, such as a live session's game page.
        Requires ``late_action``, and the grouper of ``group_type`` (and of each type in ``also_leave``)
        must then be given ``below_quorum``, which is checked when the experiment loads.

    late_action
        What happens to a member who is later than ``late_after``, which requires it: ``"fail"`` fails them
        and sends them to the end of the experiment; ``"leave_group"`` removes them from the group, so the
        rest can go on without them (see :ref:`sync-leaving-a-group` for what the removed member sees).
        ``"leave_group"`` can't be combined with a grouper's ``below_quorum="fail"``, which would fail the
        members who were on time while the late one carries on; the experiment raises an error at load, or
        when a trial shows a barrier built in ``show_trial``.
        With every action the member leaves this
        barrier's group with the reason ``"late"`` (with ``"fail"``, before they are failed), which their
        trial in the group's round records in :attr:`~psynet.trial.main.Trial.sync_group_outcome` unless an earlier barrier
        in the trial's pages already released the group with them in it (then it stays ``"stayed"``). A
        group without top-ups that this leaves below
        its quorum dissolves as its ``below_quorum`` says, so with ``late_action="fail"`` and
        ``below_quorum="fail"`` one late member can fail a whole cohort (see :ref:`groups_below_quorum`
        for groups that accept top-ups). Removal is all or nothing: while a late member's own request is in
        progress, for example submitting a page, no late member of the group is acted on until a check
        finds none of them busy, usually the next one, so the removal can come a check later; if that request
        brought them to this barrier, they are no longer late. So code a late member runs in their own
        request, such as a :class:`~psynet.timeline.CodeBlock` storing their answer, either runs before the
        removal or sees it (``participant.sync_group_removal_reason``, or, before the round's first
        release, their trial's :attr:`~psynet.trial.main.Trial.sync_group_outcome`).

    also_leave
        With ``late_action="leave_group"``, the other group types a late member also leaves, with the
        reason ``"late"``, for example ``["cohort"]`` for the cohort a pair was formed in, so that the
        cohort doesn't wait for them either. Their groups of other types keep them. ``None`` (default)
        leaves only this barrier's group.

    on_release
        Optional callback invoked when the barrier releases the group. It may take
        ``group``, ``participants`` (the members it releases: the group's
        active members), ``trials``
        (each member's ``current_trial``, in the same order as ``participants``,
        for example the trials of a :meth:`~psynet.trial.main.Trial.cue` with
        ``sync_group_type`` that the barrier is part of), ``group_round`` (the
        :class:`SyncGroupRound` whose trial every released member is in, or
        ``None``; see :ref:`the barrier's round <sync-barrier-round>`), ``leader`` (the
        group's leader), ``participant`` (the same object as ``leader``, kept for
        compatibility), ``left`` (the members who left the group since its
        previous barrier pass, or since it formed; see below), ``admitted``
        (the pending members an admission point admits with this release; see
        :ref:`sync-admission-points`) and ``barrier``,
        the reconstructed registry object for this
        visit (scalar presentation and notification settings, not wait pages).
        ``participant.sync_group_removal_reason(group_type)`` says why each
        member in ``left`` went, for example to tell a player whose partner
        returned the study apart from one whose partner was too slow::

            def score_round(participants, left, barrier):
                for participant in left:
                    reason = participant.sync_group_removal_reason("pair")
                    ...

        Must be a module-level function, ``@staticmethod``/``@classmethod``,
        or a bound method on a TrialMaker or ORM instance with a primary key.
        To share one callback between several barriers, give each its own
        arguments with :func:`functools.partial`, passed by keyword and
        JSON-compatible, for example the number of the question the barrier
        ends::

            def score_question(group, question):
                ...

            GroupBarrier(id_="question_1", group_type="team",
                         on_release=partial(score_question, question=1))

        Barriers that share an ``id_`` must pass the same arguments.

    stop_top_ups
        If ``True``, the group stops accepting newcomers once it passes this
        barrier, as :meth:`SimpleSyncGroup.stop_top_ups` does, for example at
        the barrier that starts a game, so nobody joins it once it is under way.
        Only affects groups formed with ``join_existing_groups=True``. A group
        below its quorum doesn't pass, so it keeps waiting here for a newcomer,
        up to the grouper's ``top_up_wait``, if set (see :ref:`groups_below_quorum`).
        A group whose grouper has ``use_admission_points=True`` waits only if
        this barrier is an admission point; otherwise it is dissolved. Pending members are turned away as ``"not_admitted"``; at an admission
        point, those waiting here are admitted first.

    admission_point
        If ``True``, this barrier admits the group's pending members (see
        ``SimpleGrouper(use_admission_points=True)``): they wait
        here, and its release admits them, in the order they joined, together
        with the group, which counts them towards its ``quorum`` and waits up
        to ``top_up_wait`` for newcomers while it has fewer members than the
        grouper's ``target_group_size``. Pending members pass every other
        barrier straight through. Put it where a newcomer can sensibly start,
        such as the start of a round or generation. See
        :ref:`sync-admission-points`.

    newcomer_max_wait
        Required with ``admission_point=True``: the longest a pending member
        may wait for this admission point, in seconds, counted from when they
        joined the group. It replaces ``max_wait_time`` for them. Once it runs
        out they are turned away: they leave the group as ``"not_admitted"``,
        are never failed, carry on past the group's barriers like any member
        who left it, and see the ``on_arrival_message`` notice of kind
        ``"not_admitted"`` on their next page.

    newcomer_page
        Optional page, page maker or list of timeline elements shown right
        after this admission point only to the members it just admitted, for
        example a summary of the group's history.

    fix_time_credit
        If set to ``True``, award fixed expected time credit. Otherwise default
        holds credit actual visible waiting time up to ``max_wait_time``.

    expected_wait
        See :class:`Barrier`.

    waiting_message
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. If omitted, participants see
        "Waiting for other participants…". Plain strings are shown as text;
        pass ``markupsafe.Markup`` or a dominate tag for HTML, or a
        module-level function ``waiting_message(participant)`` returning either (see
        :class:`Barrier`). Independent of
        a preceding :class:`~psynet.sync.Grouper`'s ``waiting_message`` and of
        trial-maker ``sync_group_waiting_message``.

    release_grace
        See :class:`Barrier`. Default: 3 seconds.

    waiting_screen
        See :class:`Barrier`.

    on_arrival_message
        Callable that returns arrival copy for one participant, by default
        :func:`~psynet.timeline_hold.default_group_barrier_arrival_message`.
        It receives ``kind`` (``"notice"``, ``"late"``, ``"waited_too_long"`` or ``"not_admitted"``), ``waiting_count``,
        ``group_size``, and the usual context arguments (``participant``, the
        one who sees the copy, ``group``, ``barrier``, ``experiment``). Return ``None`` to hide that
        notice. Same serialization rules as ``on_release``. Pass
        ``on_arrival_message=None`` to turn off all of this barrier's arrival
        notices, including the not-ready count on the waiting indicator in
        groups of three or more. To change the waiting indicator's progress
        line instead, return :func:`hold_message` from a ``waiting_message``
        function.

        ``"notice"`` is the progress-bar notice for members who have not
        reached the barrier yet. It defaults to "Your partner is ready." in
        pairs and ``"{ARRIVED}/{TOTAL} of your group are ready."`` in larger
        groups. It is called whenever the participant's browser fetches its
        notice, which can be several times per arrival, so it should depend
        only on its arguments and have no side effects. Notices wrap onto at
        most two lines (overflow ellipsizes), so keep them to a short sentence.

        ``"late"`` is the progress-bar notice for someone removed by
        ``late_action="leave_group"``, shown until they leave
        their page. It defaults to "Your partner went on without you. Please
        continue." or "Your group went on without you. Please continue.", and
        ``group_size`` counts the group before anyone was removed.

        ``"waited_too_long"`` is the notice for someone removed by
        ``max_wait_action="leave_group"``, shown on the page they move on to. It
        defaults to "Your partner didn't arrive in time. Please continue." or
        "Not everyone in your group arrived in time. Please continue.".

        ``"not_admitted"`` is the notice for a pending member turned away
        before an admission point admitted them (see ``newcomer_max_wait``),
        shown on the page they move on to. It defaults to "We couldn't add
        you to a group in time. Please continue.".

        Check ``kind`` for each of these rather than treating everything
        that isn't ``"late"`` as a progress notice, or a removed member
        sees "Your partner is ready." after waiting too long.

    """

    def __init__(
        self,
        id_: str,
        group_type: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=None,
        max_wait_time: Optional[Union[float, Callable]] = NoArgumentProvided,
        on_release: Optional[Callable] = None,
        fix_time_credit=False,
        *,
        max_wait_action: Literal["fail", "leave_group"] = "fail",
        late_after: Optional[float] = None,
        late_action: Optional[LateAction] = None,
        also_leave: Optional[Sequence[str]] = None,
        expected_wait=None,
        waiting_message=None,
        on_arrival_message: Optional[Callable] = default_group_barrier_arrival_message,
        release_grace: Optional[float] = NoArgumentProvided,
        waiting_screen=None,
        stop_top_ups: bool = False,
        admission_point: bool = False,
        newcomer_max_wait: Optional[float] = None,
        newcomer_page=None,
    ):
        _validate_group_timeouts(
            max_wait_action, late_after, late_action, also_leave, group_type
        )
        _validate_admission_options(
            admission_point,
            newcomer_max_wait,
            newcomer_page,
            requires_max_wait=self._requires_newcomer_max_wait,
        )
        max_wait_time = _group_max_wait_time(max_wait_time, late_after, default=20)
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            fix_time_credit=fix_time_credit,
            expected_wait=expected_wait,
            waiting_message=waiting_message,
            release_grace=release_grace,
            waiting_screen=waiting_screen,
        )
        self.max_wait_action = max_wait_action
        self.group_type = group_type
        self.on_release = on_release
        self.on_arrival_message = on_arrival_message
        self.late_after = late_after
        self.late_action = late_action
        self.also_leave = list(also_leave or [])
        self.stop_top_ups = bool(stop_top_ups)
        self.admission_point = bool(admission_point)
        self.newcomer_max_wait = newcomer_max_wait
        self.newcomer_page = newcomer_page

    #: Whether ``admission_point=True`` needs ``newcomer_max_wait`` when
    #: constructed; a synchronized trial maker's barrier is checked at load
    #: (see :func:`check_admission_points`), which names the option and owner.
    _requires_newcomer_max_wait = True
    _newcomer_max_wait_option = "newcomer_max_wait"

    @property
    def _admission_point_owner(self) -> str:
        return f"GroupBarrier '{self.id}'"

    def __new__(cls, *args, **kwargs):
        _reject_release_candidate_options(
            cls.__name__, kwargs, _GROUP_BARRIER_RELEASE_CANDIDATE_OPTIONS
        )
        return super().__new__(cls, *args, **kwargs)

    def resolve(self):
        logic = conditional(
            f"barrier:{self.id}:in_group",
            condition=self._waits_here,
            logic_if_true=super().resolve(),
            logic_if_false=CodeBlock(_forget_time_out),
            log_chosen_branch=False,
        )
        if self.newcomer_page is None:
            return logic
        return join(
            logic,
            conditional(
                f"barrier:{self.id}:newcomer_page",
                condition=self._just_admitted,
                logic_if_true=self.newcomer_page,
                log_chosen_branch=False,
            ),
        )

    def _waits_here(self, participant) -> bool:
        """Return whether the participant waits here rather than passing straight through.

        Members who left the group pass, and so do pending members except at
        an admission point.
        """
        if _removed_from_group(participant, self.group_type):
            return False
        group = participant.active_sync_groups.get(self.group_type)
        return (
            self.admission_point or group is None or not group._is_pending(participant)
        )

    def _just_admitted(self, participant) -> bool:
        """Return whether the participant's latest visit here admitted them to the group."""
        if self.group_type not in participant.active_sync_groups:
            return False
        visit = (
            ParticipantLinkBarrier.query.filter_by(
                participant_id=participant.id, barrier_id=self.id
            )
            .order_by(ParticipantLinkBarrier.id.desc())
            .first()
        )
        return visit is not None and bool(visit.admitted)

    def _release_ready_waiters(self, waiting_participants, instance):
        """Check the waiters as usual, after locking their groups that accept top-ups.

        See :meth:`_lock_top_up_groups`.
        """
        self._lock_top_up_groups(waiting_participants)
        super()._release_ready_waiters(waiting_participants, instance)
        return waiting_participants

    def _max_wait_time_for(self, participant, experiment=None):
        """Return the participant's ``max_wait_time``, or for a pending member at an admission point, what is left of ``newcomer_max_wait``."""
        group = participant.active_sync_groups.get(self.group_type)
        if not (self.admission_point and group and group._is_pending(participant)):
            return super()._max_wait_time_for(participant, experiment)
        if self.newcomer_max_wait is None:
            return None
        joined = group._active_link(participant).arrival_time
        waited = (timenow() - joined).total_seconds()
        return max(self.newcomer_max_wait - waited, 0)

    #: GroupBarrier fails timed-out waiters itself, in
    #: :meth:`handle_max_wait_timeout`, which spares pending members.
    _fails_on_timeout = False

    def _lock_top_up_groups(self, waiting_participants):
        """Lock and reload the waiters' groups that accept top-ups, raising ``55P03`` if one is busy.

        Newcomers join under the same lock (see
        ``SimpleGrouper._claim_group_to_join``), so they join either before
        the check counts them or after it commits. Taken once per check,
        before :meth:`check_waiting_participants` and
        :meth:`choose_who_to_release`, so both see the same members. A busy
        group, perhaps with a newcomer joining, defers the whole check like a
        busy waiter does: the poller and the last arrival retry it.
        """
        for group in self.get_waiting_groups(waiting_participants).values():
            if group.accepts_top_ups:
                _lock_sync_group(group.id, nowait=True)

    def waiting_pool_group(self, participant) -> "SyncGroup":
        """Return the participant's group of ``group_type``; its members wait together."""
        group = participant.active_sync_groups.get(self.group_type)
        if group is None:
            raise RuntimeError(
                f"Participant {participant.id} is not in a sync group of type "
                f"'{self.group_type}' at barrier '{self.id}'. Check that a grouper "
                "of that type comes before the barrier, and after any GroupCloser "
                "that closed their group."
            )
        return group

    def get_waiting_participants(self, participant=None, *, for_update: bool = False):
        """Return people waiting at this group visit.

        Grouped barriers have no ungrouped pool, so ``participant`` is
        required to identify the visit. Use the visit link
        ``participant.active_barriers[...].get_waiting_participants()``
        when you already have it.
        """
        if participant is None:
            raise TypeError(
                "GroupBarrier.get_waiting_participants() needs a participant "
                "to identify the visit; use the visit link "
                "participant.active_barriers[...].get_waiting_participants()."
            )
        return super().get_waiting_participants(participant, for_update=for_update)

    def _hold_progress_text(self, participant, counts=None):
        """Return hold-overlay progress when arrival notices are enabled."""
        if self.on_arrival_message is None or not self._participant_is_waiting(
            participant
        ):
            return None
        if counts is None:
            counts = self._hold_message_counts(participant)
        if counts["group_size"] is None:
            return None
        return default_hold_progress(**counts)

    def _hold_message_counts(self, participant):
        """Return ``waiting_count`` and ``group_size``, both ``None`` without a group."""
        group = (
            None
            if participant is None
            else participant.active_sync_groups.get(self.group_type)
        )
        if group is None:
            return {"waiting_count": None, "group_size": None}
        members = group.active_participants
        return {
            "waiting_count": sum(self._participant_is_waiting(m) for m in members),
            "group_size": len(members),
        }

    def _call_arrival_message(self, **kwargs):
        """Return author or default arrival copy for one participant.

        Safe on reconstructed registry barriers.
        """
        callback = self.on_arrival_message
        if callback is None:
            return None
        return callback(barrier=self, **kwargs)

    def _notify_arrivals(self, arriving_participant):
        """Publish hold progress and partner-ready notices after an arrival.

        Live timeline only. Overlay HTML comes from ``waiting_logic``.
        """
        if self.on_arrival_message is None:
            return
        if arriving_participant.failed or not self._participant_is_waiting(
            arriving_participant
        ):
            return
        group = arriving_participant.active_sync_groups.get(self.group_type)
        if group is None:
            return
        members = group.active_participants
        waiting = [m for m in members if self._participant_is_waiting(m)]
        counts = {"waiting_count": len(waiting), "group_size": len(members)}
        # Pending members waiting here see the admitted members' progress too.
        pending_waiting = (
            [p for p in group.pending_participants if self._participant_is_waiting(p)]
            if self.admission_point
            else []
        )
        if self._uses_timeline_hold:
            _prime_timeline_hold_records(waiting + pending_waiting, self.id)
        # Arrivals in concurrent requests don't see each other, so the browser
        # fetches the notice and ready seats after the commit instead of being
        # sent the counts this request sees.
        for member in members + pending_waiting:
            if member.failed:
                continue
            if self._participant_is_waiting(member):
                hold_html = None
                if self._uses_timeline_hold:
                    hold_page = self.waiting_logic
                    if getattr(
                        hold_page, "_is_silent_for", None
                    ) and hold_page._is_silent_for(member):
                        continue
                    hold_html = hold_page.overlay_html(member, counts=counts)
                _queue_arrival_update(member.id, hold_message=hold_html, refresh=True)
                continue
            _queue_arrival_update(member.id, refresh=True)

    def handle_max_wait_timeout(self, participant: Participant):
        """Remove the waiter from the sync group as ``"waited_too_long"``, then release the barrier link.

        With ``max_wait_action="fail"`` the waiter also leaves their other
        groups as ``"left_experiment"`` and is failed as a timeout before any
        quorum is checked, as in :meth:`_remove_late_participants`, so a
        group dissolving cannot fail them for its own reason first.
        """
        group = participant.active_sync_groups.get(self.group_type)
        if group is not None and group._is_pending(participant):
            # Only reached at an admission point, after newcomer_max_wait.
            group._turn_away(participant, self)
            super().handle_max_wait_timeout(participant)
        elif group is None:
            hold = self._hold_kind(participant)
            super().handle_max_wait_timeout(participant)
            if self.max_wait_action == "fail" and not participant.failed:
                participant.append_failure_tags(
                    f"{hold}:barrier:{self.id}", "fail_on_timeout"
                )
                participant.fail()
        elif self.max_wait_action == "leave_group":
            group_size = len(group.active_participants)
            group.remove_participant(participant, reason="waited_too_long")
            self._tell_removed_participant(
                participant, group, group_size, kind="waited_too_long"
            )
            super().handle_max_wait_timeout(participant)
        else:
            hold = self._hold_kind(participant)
            left = _groups_left_on_failure(participant, group, "waited_too_long")
            for left_group, reason in left:
                left_group._remove_without_quorum_check(participant, reason)
            super().handle_max_wait_timeout(participant)
            logger.info(
                "GroupBarrier '%s': failing participant %s (waited too long)",
                self.id,
                participant.id,
            )
            participant.append_failure_tags(
                f"{hold}:barrier:{self.id}", "fail_on_timeout"
            )
            participant.fail()
            for left_group, _ in left:
                left_group.dissolve_if_below_quorum()

    def _hold_kind(self, participant) -> str:
        """Return ``"timeline_hold"`` or ``"while_loop"``: how the participant waits here."""
        # The poller's reconstructed barrier lacks _uses_timeline_hold.
        link = participant.active_barriers.get(self.id)
        on_hold = link is not None and link.timeline_hold is not None
        return "timeline_hold" if on_hold else "while_loop"

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        """Release each waiting group that is ready, and dissolve those that can't reach their quorum.

        Expects to run inside a barrier check, which has locked the waiters
        and their groups that accept top-ups; called directly, it counts the
        members this session has loaded and takes no such locks.
        """
        waiting_participant_ids = {p.id for p in waiting_participants}
        participants_to_release = []
        groups = self.get_waiting_groups(waiting_participants)

        for group in groups.values():
            group_round = _common_round(
                group, self._waiting_members(group, waiting_participants)
            )
            group.check_numbers()
            members = group.active_participants
            admissible = self._admissible(group, waiting_participant_ids)
            outcome = _group_barrier_outcome(
                group,
                members,
                waiting_participant_ids,
                self.id,
                admissible,
                self.admission_point,
            )

            if outcome == "dissolve":
                # The group can never reach its quorum, so remove everyone
                # and release whoever is waiting here, after the grouper's
                # below_quorum has failed or released each of them (or
                # nobody yet, if a member is busy; see _dissolve).
                if group.accepts_top_ups:
                    group._close_to_top_ups(self)
                participants_to_release.extend(
                    participant
                    for participant in group._dissolve()
                    if participant.id in waiting_participant_ids
                )
            elif outcome == "release":
                released = self._waiting_members(group, waiting_participants)
                if admissible:
                    group._admit(
                        admissible,
                        {p.id: p.active_barriers.get(self.id) for p in admissible},
                    )
                    released += admissible
                participants_to_release.extend(released)
                self._pass(group, released, group_round, admitted=admissible)

        participants_to_release_ids = {p.id for p in participants_to_release}
        for participant in waiting_participants:
            # Release participants who reached this barrier but no longer belong
            # to the sync group (e.g., max-wait removals or dissolution below quorum).
            if (
                self.group_type not in participant.active_sync_groups
                and participant.id not in participants_to_release_ids
            ):
                participants_to_release.append(participant)
                participants_to_release_ids.add(participant.id)

        return participants_to_release

    @staticmethod
    def _waiting_members(group, waiting_participants):
        """Return the admitted active members of ``group`` among ``waiting_participants``."""
        member_ids = {p.id for p in group.active_participants}
        return [p for p in waiting_participants if p.id in member_ids]

    def _admissible(self, group, waiting_ids) -> list:
        """Return the pending members of ``group`` that this barrier's release would admit, in join order.

        Members whose ``newcomer_max_wait`` has run out are left for
        :meth:`handle_max_wait_timeout` to turn away.
        """
        if not self.admission_point or not group.accepts_top_ups:
            return []
        return [
            p
            for p in group.pending_participants
            if p.id in waiting_ids and self._max_wait_time_for(p) != 0
        ]

    def _pass(self, group, released, group_round, admitted=()):
        """Do the group's bookkeeping for releasing ``released``.

        ``admitted`` are the members this admission point just admitted.
        Also closes ``group_round``, if any, and calls ``on_release``.
        """
        group.check_leader()
        left = group._members_who_left_since(
            group.last_barrier_pass_time or group.creation_time
        )
        group.last_barrier_pass_time = timenow()
        released_ids = {p.id for p in released}
        for link in group.participant_links:
            link.page_deadline = None
            if (
                self.admission_point
                and link.active
                and link.participant_id in released_ids
            ):
                link.admission_points_passed = (link.admission_points_passed or 0) + 1
        if self.stop_top_ups:
            group._stop_top_ups(self)

        trials = [p.current_trial for p in released]
        if group_round is not None:
            # Closes the round to newcomers: their cues start the next.
            group_round._close(
                [t for t in trials if t is not None and t.group_round is group_round]
            )
        if self.on_release:
            try:
                self.on_release(
                    group=group,
                    participants=released,
                    trials=trials,
                    group_round=group_round,
                    leader=group.leader,
                    participant=group.leader,
                    left=left,
                    admitted=list(admitted),
                    barrier=self,
                )
            except Exception as err:
                if is_transient_transaction_error(err):
                    raise
                raise _BarrierAuthorHookError(
                    f"Barrier '{self.id}' on_release failed."
                ) from err

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        """Return whether this group visit would release, without mutating state.

        Mirrors :meth:`check_waiting_participants` followed by
        :meth:`choose_who_to_release`: late members that the between-barrier
        timeout would remove or fail count as already gone, and group size is
        recounted rather than read from ``n_active_participants``.
        """
        waiting_ids = {participant.id for participant in waiting_participants}
        for group in self.get_waiting_groups(waiting_participants).values():
            if group.accepts_top_ups:
                # A peek takes no lock, but still counts newcomers who have
                # joined since this session loaded the group.
                db.session.expire(group, ["participant_links"])
            # Approximate: the check keeps a late member who is busy in their
            # own request. A wrong "yes" only makes this request wait for the
            # visit claim; the member is removed at a later sweep.
            late_ids = (
                {
                    participant.id
                    for participant in self._late_between_barriers(group, waiting_ids)
                }
                if self._waiting_members(group, waiting_participants)
                else set()
            )
            members = [
                participant
                for participant in group.active_participants
                if participant.id not in late_ids
            ]
            outcome = _group_barrier_outcome(
                group,
                members,
                waiting_ids,
                self.id,
                self._admissible(group, waiting_ids),
                self.admission_point,
            )
            if outcome != "wait":
                return True
        return any(
            self.group_type not in participant.active_sync_groups
            for participant in waiting_participants
        )

    def check_waiting_participants(self, waiting_participants: List[Participant]):
        """Remove members late between barriers; relies on the lock taken in :meth:`_lock_top_up_groups`."""
        waiting_ids = {p.id for p in waiting_participants}
        removals = []
        for group in self.get_waiting_groups(waiting_participants).values():
            group.check_numbers()
            if self.late_after is None:
                continue
            if not self._waiting_members(group, waiting_participants):
                # Only pending members wait here: the group hasn't reached
                # this barrier yet, so nobody is late for it.
                continue
            late = self._late_between_barriers(group, waiting_ids)
            if not late:
                continue
            # All or nothing: a late member busy in their own request must not
            # act on a removal that request can't see, and removing only the
            # free ones could dissolve the group around the busy one, who
            # would then leave with it rather than as late. All are late at
            # the next check.
            late = _lock_all_participants(late)
            if late is None:
                continue
            late = self._still_late(group, late, waiting_ids)
            if late:
                removals.append((group, late, len(group.active_participants)))
        self._remove_late_participants(removals)

    def get_waiting_groups(self, waiting_participants: List[Participant]):
        groups = {
            participant.active_sync_groups[
                self.group_type
            ].id: participant.active_sync_groups[self.group_type]
            for participant in waiting_participants
            if self.group_type in participant.active_sync_groups
        }
        return groups

    def _remove_late_participants(self, removals):
        """Remove late members from their groups, then dissolve the groups left below quorum.

        ``removals`` holds ``(group, late, group_size)`` for each group of this
        barrier with late members, ``group_size`` counted before the removal.
        Late members leave this barrier's group as ``"late"``, and their
        groups of the types in ``also_leave`` as ``"late"`` too; with
        ``late_action="fail"`` they leave all their other groups as
        ``"left_experiment"`` and are then failed. Every late member leaves
        those groups, and is failed, before any quorum is checked, so a group
        dissolving cannot dissolve or fail a late member who was about to
        leave it too.
        """
        fail = self.late_action == "fail"
        left = {}
        for group, late, _ in removals:
            for participant in late:
                if fail:
                    groups = _groups_left_on_failure(participant, group, "late")
                else:
                    active = participant.active_sync_groups
                    groups = [(group, "late")] + [
                        (active[group_type], "late")
                        for group_type in self.also_leave
                        if group_type in active
                    ]
                for left_group, reason in groups:
                    logger.info(
                        "GroupBarrier '%s': removing participant %s from group %s (timeout between barriers)",
                        self.id,
                        participant.id,
                        left_group.id,
                    )
                    left_group._remove_without_quorum_check(participant, reason)
                    left.setdefault(left_group.id, (left_group, []))[1].append(
                        participant
                    )
                if fail:
                    logger.info(
                        "GroupBarrier '%s': failing participant %s (timeout between barriers)",
                        self.id,
                        participant.id,
                    )
                    participant.fail("timeout between barriers")
        for left_group, leavers in left.values():
            self._dissolve_after_late_removal(left_group, leavers)
        if fail:
            return
        for group, late, group_size in removals:
            for participant in late:
                self._tell_removed_participant(participant, group, group_size)

    def _dissolve_after_late_removal(self, group, late):
        """Dissolve ``group`` if losing ``late`` left it below quorum, logging a warning if that fails the rest.

        The load-time and ``show_trial`` checks reject this combination; the
        warning covers barriers neither sees, such as those built in a
        ``for_loop``.
        """
        had_others = group.n_active_participants > 0
        group.dissolve_if_below_quorum()
        dissolves = group.n_active_participants == 0 or group.dissolving
        if (
            self.late_action != "fail"
            and had_others
            and dissolves
            and group.below_quorum != "continue_without_group"
        ):
            logger.warning(
                "GroupBarrier '%s': removing late members %s dissolves group %s "
                "(now, or once its members' requests finish), so its "
                "below_quorum='fail' fails its other members while the late ones "
                "carry on. Set "
                "below_quorum='continue_without_group' on the grouper to let them "
                "carry on too.",
                self.id,
                [p.id for p in late],
                group.id,
            )

    def _tell_removed_participant(self, participant, group, group_size, kind="late"):
        """Show a removed participant a notice that they left their group.

        A ``"late"`` notice lasts until they leave their current page;
        the late removal has locked their row, so their own request is not
        leaving that page meanwhile. A ``"waited_too_long"`` notice is shown on the page
        they move on to (see :meth:`psynet.timeline.Page.consume`). A failing
        message callback is logged rather than stopping the removal.
        """
        try:
            text = self._call_arrival_message(
                kind=kind,
                waiting_count=0,
                group_size=group_size,
                participant=participant,
                group=group,
            )
        except Exception as err:
            if is_transient_transaction_error(err):
                raise
            logger.exception(
                "GroupBarrier '%s': could not make the removal notice for participant %s.",
                self.id,
                participant.id,
            )
            return
        if not text:
            return
        if kind == "waited_too_long":
            _set_next_page_notice(participant, text)
            return
        text = str(text)
        participant.group_removal_notice = {
            "page_uuid": participant.page_uuid,
            "text": text,
        }
        _queue_arrival_update(participant.id, notice=text, removed=True)

    def _late_between_barriers(self, group: "SyncGroup", waiting_ids) -> list:
        """Return active members past the between-barrier timeout who are not waiting.

        Each admitted member is timed from the group's last barrier pass or
        from when they were admitted, whichever is later, so newcomers are
        not late as soon as they take part; pending members are never late. A
        member who has started a page with a time limit (or an ``ends_by``) since then, outside
        waiting logic, is not late until that limit has run out and an answer
        sent at the deadline has had time to arrive, even if they have
        already left the page.
        """
        if self.late_after is None:
            return []
        now = timenow()
        answer_arrival = timedelta(seconds=2 * TIME_LIMIT_GRACE_SECONDS)
        active_ids = {p.id for p in group.active_participants}
        late = []
        for link in group.participant_links:
            participant = link.participant
            if (
                not link.active
                or participant.id not in active_ids
                or participant.id in waiting_ids
            ):
                continue
            starts = [t for t in (group.last_barrier_pass_time, link.admitted_at) if t]
            if not starts:
                continue
            late_at = max(starts) + timedelta(seconds=self.late_after)
            if link.page_deadline is not None:
                late_at = max(late_at, link.page_deadline + answer_arrival)
            if now > late_at:
                late.append(participant)
        return late

    def _still_late(self, group, locked, waiting_ids) -> list:
        """Return the late members in ``locked`` who are still late now that their rows are locked.

        Lateness is first decided from state read before the rows were
        locked, and a member's own request may have committed since: they may
        have reached this barrier, or started a timed page.
        """
        locked_ids = {participant.id for participant in locked}
        for participant in locked:
            db.session.expire(participant, ["active_barriers"])
        for link in group.participant_links:
            if link.participant_id in locked_ids:
                db.session.refresh(link)
        arrived = {p.id for p in locked if self._participant_is_waiting(p)}
        late_ids = {
            participant.id
            for participant in self._late_between_barriers(group, waiting_ids | arrived)
        }
        return [participant for participant in locked if participant.id in late_ids]


class Grouper(Barrier):
    """
    A Grouper is a kind of Barrier that assigns incoming participants into groups.
    This is a generic class whose subclasses must override several methods, in particular
    ``ready_to_group`` and ``group``.

    Parameters
    ----------

    group_type
        A textual label for the groups that are created. This label is used to link the Grouper with
        subsequent GroupBarriers.

    id_
        Optional ID parameter for this grouper. If left blank the default value is ``group_type + "_" + "grouper"``.
        Groupers with the same ID are treated as equivalent and share the same participant waiting areas.

    waiting_logic
        Either a single timeline element or a list of timeline elements (created by ``join``) that is to be displayed
        to the participant while they are waiting at the barrier, for
        example filler trials. If left at ``None``, the participant sees
        ``waiting_screen``, or their current page beneath a lightweight
        waiting indicator. See :class:`Barrier` for where ``waiting_logic``
        can go.

    waiting_logic_expected_repetitions
        Deprecated; pass ``expected_wait`` instead. Expected repetitions of
        ``waiting_logic``.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded and the participant is still not released, then ``max_wait_action`` is
        applied to them. This is a hard limit counted from arrival: with explicit
        ``waiting_logic``, the server applies it even while the participant is partway through a filler page,
        so make it long enough to cover long filler pages (for example trials used as filler).

    max_wait_action
        What happens to a participant who waits longer than ``max_wait_time`` without being grouped:
        ``"fail"`` (default) fails them and sends them to the end of the experiment;
        ``"continue_without_group"`` lets them carry on with the experiment without a group, which suits a participant who was
        available but couldn't be matched. Their next page says "We couldn't find a partner for you in
        time. Please continue." (or "...a group for you..."). Later barriers and synchronized trial makers of
        this group type treat them as having left a group (see :ref:`sync-leaving-a-group`), and
        :meth:`~psynet.participant.Participant.sync_group_removal_reason` returns
        ``"no_group_formed"``. Branch on ``participant.in_sync_group(group_type)`` to give them
        something else to do or to end the experiment.

    expected_wait
        See :class:`Barrier`.

    waiting_message
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. Plain strings are shown as text; pass
        ``markupsafe.Markup`` or a dominate tag for HTML. This Grouper's
        overlay is independent of trial-maker ``sync_group_waiting_message``;
        pass ``waiting_message`` here and on later :class:`~psynet.sync.GroupBarrier`
        waits if they should match. Can be a function of ``seconds_left``, as
        for :class:`Barrier`.

    fix_time_credit
        If ``True``, award fixed ``expected_wait`` credit instead of actual
        visible waiting time.

    release_grace
        See :class:`Barrier`. Default: 3 seconds.

    waiting_screen
        See :class:`Barrier`.

    """

    def __init__(
        self,
        group_type: str,
        id_: Optional[str] = None,
        waiting_logic=None,
        waiting_logic_expected_repetitions=None,
        max_wait_time=20,
        expected_wait=None,
        fix_time_credit=False,
        waiting_message=None,
        release_grace: Optional[float] = NoArgumentProvided,
        waiting_screen=None,
        *,
        max_wait_action: Literal["fail", "continue_without_group"] = "fail",
    ):
        if max_wait_action not in ("fail", "continue_without_group"):
            hint = (
                " A grouper's participants aren't in a group yet, so use "
                "'continue_without_group'."
                if max_wait_action == "leave_group"
                else ""
            )
            raise ValueError(
                "A grouper's max_wait_action must be 'fail' or "
                f"'continue_without_group', got {max_wait_action!r}.{hint}"
            )
        if not id_:
            id_ = f"{group_type}_grouper"
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            expected_wait=expected_wait,
            fix_time_credit=fix_time_credit,
            waiting_message=waiting_message,
            release_grace=release_grace,
            waiting_screen=waiting_screen,
        )
        self.group_type = group_type
        self.max_wait_action = max_wait_action

    def handle_max_wait_timeout(self, participant: Participant):
        """Let an ungrouped participant carry on with ``"continue_without_group"``, then release the barrier link."""
        if (
            self.max_wait_action == "continue_without_group"
            and not participant.in_sync_group(self.group_type)
        ):
            participant.ungrouped_group_types = sorted(
                {*(participant.ungrouped_group_types or []), self.group_type}
            )
            group_size = getattr(self, "initial_group_size", None) or getattr(
                self, "group_size", None
            )
            _p = get_translator(context=True)
            text = (
                _p(
                    "timeline_hold",
                    "We couldn't find a partner for you in time. Please continue.",
                )
                if group_size == 2
                else _p(
                    "timeline_hold",
                    "We couldn't form a group for you in time. Please continue.",
                )
            )
            _set_next_page_notice(participant, text)
        super().handle_max_wait_timeout(participant)

    def ready_to_group(self, participants: List[Participant]) -> bool:
        """
        Determines whether the Grouper is ready to group a given collection of participants.
        Note that not all participants need to be grouped at once; it's permissible to
        leave some participants still waiting.

        Parameters
        ----------

        participants
            List of participants who are candidates for grouping.

        Returns
        -------

        ``True`` if the grouper is ready to group (some of) the participants, ``False`` otherwise.

        """
        raise NotImplementedError

    def group(self, participants: List[Participant]) -> List["SyncGroup"]:
        """
        This method is run if ``ready_to_group`` returns ``True``.
        It is responsible for grouping participants.

        Parameters
        ----------
        participants
            Participants who are candidates for grouping.

        Returns
        -------
        A list of SyncGroups who should be populated by the grouped participants.
        """
        raise NotImplementedError

    def receive_participant(self, participant: Participant):
        if self.group_type in participant.active_sync_groups:
            raise RuntimeError(
                f"Participant is already in a group with this group_type ('{self.group_type}'). "
                "You should close this group, typically by including a GroupCloser in the timeline, "
                "before reassigning it."
            )
        super().receive_participant(participant)

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        participants_to_release = []

        if self.ready_to_group(waiting_participants):
            groups = self.group(waiting_participants)

            if not isinstance(groups, list) and all(
                [isinstance(group, SyncGroup) for group in groups]
            ):
                raise ValueError("group() must return a list of SyncGroups.")

            for _group in groups:
                db.session.add(_group)
                for _participant in _group.participants:
                    participants_to_release.append(_participant)

        return participants_to_release

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        """Return whether this grouper would form groups, without creating them."""
        return bool(self.ready_to_group(waiting_participants))

    def _create_group(self, participants, **settings):
        """Create a ``SimpleSyncGroup`` of these participants, led by :meth:`select_leader`."""
        group = SimpleSyncGroup(
            group_type=self.group_type,
            n_active_participants=len(participants),
            active=True,
            grouper_id=self.id,
            **settings,
        )
        db.session.add(group)
        for participant in participants:
            group.add_participant(participant)
        group.leader = self.select_leader(participants)
        return group

    def select_leader(self, participants: List[Participant]) -> Participant:
        """
        By default the leader is randomly chosen from the list of available participants.

        Parameters
        ----------

        participants
            Participants to choose from.

        Returns
        -------

        A participant to be assigned 'leader' of the SyncGroup.

        """
        return random.choice(participants)


class SimpleGrouper(Grouper):
    """
    A Simple Grouper waits until ``batch_size`` many participants are waiting,
    and then randomly partitions this group of participants into groups of size ``initial_group_size``.

    Parameters
    ----------

    group_type
        A textual label for the groups that are created. This label is used to link the Grouper with
        subsequent GroupBarriers.

    initial_group_size
        Size of the groups to create. The default barrier ID is
        ``{group_type}_grouper_{initial_group_size}``, so sequential groupers
        of different sizes do not share a waiting pool. Pass ``id_`` only when
        two groupers should share one pool and have the same release behavior.

    max_group_size
        If ``join_existing_groups=True``, then participants will be allowed to join groups until
        they reach this maximum size. If set to ``"initial_group_size"`` (default),
        then the maximum size will be set to the initial group size.

    quorum
        How many active members a group needs to keep going. A group whose
        members fail or leave until it has fewer than this is below quorum; it
        then waits for newcomers or is dissolved (see :ref:`groups_below_quorum`).
        Defaults to ``start_short_with`` if given, and otherwise to
        ``initial_group_size``, so that a group needs all its members; for
        groups of three or more, leaving it out warns. Must be at most
        ``start_short_with`` when that is set.

    min_group_size
        Deprecated name for ``quorum``.

    batch_size
        Number of participants that should be waiting until the groups are created.
        If set to ``"initial_group_size"`` (default), then the batch size will be set to the initial group size.

    join_existing_groups
        If set to ``True``, then before a new group is created, the Grouper will check if there are any existing
        groups that aren't full (e.g. because some participants left the experiment early).
        If so, the arriving participant will be assigned to one of these groups instead.
        Participants already waiting at the grouper join such a group on the next barrier check.
        Groups that have closed or stopped accepting top-ups, and groups with no
        active members, are not joined. Groups keep accepting top-ups until you stop
        them (see :ref:`groups_below_quorum`).
        This behavior can be further customized via the ``join_criterion`` argument.
        Pass ``use_admission_points`` to say when such a newcomer starts taking part.

    use_admission_points
        When a newcomer who joins an existing group starts taking part in it.
        ``False`` admits them at once, so the group's next barrier waits
        for them, which suits groups that only take newcomers before play
        starts (for example in a lobby closed by ``stop_top_ups=True``).
        ``True`` makes them a pending member: they hold a
        seat, but barriers, the quorum, the leader and
        :class:`~psynet.group_prompt.GroupPrompt` ignore them until the
        group's next admission point (a ``GroupBarrier(admission_point=True)``,
        a synchronized trial maker's trial preparation, or a
        :class:`Regrouper` with ``within``) admits them; they pass its other
        barriers straight through. See :ref:`sync-admission-points`.
        Required with ``join_existing_groups=True``; leaving it out warns and
        uses ``False``.

    target_group_size
        With ``use_admission_points=True``, which requires it, how
        many members the group tries to have: an admission point that would
        leave it with fewer admitted members waits up to ``top_up_wait`` for
        newcomers (without a limit if ``top_up_wait`` is ``None``), then
        carries on with whoever is there as long as they meet the ``quorum``.
        Must be between ``quorum`` and ``max_group_size``; set it to the
        ``quorum`` to carry on without waiting.

    max_groups
        Optional cap on how many of this grouper's groups may be active at
        once. Once it is reached, participants wait at the grouper for a seat
        in an existing group instead of forming a new one, for example to run
        a single society that newcomers join one by one. ``None`` (default)
        has no cap.

    join_criterion
        A callable that takes ``group`` and ``participant`` as arguments, and returns ``True``
        if the participant should be allowed to join the group, and ``False`` otherwise.
        To be used in conjunction with ``join_existing_groups=True``. Returning ``False``
        only turns that newcomer away; the group keeps accepting top-ups (see
        :ref:`groups_below_quorum`).

    below_quorum
        What happens to the members left when a group is dissolved below its ``quorum``
        (for when that happens, see :ref:`groups_below_quorum`). The member whose departure caused it is handled by their own
        cause instead (a barrier's ``max_wait_action`` or ``late_action``, or their
        failure). ``"fail"`` fails them, telling them "Too few members of your
        group remained to continue, so we ended your session." ``"continue_without_group"``
        lets them carry on with the experiment without the group, and their next page says
        that their group ended (see :ref:`sync-leaving-a-group`). With ``"fail"``, one
        member who is late or leaves can end the session of everyone who was on time,
        as in a pair.
        Required when the groups are designed to shrink: when ``quorum`` is below
        ``initial_group_size``, or when a :class:`GroupBarrier` of this group type in the
        timeline has ``late_after`` (checked when the experiment loads). Otherwise it
        defaults to ``"fail"``. A barrier's ``late_action="leave_group"`` needs
        ``"continue_without_group"``.
        See :ref:`groups_below_quorum` for when the group is dissolved.

    top_up_wait
        With ``join_existing_groups=True``, how many seconds a group below its
        ``quorum`` waits for newcomers. Then the next check of the :class:`GroupBarrier`
        its members are waiting at stops top-ups and dissolves it; until all its
        remaining members have reached such a barrier, the group keeps accepting
        top-ups. The time counts from when the last of them arrived there, or from
        when the group fell below its quorum, if later. ``max_wait_time`` counts
        from each member's own arrival, so the first to arrive also waits for the
        others: give the barrier ``late_after``, which removes that limit, or a
        ``max_wait_time`` longer than ``top_up_wait`` plus the time members may
        take to reach it (see :ref:`groups_below_quorum`).
        Default: ``None``, waiting for newcomers without a limit. Required
        (checked when the experiment loads, or when a trial shows a barrier
        built in ``show_trial``) if the groups could wait for
        newcomers at a barrier with ``late_after``: any of the group type's
        such barriers with ``use_admission_points=False``, or its admission
        points with ``use_admission_points=True``, unless an earlier barrier has
        ``stop_top_ups=True``.

    start_short_after
        If set, a group may start with fewer than ``batch_size`` participants once the
        longest-waiting participant has waited this many seconds and at least
        ``start_short_with`` participants are waiting. If fewer than ``initial_group_size``
        are waiting, they form one smaller group. Requires ``quorum`` or
        ``start_short_with``, and a ``max_wait_time`` longer than
        ``start_short_after`` (not checked when ``max_wait_time`` is a function).
        Default: ``None`` (always wait for ``batch_size``).

    start_short_with
        The smallest group that ``start_short_after`` may start, between 1 and
        ``initial_group_size``. Only used with ``start_short_after``, and defaults
        to ``quorum``. ``quorum`` defaults to it and may not exceed it, so that a
        group started this way is not below quorum at its first barrier.

    max_wait_time, max_wait_action
        How long a participant may wait for a group (default 20 seconds), and
        what happens then: ``"fail"`` (default) fails them, and
        ``"continue_without_group"`` lets them carry on without a group (see
        :class:`Grouper`).

    kwargs
        Further arguments to pass to Grouper, such as ``waiting_message``.
    """

    def __init__(
        self,
        group_type: str,
        *,
        initial_group_size: Optional[int] = None,
        max_group_size: Optional[Union[int, str]] = "initial_group_size",
        min_group_size: Union[int, str] = NoArgumentProvided,
        batch_size: Union[int, str] = "initial_group_size",
        join_existing_groups: bool = False,
        join_criterion: Optional[Callable] = None,
        below_quorum: Optional[str] = None,
        start_short_after: Optional[float] = None,
        start_short_with: Optional[int] = None,
        quorum: Optional[int] = None,
        top_up_wait: Optional[float] = None,
        use_admission_points: Optional[bool] = None,
        target_group_size: Optional[int] = None,
        max_groups: Optional[int] = None,
        **kwargs,
    ):
        _reject_old_below_quorum_names(kwargs)
        if "group_size" in kwargs:
            raise ValueError(
                "The group_size argument has been renamed to initial_group_size, "
                "please update your code accordingly.",
            )

        if initial_group_size is None:
            raise ValueError("initial_group_size must be provided.")

        if not kwargs.get("id_"):
            kwargs["id_"] = f"{group_type}_grouper_{initial_group_size}"
        super().__init__(group_type=group_type, **kwargs)

        if max_group_size == "initial_group_size":
            max_group_size = initial_group_size
        else:
            if not join_existing_groups:
                raise ValueError(
                    "A max_group_size other than 'initial_group_size' requires "
                    "join_existing_groups=True: a group only grows past its "
                    "initial size by taking newcomers."
                )

        if min_group_size is not NoArgumentProvided:
            if quorum is not None:
                raise ValueError("Pass quorum, not also its old name min_group_size.")
            warn_from_caller(
                "SimpleGrouper(min_group_size=...) is deprecated; pass quorum=... "
                "instead (how many active members a group needs to keep going).",
                FutureWarning,
            )
            if min_group_size != "initial_group_size":
                # 13.3.0 accepted 0, which behaves like 1.
                quorum = max(min_group_size, 1)
        if batch_size == "initial_group_size":
            batch_size = initial_group_size

        self.initial_group_size = initial_group_size
        self.max_group_size = max_group_size
        self.batch_size = batch_size
        self.join_existing_groups = join_existing_groups
        self.join_criterion = join_criterion
        if below_quorum not in (None, "fail", "continue_without_group"):
            hint = (
                " The remaining members don't leave the group; it ends around them, "
                "so use 'continue_without_group'."
                if below_quorum == "leave_group"
                else " Functions aren't supported; pass one of these strings."
                if callable(below_quorum)
                else ""
            )
            raise ValueError(
                "below_quorum must be 'fail' or 'continue_without_group', "
                f"got {below_quorum!r}.{hint}"
            )
        self.below_quorum = below_quorum
        if top_up_wait is not None and not join_existing_groups:
            raise ValueError(
                "top_up_wait requires join_existing_groups=True: only groups that "
                "accept newcomers wait for them."
            )
        if top_up_wait is not None and top_up_wait <= 0:
            raise ValueError(f"top_up_wait must be positive, got {top_up_wait}.")
        self.top_up_wait = top_up_wait
        if start_short_after is None and start_short_with is not None:
            raise ValueError(
                "start_short_with is only used with start_short_after: pass how "
                "long to wait before a short start too."
            )
        if start_short_after is not None and start_short_with is None:
            if quorum is None:
                raise ValueError(
                    "With start_short_after, pass quorum=...: a short start forms "
                    "a group of at least that many (or pass start_short_with)."
                )
            if quorum > initial_group_size:
                raise ValueError(
                    f"start_short_after needs quorum ({quorum}) to be at most "
                    f"initial_group_size ({initial_group_size}): a short start forms "
                    "a group of at least the quorum. Lower quorum, or drop "
                    "start_short_after."
                )
            start_short_with = quorum
        if start_short_with is not None and not (
            1 <= start_short_with <= initial_group_size
        ):
            raise ValueError(
                "Need 1 <= start_short_with <= initial_group_size, "
                f"got {start_short_with}."
            )
        if (
            quorum is None
            and start_short_with is None
            and min_group_size is NoArgumentProvided
            and initial_group_size > 2
        ):
            warn_from_caller(
                f"SimpleGrouper('{group_type}') makes groups of "
                f"{initial_group_size} that need all {initial_group_size} members "
                "to keep going. Pass quorum=... to choose how many members a "
                f"group needs (quorum={initial_group_size} keeps this behavior).",
                UserWarning,
            )
        if quorum is None:
            quorum = (
                start_short_with if start_short_with is not None else initial_group_size
            )
        if quorum < 1 or (quorum > initial_group_size and not join_existing_groups):
            raise ValueError(
                f"Need 1 <= quorum <= initial_group_size, got quorum={quorum} "
                "(a larger quorum needs join_existing_groups=True)."
            )
        if max_group_size is not None and quorum > max_group_size:
            raise ValueError(
                f"quorum ({quorum}) must be at most max_group_size ({max_group_size}): "
                "a group could never reach it."
            )
        if start_short_with is not None and quorum > start_short_with:
            raise ValueError(
                f"quorum ({quorum}) must be at most start_short_with "
                f"({start_short_with}): a group started short would already be "
                "below quorum."
            )
        self.quorum = quorum
        if below_quorum is None and quorum < initial_group_size:
            raise ValueError(
                f"SimpleGrouper('{group_type}') has a quorum ({quorum}) below "
                f"initial_group_size ({initial_group_size}), so its groups can "
                "shrink. Pass below_quorum='fail' to fail the remaining members "
                "when a group falls below its quorum, or "
                "below_quorum='continue_without_group' to let them carry on "
                "without it."
            )
        if (
            start_short_after is not None
            and self.max_wait_time is not None
            and not callable(self.max_wait_time)
            and self.max_wait_time <= start_short_after
        ):
            raise ValueError(
                f"start_short_after ({start_short_after} s) must be less than "
                f"max_wait_time ({self.max_wait_time} s), otherwise participants "
                "are failed before a smaller group can start."
            )
        self.start_short_after = start_short_after
        self.start_short_with = start_short_with
        self.use_admission_points = self._check_use_admission_points(
            use_admission_points, join_existing_groups
        )
        if self.use_admission_points:
            if target_group_size is None:
                raise ValueError(
                    "use_admission_points=True needs target_group_size: "
                    "how many members an admission point waits for (up to "
                    "top_up_wait) before carrying on."
                )
            if not quorum <= target_group_size <= (max_group_size or float("inf")):
                raise ValueError(
                    "Need quorum <= target_group_size <= max_group_size, got "
                    f"{quorum}, {target_group_size} and {max_group_size}."
                )
        elif target_group_size is not None:
            raise ValueError(
                "target_group_size is only used with use_admission_points=True."
            )
        self.target_group_size = target_group_size
        if max_groups is not None and (
            not isinstance(max_groups, int) or max_groups < 1
        ):
            raise ValueError(
                f"max_groups must be a positive integer, got {max_groups!r}."
            )
        self.max_groups = max_groups

    @staticmethod
    def _check_use_admission_points(use_admission_points, join_existing_groups):
        """Validate ``use_admission_points``, warning and defaulting when it is left out."""
        if use_admission_points is None:
            if join_existing_groups:
                warn_from_caller(
                    "SimpleGrouper(join_existing_groups=True) should say when "
                    "newcomers start taking part: pass use_admission_points=False "
                    "(the current behavior: at once) or use_admission_points=True "
                    "(at the group's next admission point).",
                    FutureWarning,
                )
            return False
        if not isinstance(use_admission_points, bool):
            raise ValueError(
                "use_admission_points must be True or False, "
                f"got {use_admission_points!r}."
            )
        if not join_existing_groups:
            raise ValueError(
                "use_admission_points requires join_existing_groups=True: only "
                "groups that take newcomers admit them."
            )
        return use_admission_points

    @property
    def min_group_size(self):
        """Deprecated name for :attr:`quorum`."""
        return self.quorum

    @min_group_size.setter
    def min_group_size(self, value):
        warn_from_caller(
            "SimpleGrouper.min_group_size is deprecated; set quorum instead.",
            FutureWarning,
        )
        self.quorum = max(value, 1)

    def resolve(self):
        from .timeline import conditional, join

        return join(
            CodeBlock(self._join_on_arrival),
            conditional(
                "joined_an_existing_group",
                condition=lambda participant: (
                    self.group_type in participant.active_sync_groups
                ),
                logic_if_true=[],
                logic_if_false=super().resolve(),
            ),
        )

    def _find_group_to_join(self, participant: Participant):
        """Return the open group this participant may join, or ``None``.

        Read-only and unlocked, so the release peek can use it. Joining goes
        through :meth:`_claim_group_to_join`, which re-checks under a lock.
        """
        return next(self._groups_to_join(participant), None)

    def _groups_to_join(self, participant: Participant):
        """Yield open groups this participant may join, best first.

        Closed groups and groups whose members have all left are skipped:
        joining an empty group would start a group of one and bypass
        ``batch_size``. Counts pending members live but uses the stored
        count of admitted members, which a concurrent join may have made
        stale; :meth:`_has_room_to_join` recounts under the group's lock.
        """
        if not self.join_existing_groups:
            return

        link = ParticipantLinkSyncGroup
        n_pending = (
            select(func.count(link.id))
            .join(Participant, Participant.id == link.participant_id)
            .where(
                link.sync_group_id == SimpleSyncGroup.id,
                link.active.is_(True),
                link.admitted_at.is_(None),
                ~Participant.failed,
                Participant.status == "working",
            )
            .correlate(SimpleSyncGroup)
            .scalar_subquery()
        )
        seats_taken = SimpleSyncGroup.n_active_participants + n_pending
        query = SimpleSyncGroup.query.filter(
            SimpleSyncGroup.group_type == self.group_type,
            SimpleSyncGroup.active.is_(True),
            SimpleSyncGroup.accepts_top_ups.is_(True),
            SimpleSyncGroup.n_active_participants > 0,
        )

        if self.max_group_size is not None:
            query = query.filter(seats_taken < self.max_group_size)

        # Pending members hold seats: join the groups with the fewest seats
        # taken, and among those, the oldest.
        query = query.order_by(seats_taken, SimpleSyncGroup.id)

        for group in query.all():
            if self.join_criterion is None or self.join_criterion(
                group=group, participant=participant
            ):
                yield group

    def _claim_group_to_join(self, participant: Participant, *, wait=False):
        """Lock and return the best group with room for this participant.

        Each candidate's row is locked ``FOR NO KEY UPDATE SKIP LOCKED``, and
        its active members are re-counted under that lock, so two joiners
        cannot both take a group's last place. A :class:`GroupBarrier` check
        holds the same lock while it counts a top-up group's members, so a
        newcomer joins either before the check or after it commits. A group
        another transaction is changing is skipped for the next candidate.
        Each lock, including the one after a ``wait``, is taken in a
        savepoint, rolled back unless that group is joined, so the joiner
        holds at most the row of the group it joins.
        The joiner already holds its own participant row (or, in a barrier
        check, the waiters' rows), so this keeps the order participants
        before group.

        Parameters
        ----------
        participant
            The newcomer.
        wait
            If every open group was busy, wait up to
            ``_JOIN_LOCK_WAIT_SECONDS`` for the best one instead of returning
            ``None``. For the newcomer's own request, which would otherwise
            wait at the grouper for the barrier poller; barrier checks don't
            wait. The wait can't deadlock: it holds no other group's row,
            and the newcomer has no link in the group yet, so whoever holds
            the group's row has no reason to lock the newcomer's.

        Returns
        -------
        SimpleSyncGroup or None
            The locked group, or ``None`` if no candidate is free and has room.
        """
        busy = None
        for candidate in self._groups_to_join(participant):
            locked, group = self._lock_if_room_to_join(candidate.id, skip_locked=True)
            if group is not None:
                return group
            if not locked:
                busy = busy or candidate
        if wait and busy is not None:
            _, group = self._lock_if_room_to_join(
                busy.id, wait_seconds=_JOIN_LOCK_WAIT_SECONDS
            )
            return group
        return None

    def _lock_if_room_to_join(self, group_id, **lock_options):
        """Lock a group's row in a savepoint and keep the lock only if a newcomer may join.

        Returns ``(locked, group)``: whether the row was locked, and the
        group if it has room. A group without room has its savepoint rolled
        back, releasing its row.
        """
        with db.session.begin_nested() as savepoint:
            group = _lock_sync_group(group_id, **lock_options)
            if group is not None and self._has_room_to_join(group):
                return True, group
            savepoint.rollback()
        return group is not None, None

    def _has_room_to_join(self, group) -> bool:
        """Re-count a locked group's members and return whether a newcomer may join it.

        The recount corrects a stale stored count, but for a group without
        room it is rolled back with the savepoint, so later newcomers repeat
        it until :func:`check_sync_groups` corrects the count. That costs one
        member query per arrival.
        """
        if not group.active or not group.accepts_top_ups:
            return False
        n_admitted = len(group.active_participants)
        group.n_active_participants = n_admitted
        n_seats_taken = n_admitted + len(group.pending_participants)
        return n_admitted > 0 and (
            self.max_group_size is None or n_seats_taken < self.max_group_size
        )

    def _join_on_arrival(self, participant: Participant):
        """Join an open group as the newcomer reaches the grouper, waiting briefly for a busy one."""
        self._join_existing_groups(participant, wait=True)

    def _join_existing_groups(self, participant: Participant, *, wait=False):
        group = self._claim_group_to_join(participant, wait=wait)
        if group is not None:
            group._add_link(participant, admitted=not group.uses_admission_points)
            assert participant.active_sync_groups[self.group_type] == group
            group.check_numbers()
            group.check_leader()
            # Joining skips this barrier, whose arrival would forget a
            # time-out from before joining.
            participant.timed_out_since_barrier = False

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        """Release waiters who can join an open group, then group the rest.

        Participants who arrive while a group is open join it before reaching
        the barrier. Those already waiting, such as leftovers from a burst of
        arrivals that was not a multiple of ``initial_group_size``, join here
        once a group opens.
        """
        if not self.join_existing_groups:
            released = super().choose_who_to_release(waiting_participants)
        else:
            joined, still_waiting = [], []
            for participant in waiting_participants:
                self._join_existing_groups(participant)
                if self.group_type in participant.active_sync_groups:
                    joined.append(participant)
                else:
                    still_waiting.append(participant)
            released = joined + super().choose_who_to_release(still_waiting)
        self._refresh_countdowns(waiting_participants, released)
        return released

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        """Return whether a check would form a group or let a waiter join one."""
        if super().would_release(waiting_participants):
            return True
        if not self.join_existing_groups:
            return False
        # Without a join_criterion, every waiter would join the same group.
        candidates = (
            waiting_participants if self.join_criterion else waiting_participants[:1]
        )
        return any(self._find_group_to_join(p) is not None for p in candidates)

    def ready_to_group(self, participants: List[Participant]) -> bool:
        if self._groups_left() == 0:
            return False
        if len(participants) >= self.batch_size:
            return True
        return self._can_start_short(participants)

    def _groups_left(self) -> Optional[int]:
        """Return how many more groups ``max_groups`` allows, or ``None`` without a cap."""
        if getattr(self, "max_groups", None) is None:
            return None
        n_active = SimpleSyncGroup.query.filter_by(
            grouper_id=self.id, active=True
        ).count()
        return max(self.max_groups - n_active, 0)

    def _can_start_short(self, participants: List[Participant]) -> bool:
        """Return whether enough people have waited long enough for a short start."""
        start_time = self._short_start_time(participants)
        return start_time is not None and time.time() >= start_time

    def _short_start_time(self, participants) -> Optional[float]:
        """Return when these waiters can start short, in epoch seconds, if they ever can."""
        if self.start_short_after is None or len(participants) < self.start_short_with:
            return None
        first_arrival = min(_arrival_time(self, p) for p in participants)
        return first_arrival.timestamp() + self.start_short_after

    def _shows_countdown(self) -> bool:
        return self.start_short_after is not None

    def expected_release_time(self, participant) -> Optional[float]:
        """Return when the waiting participants will start short, in epoch seconds.

        ``None`` until ``start_short_with`` participants are waiting, or without
        ``start_short_after``.
        """
        if self.start_short_after is None or not self._participant_is_waiting(
            participant
        ):
            return None
        return self._short_start_time(self.get_waiting_participants(participant))

    def _refresh_countdowns(self, waiting_participants, released):
        """Send those still waiting the new short start time, and its message, when it changes.

        Runs inside the serialized barrier check, so simultaneous arrivals and
        departures are all seen.
        """
        message = getattr(self, "waiting_message", None)
        if self.start_short_after is None or (
            not isinstance(message, SerializedCallable)
            and "{SECONDS}" not in str(message or "")
        ):
            return
        released_ids = {p.id for p in released}
        remaining = [p for p in waiting_participants if p.id not in released_ids]
        start = self._short_start_time(remaining)
        instance = BarrierInstance._active_instance(self.id, None)
        if instance is None or instance.announced_release_time == start:
            return
        instance.announced_release_time = start
        hold_page = _BarrierHoldPage(self)
        for member in remaining:
            if not member.failed:
                _queue_countdown_update(
                    member.id,
                    start,
                    hold_message=hold_page.overlay_html(member, release_time=start),
                )

    def group(self, participants: List[Participant]) -> List["SyncGroup"]:
        if len(participants) < self.initial_group_size:
            return [
                self._make_group(participants, initial_group_size=len(participants))
            ]
        n_groups = floor(len(participants) / self.initial_group_size)
        groups_left = self._groups_left()
        if groups_left is not None:
            n_groups = min(n_groups, groups_left)
        n_participants_to_group = n_groups * self.initial_group_size
        participants_to_group = participants[:n_participants_to_group]

        grouped_participants = self.randomly_partition_list(
            participants_to_group, group_size=self.initial_group_size
        )
        return [
            self._make_group(_participants, initial_group_size=self.initial_group_size)
            for _participants in grouped_participants
        ]

    def _make_group(self, participants, *, initial_group_size):
        """Create one group of these participants with this grouper's settings."""
        return self._create_group(
            participants,
            initial_group_size=initial_group_size,
            max_group_size=self.max_group_size,
            quorum=self.quorum,
            accepts_top_ups=self.join_existing_groups,
            below_quorum=self.below_quorum or "fail",
            top_up_wait=self.top_up_wait,
            uses_admission_points=self.use_admission_points,
            target_group_size=self.target_group_size,
        )

    @staticmethod
    def randomly_partition_list(lst: list, group_size: int):
        n_groups = len(lst) / group_size
        if not n_groups == floor(n_groups):
            raise ValueError(
                f"List size ({len(lst)}) is not an integer multiple of group_size ({group_size})"
            )
        n_groups = floor(n_groups)
        lst = lst.copy()
        random.shuffle(lst)
        return [lst[i::n_groups] for i in range(n_groups)]


def _latest_tick(now: float, period: float) -> float:
    """Return the most recent tick at or before ``now`` (seconds since the epoch)."""
    return floor(now / period) * period


def _balanced_groups(members, max_size, min_size):
    """Shuffle members into balanced groups of at most ``max_size``.

    Members who do not fit a group of at least ``min_size`` are left out,
    for example the odd one out when pairing.
    """
    members = random.sample(list(members), len(members))
    n_groups = -(-len(members) // max_size)
    if n_groups == 0:
        return []
    if len(members) // n_groups < min_size:
        n_groups = len(members) // max_size
        members = members[: n_groups * max_size]
        if n_groups == 0:
            return []
    return [members[i::n_groups] for i in range(n_groups)]


class Regrouper(Grouper):
    """Repeatedly split participants into new groups, for example once per round.

    Each time a participant reaches the regrouper, they leave their previous
    group of this ``group_type`` and wait for the next split. Waiting
    participants are pooled: by default everyone waiting is one pool, and with
    ``within`` each existing group (such as a cohort) is its own pool. A pool is
    split into groups when every active member of its ``within`` group is
    waiting, or when its ``deadline`` passes, whichever comes first. With
    ``every``, splits happen only on fixed wall-clock ticks instead. Absent
    members are not waited for beyond the deadline once a group can be
    formed without them, and are never failed for missing a split; they join
    the pool again when they come back.

    Groups made by a regrouper don't accept top-ups and are never dissolved
    when a member leaves, so a member who drops out of a round leaves their
    partners in a smaller group rather than failing them.

    By default, members are grouped at random, and when not everyone waiting
    fits into a group, those who have played the most rounds sit out. The
    regrouper counts each participant's rounds (:meth:`rounds_played`,
    :meth:`rounds_sat_out`, :meth:`sat_out`) and, with ``roles``, gives out roles
    (read in a cued trial as :attr:`~psynet.trial.main.Trial.sync_group_role`),
    all while it holds its lock, so two splits cannot give
    out the same seat twice. Each group records the regrouper that formed
    it, and each member's link to it records their role, so these counts
    come from the groups themselves.

    Parameters
    ----------
    group_type
        Type of the groups this regrouper creates, for example ``"pair"``.

    within
        Optional ``group_type`` of an existing group to regroup within, for
        example ``"cohort"``. Participants are only grouped with members of the
        same ``within`` group, and a pool counts as complete once all that
        group's admitted members are waiting. A participant without such a group
        is released ungrouped. If ``None`` (default), everyone waiting is one pool,
        which is only split at the ``deadline`` or ``every`` tick.
        Each split is an admission point of the ``within`` group (see
        :ref:`sync-admission-points`): its pending members waiting in the pool
        are admitted, then grouped with the rest.

    group_size
        Size of the groups to form. The pool is split into balanced groups of
        at most this size, for example rooms of 8, 8, 7 and 7 for 30 people
        with ``group_size=8``. Required unless ``roles`` is given, which sets
        it.

    smallest_group
        Smallest group to form when the pool doesn't divide evenly or members
        are missing: 2 by default (or ``group_size`` if that is smaller). A
        pool is only split once this many of its members are waiting. Groups
        are never dissolved later, so a group can carry on below this size.
        With ``roles`` every group has one member per role.

    deadline
        Seconds to wait for absent members, counted from when the first of
        the pool's waiting members arrived, or from the pool's previous split
        if that is later. The pool is split when it is complete or when the
        deadline passes. Make it longer than a round takes: otherwise members
        who finish a round early are split again before the rest are back.
        ``None`` (default) waits until the pool is complete, which needs
        ``within``.

    every
        Seconds between fixed wall-clock ticks. The pool is split only at a
        tick, even when everyone is already waiting, if at least
        ``smallest_group`` members were waiting at the tick. The background
        barrier check makes the split at its next check after the tick,
        normally within a second, so participants arriving with Next don't
        wait for a check of the whole pool; an arrival or reload in
        ``GET /timeline`` still checks the waiter's visit. Pass either
        ``deadline`` or ``every``, not both.

    roles
        Optional role names, for example ``["proposer", "responder"]``. Each
        group then has one member per role, so groups have ``len(roles)``
        members; ``group_size``, if given, must equal it. A cued trial reads its
        player's role as :attr:`~psynet.trial.main.Trial.sync_group_role`. Roles
        are given out at random by default; see ``assign_roles``.

    form_groups
        Optional callable ``form_groups(members, within_group, barrier)``
        that returns a list of groups, each a list of participants, replacing
        the default grouping described above; ``barrier`` is this regrouper.
        Members who are not placed are left over. With ``roles``, each group
        needs one member per role; ``assign_roles`` then gives out the roles.
        Subclasses can override :meth:`form_groups` instead, for
        example calling the default and retrying until no one is paired with
        last round's partner, as the ``ultimatum_pairing`` demo does. The
        callable must be a module-level function so it can be
        stored with the barrier.

    assign_roles
        Optional callable ``assign_roles(members, within_group, barrier)``
        that returns ``{participant: role}`` for one group formed with
        ``roles``, giving each role to one member; ``barrier`` is this
        regrouper. It is called once per group, before the group is created,
        replacing the default, which shuffles the roles across the group's
        members. Subclasses can override :meth:`assign_roles` instead, for
        example to give each role to whoever has held it least often, so that
        roles alternate, as the ``ultimatum_pairing`` demo does. The callable
        must be a module-level function so it can be stored with the barrier.

    left_over
        What participants left over after a split do: ``"wait"`` (default)
        keeps them waiting for the next split, and ``"sit_out"`` lets them
        continue ungrouped, for example to a sit-out page, and come back for
        the next split. With
        ``within``, when too few are waiting to form any group, for example
        one player whose cohort is still playing a round, they wait for
        the rest of the cohort for up to one more ``deadline`` (or ``every`` tick)
        before they are released ungrouped, or until ``max_wait_time`` if
        there is no deadline. Taking members who stop playing out of the
        ``within`` group, for example with ``remove_participant``, means
        nobody waits for them.

    on_release
        Optional callback ``on_release(within_group, groups, left_over, barrier)``
        run after each split that forms at least one group, after roles are
        given out; ``barrier`` is this regrouper. The new ``groups`` already
        have their ``id``, for example to save as a pair ID. A late member can make a split
        of their own in the same round, so count rounds per participant (see
        :meth:`rounds_played`) rather than here.

    stop_top_ups_after_rounds
        Optional number of rounds during which newcomers can still join the
        ``within`` group, for example a cohort formed with
        ``join_existing_groups=True``. Each split that forms groups in the
        cohort counts as one of its rounds, even one that groups only
        latecomers while the others are still playing. The next split, even
        one in which everyone waiting sits out, stops the cohort's top-ups, as
        :meth:`SimpleSyncGroup.stop_top_ups` does; a cohort below its quorum
        is then dissolved instead of split, as its ``below_quorum`` says.
        With ``0`` the cohort closes when its first round starts. ``None``
        (default) leaves top-ups to the grouper and the barriers. Needs
        ``within``, and only applies to ``within`` groups that accept
        top-ups; it does nothing for others.

    max_wait_time
        Longest a participant waits at the regrouper before ``max_wait_action``
        applies: being failed by default, or carrying on without a group with
        ``max_wait_action="continue_without_group"``. Defaults to 300 seconds, or to twice the ``deadline`` (or ``every``
        period) plus 60 seconds if that is longer. With ``left_over="sit_out"``
        and ``within``, a value you pass must be longer than twice the
        period, so that a player waiting alone sits out instead of being
        failed.

    waiting_message
        Message shown while waiting. A ``{SECONDS}`` placeholder becomes a live
        countdown to the pool's deadline or next tick, for example
        ``"Next round in {SECONDS} s"``. To show other text while the deadline
        is unknown, for example while a participant waits alone, pass a function
        of ``seconds_left``, which is ``None`` then (see :class:`Barrier`).

    kwargs
        Further arguments to pass to :class:`Grouper`.
    """

    def __init__(
        self,
        group_type: str,
        *,
        within: Optional[str] = None,
        group_size: Optional[int] = None,
        smallest_group: Optional[int] = None,
        deadline: Optional[float] = None,
        every: Optional[float] = None,
        roles: Optional[Sequence[str]] = None,
        form_groups: Optional[Callable] = None,
        assign_roles: Optional[Callable] = None,
        left_over: Literal["wait", "sit_out"] = "wait",
        on_release: Optional[Callable] = None,
        stop_top_ups_after_rounds: Optional[int] = None,
        max_wait_time: Optional[Union[float, Callable]] = NoArgumentProvided,
        **kwargs,
    ):
        if stop_top_ups_after_rounds is not None:
            if within is None:
                raise ValueError("stop_top_ups_after_rounds needs within.")
            if (
                isinstance(stop_top_ups_after_rounds, bool)
                or not isinstance(stop_top_ups_after_rounds, int)
                or stop_top_ups_after_rounds < 0
            ):
                raise ValueError(
                    "stop_top_ups_after_rounds must be a whole number, 0 or more."
                )
        if roles is not None:
            if len(set(roles)) != len(roles):
                raise ValueError("Pass distinct role names.")
            for name, value in (
                ("group_size", group_size),
                ("smallest_group", smallest_group),
            ):
                if value not in (None, len(roles)):
                    raise ValueError(
                        "With roles, each group has one member per role, so "
                        f"{name} must equal len(roles) or be left out."
                    )
            group_size = smallest_group = len(roles)
        elif group_size is None:
            raise ValueError("Regrouper needs group_size, or roles.")
        if smallest_group is None:
            smallest_group = min(2, group_size)
        if smallest_group < 1 or group_size < smallest_group:
            raise ValueError("Need 1 <= smallest_group <= group_size.")
        if deadline is not None and every is not None:
            raise ValueError(
                "Pass deadline (a timeout) or every (fixed ticks), not both."
            )
        if every is not None and every <= 0:
            raise ValueError("every must be positive.")
        if deadline is not None and deadline <= 0:
            raise ValueError("deadline must be positive.")
        if deadline is None and every is None and within is None:
            raise ValueError(
                "A Regrouper without `within` needs a deadline or every, because "
                "it cannot tell when everyone is present."
            )
        if "below_quorum" in kwargs or any(
            name in kwargs for name in _OLD_BELOW_QUORUM_NAMES
        ):
            raise TypeError(
                "Regrouper groups are never dissolved when a member leaves, so "
                "below_quorum doesn't apply; it is an option of "
                "the SimpleGrouper that forms the groups being regrouped."
            )
        if left_over not in ("wait", "sit_out"):
            raise ValueError(
                f"left_over must be 'wait' or 'sit_out', got {left_over!r}."
            )
        longest_lone_wait = every or deadline
        if max_wait_time is NoArgumentProvided:
            max_wait_time = max(300, 2 * (longest_lone_wait or 0) + 60)
        elif (
            left_over == "sit_out"
            and within is not None
            and longest_lone_wait is not None
            and isinstance(max_wait_time, (int, float))
            and max_wait_time <= 2 * longest_lone_wait
        ):
            raise ValueError(
                f"max_wait_time ({max_wait_time} s) must be longer than twice the "
                f"deadline or every period ({longest_lone_wait} s): with "
                "left_over='sit_out', a player waiting alone for cohort members who are "
                "still playing waits up to two periods before sitting out."
            )
        kwargs.setdefault("id_", f"{group_type}_regrouper")
        super().__init__(group_type=group_type, max_wait_time=max_wait_time, **kwargs)
        self.within = within
        self.group_size = group_size
        self.smallest_group = smallest_group
        self.deadline = deadline
        self.every = every
        self.roles = None if roles is None else list(roles)
        self.form_groups_function = form_groups
        self.assign_roles_function = assign_roles
        self.left_over = left_over
        self.on_release = on_release
        self.stop_top_ups_after_rounds = stop_top_ups_after_rounds

    def receive_participant(self, participant: Participant):
        previous = participant.active_sync_groups.get(self.group_type)
        if previous is not None:
            previous.remove_participant(participant, reason="moved_on")
        Barrier.receive_participant(self, participant)

    def _queue_check_on_arrival(self, barrier_instance):
        """Leave a pool with ``every`` ticks to the barrier poller.

        Such a pool is split only at a tick, among the members who were
        already waiting then, so an arrival cannot make the pool ready. A
        check on the arrival would enact a tick that is already due and not
        yet used, but it locks every waiter to do so. Skipping it leaves that
        split to the barrier poller, at its next check and normally within a
        second. This only covers arrivals submitted with Next
        (``POST /response``): an arrival or reload in ``GET /timeline``, or a
        bot's poll, still checks the waiter's visit. Ungrouped arrivals at a
        ``within`` regrouper are still checked, because they are released at
        once. Subclasses that override :meth:`choose_who_to_release` or
        :meth:`check_waiting_participants` keep the check, since their rule
        might release on arrival.
        """
        if self._skips_arrival_release_check(barrier_instance):
            return
        super()._queue_check_on_arrival(barrier_instance)

    def _skips_arrival_release_check(self, barrier_instance):
        """Return whether this arrival should skip the queued release check."""
        return (
            self.every is not None
            and (self.within is None or barrier_instance.group_id is not None)
            and type(self).choose_who_to_release is Regrouper.choose_who_to_release
            and type(self).check_waiting_participants
            is Regrouper.check_waiting_participants
        )

    def form_groups(self, members, within_group=None):
        """Return the groups to form from one pool's waiting members.

        By default members are shuffled into balanced groups of at most
        ``group_size`` and at least ``smallest_group``, or into one group per
        set of ``roles``. Those who have played the most rounds sit out.
        """
        if self.form_groups_function is not None:
            return self.form_groups_function(
                members=members, within_group=within_group, barrier=self
            )
        rounds = self._rounds(members)
        # Shuffled first, so that ties are broken at random.
        members = sorted(
            random.sample(members, len(members)), key=lambda m: rounds[m.id]
        )
        n_placed = sum(
            len(group)
            for group in _balanced_groups(members, self.group_size, self.smallest_group)
        )
        return _balanced_groups(
            members[:n_placed], self.group_size, self.smallest_group
        )

    def rounds_played(self, participant) -> int:
        """Return how many groups this regrouper has put ``participant`` in.

        A group counts from when it is formed, even if the participant is
        later removed from it, for example for being away too long.
        """
        return (
            ParticipantLinkSyncGroup.query.join(SyncGroup)
            .filter(
                SyncGroup.grouper_id == self.id,
                ParticipantLinkSyncGroup.participant_id == participant.id,
            )
            .count()
        )

    def rounds_sat_out(self, participant) -> int:
        """Return how often ``participant`` sat a round out (see ``left_over``)."""
        return ParticipantLinkBarrier.query.filter_by(
            barrier_id=self.id, participant_id=participant.id, sat_out=True
        ).count()

    def sat_out(self, participant) -> bool:
        """Return whether ``participant`` sat out their latest visit here (see ``left_over``)."""
        latest_visit = self._latest_visit(participant)
        return latest_visit is not None and bool(latest_visit.sat_out)

    def _latest_visit(self, participant) -> Optional["ParticipantLinkBarrier"]:
        """Return ``participant``'s latest visit to this regrouper, if any."""
        return (
            ParticipantLinkBarrier.query.filter_by(
                barrier_id=self.id, participant_id=participant.id
            )
            .order_by(ParticipantLinkBarrier.id.desc())
            .first()
        )

    def _links(self, participant_ids) -> List["ParticipantLinkSyncGroup"]:
        """Return these participants' links to groups this regrouper formed, oldest first."""
        if not participant_ids:
            return []
        return (
            ParticipantLinkSyncGroup.query.join(SyncGroup)
            .filter(
                SyncGroup.grouper_id == self.id,
                ParticipantLinkSyncGroup.participant_id.in_(participant_ids),
            )
            .order_by(ParticipantLinkSyncGroup.id)
            .all()
        )

    def _visits(self, participants) -> Dict[int, "ParticipantLinkBarrier"]:
        """Return each participant's current, unreleased visit to this regrouper."""
        if not participants:
            return {}
        visits = ParticipantLinkBarrier.query.filter(
            ParticipantLinkBarrier.barrier_id == self.id,
            ParticipantLinkBarrier.participant_id.in_([p.id for p in participants]),
            ParticipantLinkBarrier.released.is_(False),
        )
        return {visit.participant_id: visit for visit in visits}

    def assign_roles(self, members, within_group=None) -> Dict[Participant, str]:
        """Return ``{participant: role}`` for one group's members, one member per role.

        By default the roles are shuffled across the members.
        """
        if self.assign_roles_function is not None:
            return self.assign_roles_function(
                members=members, within_group=within_group, barrier=self
            )
        return dict(zip(random.sample(members, len(members)), self.roles))

    def _rounds(self, members) -> Dict[int, int]:
        """Return how many groups this regrouper has put each member in, keyed by ID."""
        rounds = {m.id: 0 for m in members}
        for link in self._links(list(rounds)):
            rounds[link.participant_id] += 1
        return rounds

    def _planned_roles(self, plan, within_group) -> Dict[int, str]:
        """Return each planned member's role by ID, given out before the groups exist."""
        if not self.roles:
            return {}
        roles = {}
        for group_members in plan:
            assigned = self.assign_roles(group_members, within_group=within_group)
            if not all(isinstance(m, Participant) for m in assigned):
                raise TypeError(
                    f"Regrouper '{self.id}': assign_roles must return "
                    "{participant: role}, keyed by participants rather than IDs."
                )
            if sorted(m.id for m in assigned) != sorted(
                m.id for m in group_members
            ) or sorted(assigned.values()) != sorted(self.roles):
                raise ValueError(
                    f"Regrouper '{self.id}': assign_roles must give each role "
                    "to one member of the group."
                )
            roles.update({m.id: role for m, role in assigned.items()})
        return roles

    def _shows_countdown(self) -> bool:
        return self.every is not None or self.deadline is not None

    def expected_release_time(self, participant) -> Optional[float]:
        """Return when this participant's pool will be split at the latest, in epoch seconds."""
        if self.id not in participant.active_barriers:
            return None
        within_group = self._within_group(participant)
        if self.within is not None and within_group is None:
            return None
        if _is_dissolving(within_group):
            return None
        if self.every is None and self.deadline is None:
            return None
        waiting = self.get_waiting_participants(participant)
        # Reading who is waiting reloads this participant's barrier links, so
        # a release by another request since the check above shows up here.
        if participant not in waiting:
            return None
        pool = next(
            members for _, members in self._pools(waiting) if participant in members
        )
        if len(pool) < self._smallest_pool_to_split(within_group, pool):
            return None
        if self.every is None:
            return self._deadline_reference(within_group, pool) + self.deadline
        now = time.time()
        tick = _latest_tick(now, self.every)
        waited_for_tick = _arrival_time(self, participant).timestamp() <= tick
        if waited_for_tick and self._enough_waiting_at_tick(within_group, pool, now):
            # Due now: the poller has not split the pool yet.
            return tick
        return tick + self.every

    def waiting_pool_group(self, participant) -> Optional["SyncGroup"]:
        """Return the participant's ``within`` group, so each cohort waits in its own pool."""
        return self._within_group(participant)

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        released = []
        for within_group, pool in self._pools(waiting_participants):
            if self.within is not None and within_group is None:
                released += pool
                continue
            if _is_dissolving(within_group):
                continue
            members = self._members_to_split(within_group, pool)
            if members is None:
                continue
            stop_top_ups = self._ends_join_window(within_group)
            if stop_top_ups:
                if _lock_sync_group(within_group.id, skip_locked=True) is None:
                    continue
                if _is_dissolving(within_group):
                    continue
                # The lock reloads the cohort's members, so a newcomer who
                # joined in another request now keeps a complete pool waiting.
                members = self._members_to_split(within_group, pool)
                if members is None:
                    continue
                member_ids = {p.id for p in members}
                admissible = [
                    p for p in within_group.pending_participants if p.id in member_ids
                ]
                if (
                    len(within_group.active_participants) + len(admissible)
                    < within_group.quorum
                ):
                    # Dissolving releases the members its below_quorum let
                    # carry on. One deferred by a busy member
                    # marks the cohort dissolving, so later checks skip its
                    # pool until the poller dissolves it.
                    within_group.stop_top_ups()
                    released += [p for p in pool if self._within_group(p) is None]
                    continue
            released += self._split(within_group, members, stop_top_ups=stop_top_ups)
        return released

    def _members_to_split(self, within_group, pool) -> Optional[List[Participant]]:
        """Return the members of a ready pool to split now, or ``None`` if it isn't ready."""
        if not self._pool_is_ready(within_group, pool):
            return None
        if self.every is not None:
            return self._waiting_at_tick(pool, time.time())
        return pool

    def _ends_join_window(self, within_group) -> bool:
        """Return whether the next split comes after ``stop_top_ups_after_rounds`` splits of this cohort."""
        if self.stop_top_ups_after_rounds is None or not within_group.accepts_top_ups:
            return False
        return self._n_splits(within_group) >= self.stop_top_ups_after_rounds

    def _n_splits(self, within_group) -> int:
        """Return how many splits of this pool formed groups."""
        return (
            db.session.query(func.count(SyncGroup.split_id.distinct()))
            .filter(*self._pool_splits(within_group))
            .scalar()
        )

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        return any(
            (self.within is not None and within_group is None)
            or (
                not _is_dissolving(within_group)
                and self._pool_is_ready(within_group, members)
            )
            for within_group, members in self._pools(waiting_participants)
        )

    def _within_group(self, participant):
        if self.within is None:
            return None
        return participant.active_sync_groups.get(self.within)

    def _pools(self, waiting_participants):
        """Yield ``(within_group, members)`` for each pool of waiting participants."""
        pools = {}
        for participant in waiting_participants:
            group = self._within_group(participant)
            key = None if group is None else group.id
            pools.setdefault(key, (group, []))[1].append(participant)
        return list(pools.values())

    def _pool_is_ready(self, within_group, members) -> bool:
        if len(members) < self._smallest_pool_to_split(within_group, members):
            return False
        if self.every is None and self._pool_is_complete(within_group, members):
            return True
        return self._deadline_passed(within_group, members)

    @staticmethod
    def _pool_is_complete(within_group, members) -> bool:
        """Return whether every active member of the ``within`` group is in ``members``."""
        if within_group is None:
            return False
        waiting_ids = {participant.id for participant in members}
        return all(p.id in waiting_ids for p in within_group.active_participants)

    def _may_release_only_left_over(self, within_group, members) -> bool:
        """Return whether a split that forms no group may release its members ungrouped.

        Not while other cohort members are still active elsewhere, for example still
        playing a round, so that a lone waiter waits for them rather than
        sitting out round after round; but only for one more deadline, in case
        those members have stopped playing.
        """
        return self.left_over == "sit_out" and (
            within_group is None
            or self._pool_is_complete(within_group, members)
            or self._waited_an_extra_deadline(within_group, members)
        )

    def _waited_an_extra_deadline(self, within_group, members) -> bool:
        """Return whether the pool has waited a deadline (or ``every`` tick) past the usual one."""
        now = time.time()
        if self.every is not None:
            previous_tick = _latest_tick(now, self.every) - self.every
            return any(
                _arrival_time(self, p).timestamp() <= previous_tick for p in members
            )
        if self.deadline is None:
            return False
        reference = self._deadline_reference(within_group, members)
        return now - reference >= 2 * self.deadline

    def _smallest_pool_to_split(self, within_group, members) -> int:
        if self._may_release_only_left_over(within_group, members):
            return 1
        return self.smallest_group

    def _deadline_passed(self, within_group, members) -> bool:
        now = time.time()
        if self.every is not None:
            return self._enough_waiting_at_tick(within_group, members, now)
        if self.deadline is None:
            return False
        return now - self._deadline_reference(within_group, members) >= self.deadline

    def _deadline_reference(self, within_group, members) -> float:
        """Return when a pool's deadline starts: its first arrival, or its last split if later."""
        first_arrival = min(_arrival_time(self, p) for p in members).timestamp()
        return max(self._last_split(within_group) or 0, first_arrival)

    def _waiting_at_tick(self, members, now):
        """Return the members who were already waiting at the latest tick."""
        tick = _latest_tick(now, self.every)
        return [p for p in members if _arrival_time(self, p).timestamp() <= tick]

    def _enough_waiting_at_tick(self, within_group, members, now) -> bool:
        """Return whether enough members were already waiting at the latest unused tick."""
        last_split = self._last_split(within_group)
        if last_split is not None and last_split >= _latest_tick(now, self.every):
            return False
        at_tick = self._waiting_at_tick(members, now)
        return len(at_tick) >= self._smallest_pool_to_split(within_group, at_tick)

    def _last_split(self, within_group) -> Optional[float]:
        """Return when this regrouper last formed groups in this pool, in epoch seconds."""
        latest = (
            db.session.query(func.max(SyncGroup.creation_time))
            .filter(*self._pool_splits(within_group))
            .scalar()
        )
        return None if latest is None else latest.timestamp()

    def _pool_splits(self, within_group) -> list:
        """Return the filter criteria for the groups this regrouper formed in this pool."""
        return [
            SyncGroup.grouper_id == self.id,
            SyncGroup.within_group_id.is_(None)
            if within_group is None
            else SyncGroup.within_group_id == within_group.id,
        ]

    def _split(self, within_group, members, stop_top_ups=False):
        """Form this pool's groups and return the participants to release.

        With ``stop_top_ups``, a split that forms a group or releases sit-outs
        also stops the ``within`` group's top-ups (see
        ``stop_top_ups_after_rounds``).
        """
        plan = [
            list(group_members)
            for group_members in self.form_groups(members, within_group=within_group)
            if group_members
        ]
        self._check_plan(plan, members)
        roles = self._planned_roles(plan, within_group)
        # The split's time, not the inserts', decides which tick it used.
        split_time = timenow()
        split_id = uuid.uuid4().hex
        groups = [
            self._make_group(group_members, within_group, split_time, split_id)
            for group_members in plan
        ]
        for group in groups:
            for link in group.participant_links:
                if roles:
                    link.role = roles[link.participant.id]
        placed = {p.id for group in groups for p in group.participants}
        left_over = [p for p in members if p.id not in placed]
        if not groups:
            if self._may_release_only_left_over(within_group, members):
                self._admit_released(within_group, left_over)
                if stop_top_ups:
                    within_group.stop_top_ups()
                self._record_sit_outs(left_over)
                return left_over
            return []
        self._admit_released(
            within_group,
            [p for p in members if p.id in placed or self.left_over == "sit_out"],
        )
        if stop_top_ups:
            within_group.stop_top_ups()
        if self.on_release:
            # Gives the new groups their IDs, for example to store as pair IDs.
            db.session.flush()
            try:
                self.on_release(
                    within_group=within_group,
                    groups=groups,
                    left_over=left_over,
                    barrier=self,
                )
            except Exception as err:
                if is_transient_transaction_error(err):
                    raise
                raise _BarrierAuthorHookError(
                    f"Regrouper '{self.id}' on_release failed."
                ) from err
        released = [p for group in groups for p in group.participants]
        if self.left_over == "sit_out":
            self._record_sit_outs(left_over)
            released += left_over
        return released

    def _admit_released(self, within_group, released):
        """Admit the pending ``within`` members among ``released`` and count this admission point for all of them.

        A split is an admission point of the ``within`` group: it admits
        the pending members it places or sits out, in the order they joined.
        """
        if within_group is None:
            return
        released_ids = {p.id for p in released}
        admitted = [
            p for p in within_group.pending_participants if p.id in released_ids
        ]
        visits = self._visits(admitted)
        within_group._admit(admitted, {p.id: visits.get(p.id) for p in admitted})
        for link in within_group.participant_links:
            if link.active and link.participant_id in released_ids:
                link.admission_points_passed = (link.admission_points_passed or 0) + 1

    def _record_sit_outs(self, left_over):
        """Mark these members' current visits as sat out."""
        for visit in self._visits(left_over).values():
            visit.sat_out = True

    def _check_plan(self, plan, members):
        """Raise if ``form_groups`` placed someone twice, placed a non-member, or broke the roles."""
        if not all(
            isinstance(p, Participant) for group_members in plan for p in group_members
        ):
            raise TypeError(
                f"Regrouper '{self.id}': form_groups must return groups as lists "
                "of participants; give out roles with assign_roles instead."
            )
        member_ids = {p.id for p in members}
        placed = [p.id for group_members in plan for p in group_members]
        if len(placed) != len(set(placed)):
            raise ValueError(
                f"Regrouper '{self.id}': form_groups put a participant in two groups."
            )
        outsiders = set(placed) - member_ids
        if outsiders:
            raise ValueError(
                f"Regrouper '{self.id}': form_groups placed participants "
                f"{sorted(outsiders)}, who are not waiting in this pool."
            )
        for group_members in plan if self.roles else []:
            if len(group_members) != len(self.roles):
                raise ValueError(
                    f"Regrouper '{self.id}': with roles, form_groups must "
                    f"return groups of {len(self.roles)}, one member per role."
                )

    def _make_group(self, participants, within_group, creation_time, split_id):
        """Create a fixed group that never dissolves or fails its members."""
        return self._create_group(
            participants,
            within_group_id=None if within_group is None else within_group.id,
            creation_time=creation_time,
            split_id=split_id,
            initial_group_size=len(participants),
            max_group_size=len(participants),
            quorum=1,
            accepts_top_ups=False,
            below_quorum="continue_without_group",
        )


def _is_dissolving(within_group) -> bool:
    """Return whether a regrouper pool's ``within`` group waits to be dissolved, so it isn't split."""
    return within_group is not None and bool(within_group.dissolving)


def check_group_dropout_policies(barriers):
    """Check that groups which late members can shrink say what happens to the rest.

    A :class:`GroupBarrier` with ``late_after`` removes late members from its
    group, and from the groups in ``also_leave``, so each :class:`SimpleGrouper`
    forming such a group must be given ``below_quorum``. With
    ``late_action="leave_group"`` it must not be ``"fail"``, which would fail
    the members who were on time while the late one carries on.

    A barrier with ``late_after`` has no ``max_wait_time``, so a group that
    falls below its quorum there while it waits for newcomers would wait
    forever once they stop coming. Groupers whose groups may wait for
    newcomers at such a barrier, before a ``stop_top_ups=True`` barrier
    stops their top-ups, must therefore set ``top_up_wait``.

    Parameters
    ----------
    barriers : iterable of Barrier
        The barriers in the timeline, in timeline order. Barriers built inside a trial's
        ``show_trial`` are checked by
        :func:`check_late_removal_policies` when the trial is shown; those
        built in a ``for_loop`` or another ``PageMaker`` are not visible, and
        :meth:`GroupBarrier._dissolve_after_late_removal` warns about them at
        runtime.

    Raises
    ------
    ValueError
        If a grouper lacks ``below_quorum``, combines ``below_quorum="fail"``
        with a barrier's ``late_action="leave_group"``, or lacks a
        ``top_up_wait`` that such a barrier needs.
    """
    barriers = list(barriers)
    groupers = {}
    for barrier in barriers:
        if isinstance(barrier, SimpleGrouper):
            groupers.setdefault(barrier.group_type, []).append(barrier)
    top_ups_stopped = set()
    for barrier in barriers:
        if not isinstance(barrier, GroupBarrier):
            continue
        if barrier.late_after is not None and (
            barrier.group_type not in top_ups_stopped
        ):
            for grouper in groupers.get(barrier.group_type, []):
                _check_top_up_wait(
                    barrier,
                    grouper.join_existing_groups,
                    grouper.top_up_wait,
                    grouper.use_admission_points,
                    f"SimpleGrouper '{grouper.id}'",
                )
        if barrier.stop_top_ups:
            top_ups_stopped.add(barrier.group_type)
        if barrier.late_after is None:
            continue
        for group_type in [barrier.group_type, *barrier.also_leave]:
            for grouper in groupers.get(group_type, []):
                if grouper.below_quorum is None:
                    raise ValueError(
                        f"GroupBarrier '{barrier.id}' has late_after, so late "
                        f"members leave their '{group_type}' groups. Pass "
                        f"below_quorum to SimpleGrouper '{grouper.id}' to say "
                        "what happens to the remaining members when a group "
                        "falls below its quorum: 'fail' or "
                        "'continue_without_group'."
                    )
                _check_late_action(
                    barrier, grouper.below_quorum, f"SimpleGrouper '{grouper.id}'"
                )


def check_late_removal_policies(barriers, participant):
    """Check barriers built at runtime against the stored groups they remove late members from.

    :func:`check_group_dropout_policies` only sees the timeline's top-level
    barriers, so :meth:`psynet.trial.main.Trial._show_trial` calls this for
    the barriers in ``show_trial``, using the ``below_quorum`` stored on
    ``participant``'s groups.

    Parameters
    ----------
    barriers : iterable of Barrier
        The barriers to check.
    participant : Participant
        The participant whose active groups the barriers act on.

    Raises
    ------
    ValueError
        If a barrier with ``late_action="leave_group"`` acts on a group with
        ``below_quorum="fail"``, or a ``late_after`` barrier acts on a group
        that could wait there for newcomers without a ``top_up_wait``.
    """
    groups = None
    for barrier in barriers:
        if not isinstance(barrier, GroupBarrier) or barrier.late_after is None:
            continue
        if groups is None:
            groups = participant.active_sync_groups
        group = groups.get(barrier.group_type)
        if isinstance(group, SimpleSyncGroup):
            _check_top_up_wait(
                barrier,
                group.accepts_top_ups,
                group.top_up_wait,
                group.uses_admission_points,
                f"the '{barrier.group_type}'",
            )
        if barrier.late_action != "leave_group":
            continue
        for group_type in [barrier.group_type, *barrier.also_leave]:
            group = groups.get(group_type)
            if isinstance(group, SimpleSyncGroup):
                _check_late_action(
                    barrier, group.below_quorum, f"the '{group_type}' grouper"
                )


def _check_top_up_wait(
    barrier, takes_newcomers, top_up_wait, uses_admission_points, groups_label
):
    """Reject a ``late_after`` barrier at which groups taking newcomers could wait for them without a limit."""
    if barrier.late_after is None or not takes_newcomers or top_up_wait is not None:
        return
    if uses_admission_points and not barrier.admission_point:
        return
    raise ValueError(
        f"GroupBarrier '{barrier.id}' has late_after, so it has no "
        f"max_wait_time, and {groups_label} groups wait there "
        "for newcomers while they are below their quorum"
        + (" or target_group_size" if uses_admission_points else "")
        + ". Pass top_up_wait to the grouper to limit that wait, or stop "
        "top-ups before this barrier with stop_top_ups=True on an earlier "
        "GroupBarrier."
    )


def _check_late_action(barrier, below_quorum, grouper_label):
    """Reject ``late_action="leave_group"`` on a group whose ``below_quorum`` is ``"fail"``."""
    if barrier.late_action == "leave_group" and below_quorum == "fail":
        raise ValueError(
            f"GroupBarrier '{barrier.id}' has late_action='leave_group', but "
            f"{grouper_label} has below_quorum='fail', so a late member would "
            "carry on alone while the members who were on time are failed. "
            "Pass below_quorum='continue_without_group', or late_action='fail'."
        )


def check_admission_points(barriers):
    """Check the admission points of groups that admit newcomers at them.

    Each :class:`SimpleGrouper` with ``use_admission_points=True``
    needs an admission point for its group type: a
    ``GroupBarrier(admission_point=True)``, a synchronized trial maker's
    trial preparation, or a :class:`Regrouper` with ``within`` that type.
    Without one its newcomers would never be admitted, so this warns.

    Parameters
    ----------
    barriers : iterable of Barrier
        The barriers in the timeline.

    Raises
    ------
    ValueError
        If an admission point of such a group type lacks ``newcomer_max_wait``
        (``sync_group_newcomer_max_wait`` for a trial maker).
    """
    barriers = list(barriers)
    group_types = {
        barrier.group_type
        for barrier in barriers
        if isinstance(barrier, SimpleGrouper) and barrier.use_admission_points
    }
    found = set()
    for barrier in barriers:
        if isinstance(barrier, Regrouper) and barrier.within in group_types:
            found.add(barrier.within)
        if not (
            isinstance(barrier, GroupBarrier)
            and barrier.admission_point
            and barrier.group_type in group_types
        ):
            continue
        found.add(barrier.group_type)
        if barrier.newcomer_max_wait is None:
            raise ValueError(
                f"{barrier._admission_point_owner} admits newcomers to "
                f"'{barrier.group_type}' groups, whose grouper uses "
                f"use_admission_points=True, so pass "
                f"{barrier._newcomer_max_wait_option}: the longest a newcomer "
                "may wait for it, in seconds from joining, before they are "
                "turned away."
            )
    for group_type in sorted(group_types - found):
        warnings.warn(
            f"The grouper of '{group_type}' groups uses "
            "use_admission_points=True, but the timeline has no "
            "admission point for them, so newcomers would never be admitted. "
            "Add GroupBarrier(admission_point=True, ...), a synchronized trial "
            f"maker with sync_group_type='{group_type}', or a Regrouper within "
            "that group type.",
            UserWarning,
            stacklevel=2,
        )


def group_seats(group) -> Dict[int, int]:
    """Return ``{participant_id: seat}`` for everyone who has been admitted to ``group``.

    Seats number members in the order they were first admitted. Links are
    kept when members leave, so seats never change while the group exists,
    and pages can refer to members without their IDs. Pending members get a
    seat once admitted, and members turned away never get one.
    """
    seats = {}
    links = sorted(
        (link for link in group.participant_links if link.admitted_at is not None),
        key=lambda link: (link.admitted_at, link.id is None, link.id or 0),
    )
    for link in links:
        seats.setdefault(link.participant_id, len(seats))
    return seats


def leave_group(group_type: str, reason: RemovalReason = "finished"):
    """Return a timeline step that takes the participant out of their ``group_type`` group.

    For example, put ``leave_group("cohort")`` after a player's last round,
    so that cohort members who are still playing, and any
    :class:`Regrouper` pairing them, don't wait for them. The step does
    nothing if the participant is in no group of that type.

    Parameters
    ----------
    group_type
        The type of the group to leave.
    reason
        Passed to :meth:`SyncGroup.remove_participant`. Leaving with the
        default, ``"finished"``, doesn't dissolve the group by itself, even
        if it leaves the group below its quorum; but the group's next
        :class:`GroupBarrier` can still dissolve it then, unless it is
        waiting for newcomers (see :ref:`groups_below_quorum`).

    Returns
    -------
    CodeBlock
    """
    if reason not in REMOVAL_REASONS:
        raise ValueError(f"reason must be one of {REMOVAL_REASONS}, got {reason!r}.")

    def _leave(participant):
        group = participant.active_sync_groups.get(group_type)
        if group is not None:
            group.remove_participant(participant, reason=reason)

    return CodeBlock(_leave)


@register_table
class SyncGroup(SQLBase, SQLMixin):
    """
    A SyncGroup represents a group of participants that are synchronized at various points in the experiment.
    Such groups are created by Groupers and synchronized by GroupBarriers.

    Attributes
    ----------

    leader : Participant
        The leader of the SyncGroup. This can be reassigned by logic such as ``group.leader = participant``.
    """

    __tablename__ = "sync_group"

    group_type = Column(String)
    active = Column(Boolean, default=True)
    end_time = Column(DateTime)
    last_barrier_pass_time = Column(DateTime, nullable=True)
    # No foreign key, so writing the group, for example to mark it
    # ``dissolving``, doesn't wait for a request that holds the leader's row.
    leader_id = Column(Integer)
    # Dissolution is queued because a member's row was busy; nobody has been
    # removed yet, and the barrier poller dissolves the group all at once.
    dissolving = Column(Boolean, default=False)
    # The grouper that formed the group. For a Regrouper, also the split that
    # formed it, shared by that split's other groups, and with ``within``, the
    # group it regrouped within.
    grouper_id = Column(String, index=True)
    within_group_id = Column(Integer, index=True)
    split_id = Column(String)
    # Each synchronized trial maker's runs, by trial maker id, one dict per
    # run with the group's choices (see ``psynet.trial.main._current_group_run``).
    trial_maker_runs = Column(PythonDict, default=lambda: {})

    participant_links = relationship(
        "ParticipantLinkSyncGroup",
        cascade="all, delete-orphan",
    )

    n_active_participants = Column(Integer)

    #: Whether newcomers may join; only :class:`SimpleSyncGroup` takes top-ups.
    accepts_top_ups = False
    #: When the group stopped accepting top-ups; see :class:`SimpleSyncGroup`.
    top_ups_stopped_at = None
    #: Quorum and below-quorum policy; only :class:`SimpleSyncGroup` sets them.
    quorum = None
    below_quorum = None
    #: When newcomers are admitted and how many an admission point waits
    #: for; only :class:`SimpleSyncGroup` takes newcomers.
    uses_admission_points = False
    target_group_size = None

    def stop_top_ups(self):
        """Stop newcomers joining this group; a no-op for groups that never take them."""

    def _stop_top_ups(self, barrier=None):
        """Stop newcomers joining this group; a no-op for groups that never take them."""

    @property
    def participants(self) -> List[Participant]:
        """Read-only list of participants currently in the group (links with ``active=True``).

        Includes pending members (see :attr:`pending_participants`); use
        :attr:`active_participants` for the admitted ones still working.
        Use ``group.add_participant(participant)`` to add a participant.
        """
        links = [
            link for link in self.participant_links if getattr(link, "active", True)
        ]
        _load_link_participants(links)
        return _ReadOnlyParticipantList(link.participant for link in links)

    def add_participant(self, participant: Participant):
        """Add a participant to the group as an admitted member (creates an active link).

        If an active member already has the newcomer's derived pseudonym and
        this is the newcomer's first group, the newcomer is given a free one,
        so members can tell each other apart. Pseudonyms set with
        :meth:`~psynet.participant.Participant.set_pseudonym` are kept, and
        later groups never rename anyone, so a pseudonym stays the same once
        others have seen it.
        """
        self._add_link(participant, admitted=True)

    def _add_link(self, participant: Participant, *, admitted: bool):
        """Link ``participant`` to the group, admitted or pending (see :attr:`pending_participants`)."""
        self._give_distinct_pseudonym(participant)
        _forget_active_sync_group(participant)
        if self.group_type in (participant.ungrouped_group_types or []):
            participant.ungrouped_group_types = [
                t for t in participant.ungrouped_group_types if t != self.group_type
            ]
        now = timenow()
        # Setting ``sync_group`` also appends to ``participant_links``, and lets
        # ``participant.active_sync_groups`` see the group before a flush.
        ParticipantLinkSyncGroup(
            participant=participant,
            sync_group=self,
            active=True,
            arrival_time=now,
            admitted_at=now if admitted else None,
            admission_points_passed=0,
        )
        if admitted:
            _notify_membership_change(self, newcomer=participant)

    def _working_links(self, admitted: bool) -> list:
        """Return the active links of working members, admitted or pending, in join order."""
        links = sorted(
            (
                link
                for link in self.participant_links
                if getattr(link, "active", True)
                and (link.admitted_at is not None) == admitted
            ),
            key=lambda link: (link.id is None, link.id or 0),
        )
        _load_link_participants(links)
        return [
            link
            for link in links
            if not link.participant.failed and link.participant.status == "working"
        ]

    @property
    def active_participants(self) -> List[Participant]:
        """The admitted members who are still working, in the order they joined.

        Barriers wait for them, the quorum counts them, the leader is one of
        them, and :class:`~psynet.group_prompt.GroupPrompt` draws them.
        Pending members (see :attr:`pending_participants`) are not included.
        """
        return [link.participant for link in self._working_links(admitted=True)]

    @property
    def pending_participants(self) -> List[Participant]:
        """Members who have joined but not been admitted yet, in the order they joined.

        Only a grouper with ``use_admission_points=True`` makes
        pending members: each holds a seat until the group's next admission
        point admits them or turns them away (see
        :ref:`sync-admission-points`).
        """
        return [link.participant for link in self._working_links(admitted=False)]

    def _active_link(self, participant) -> Optional["ParticipantLinkSyncGroup"]:
        """Return ``participant``'s active link to the group, or ``None``."""
        return next(
            (
                link
                for link in self.participant_links
                if link.active
                and (
                    link.participant_id == participant.id
                    or (link.participant_id is None and link.participant is participant)
                )
            ),
            None,
        )

    def _is_pending(self, participant) -> bool:
        """Return whether ``participant`` is a pending member of the group."""
        link = self._active_link(participant)
        return link is not None and link.admitted_at is None

    def _admit(self, participants, barrier_visits=None):
        """Admit pending members, recording the admitting visit if there is one."""
        now = timenow()
        for participant in participants:
            self._active_link(participant).admitted_at = now
            visit = (barrier_visits or {}).get(participant.id)
            if visit is not None:
                visit.admitted = True
        if participants:
            self.check_numbers()
            self.check_leader()
            _notify_membership_change(self)

    def _turn_away_pending(self, barrier=None):
        """Remove every pending member as ``"not_admitted"``; see :meth:`_turn_away`."""
        for participant in self.pending_participants:
            self._turn_away(participant, barrier)

    def _turn_away(self, participant, barrier=None):
        """Remove a pending member as ``"not_admitted"`` and tell them on their next page.

        They did nothing wrong, so they are never failed. The notice comes
        from ``barrier``'s ``on_arrival_message`` with ``kind="not_admitted"``,
        or the default one.
        """
        link = self._active_link(participant)
        if link is None or link.admitted_at is not None:
            return
        logger.info(
            "Sync group %s turns away pending member %s.", self.id, participant.id
        )
        link.active = False
        link.removal_reason = "not_admitted"
        link.removal_time = timenow()
        _forget_active_sync_group(participant)
        message = (
            default_group_barrier_arrival_message
            if barrier is None
            else barrier._call_arrival_message
        )
        try:
            text = message(
                kind="not_admitted",
                waiting_count=0,
                group_size=len(self.active_participants),
                participant=participant,
                group=self,
            )
        except Exception as err:
            if is_transient_transaction_error(err):
                raise
            logger.exception(
                "Could not make the not-admitted notice for participant %s.",
                participant.id,
            )
            return
        if text:
            _set_next_page_notice(participant, text)

    def _give_distinct_pseudonym(self, participant):
        """Store a free pseudonym for ``participant`` if an admitted or pending member has theirs.

        Only in the participant's first group; see :meth:`add_participant`.
        """
        # Cached for this transaction, so forming a large group stays linear.
        transaction = db.session().get_transaction()
        cached = self.__dict__.get("_pseudonym_keys")
        if cached is not None and transaction is not None and cached[0] is transaction:
            taken = cached[1]
        else:
            others = [
                p
                for p in self.active_participants + self.pending_participants
                if p.id != participant.id
            ]
            taken = {(p.pseudonym.color, p.pseudonym.animal) for p in others}
            self.__dict__["_pseudonym_keys"] = (transaction, taken)
        pseudonym = participant.pseudonym
        keys = (pseudonym.color, pseudonym.animal)
        first_group = not participant.sync_group_links
        # Before the first group, stored keys can only come from set_pseudonym.
        derived = (
            participant.pseudonym_color is None or participant.pseudonym_animal is None
        )
        if keys in taken and first_group and derived:
            from .experiment import get_experiment

            replacement = get_experiment().pseudonym_scheme.assign_distinct(
                participant, taken
            )
            if replacement is not None:
                participant.set_pseudonym(*replacement)
                keys = replacement
        taken.add(keys)

    leader = relationship(
        Participant,
        primaryjoin=lambda: foreign(SyncGroup.leader_id) == Participant.id,
    )

    def check_leader(self):
        """Make the lowest-id active member leader if the leader has left."""
        active_participants = sorted(self.active_participants, key=lambda p: p.id)
        if len(active_participants) == 0:
            self.leader = None
        elif self.leader not in active_participants:
            self.leader = active_participants[0]

    @property
    def active_followers(self):
        return [p for p in self.active_participants if p != self.leader]

    @classmethod
    def get_active_group(
        cls,
        participant: Participant,
        group_type: str,
    ) -> "SyncGroup":
        return participant.active_sync_groups[group_type]

    def close(self):
        """End the group, turning away its pending members as ``"not_admitted"``."""
        self._turn_away_pending()
        self.active = False
        self.end_time = timenow()
        for participant in self.participants:
            _forget_active_sync_group(participant)

    def check_numbers(self):
        self.n_active_participants = len(self.active_participants)

    def remove_participant(self, participant: Participant, reason: RemovalReason):
        """Remove a participant from the group.

        Parameters
        ----------
        participant
            The member to remove.
        reason
            Why they left, stored on their link and returned by
            :meth:`~psynet.participant.Participant.sync_group_removal_reason`.
            A :class:`~psynet.group_prompt.GroupPrompt` that still draws them
            for their answer labels them "(left)" unless the reason is
            ``"moved_on"`` or ``"finished"`` (see :ref:`sync-showing-the-group`).

            - ``"removed_by_experimenter"``: removed without a more specific
              reason, for example from the dashboard.
            - ``"left_experiment"``, ``"waited_too_long"`` or
              ``"group_dissolved"``: they dropped out.
            - ``"late"``: a barrier removed them for being late (with any
              ``late_action``).
            - ``"moved_on"``: for a member who left at a :class:`Regrouper`,
              for their next group or to sit the round out. A pair a :class:`SimpleGrouper`
              formed isn't dissolved, failing the partner, when the first
              member reaches a :class:`Regrouper`.
            - ``"finished"``: for a member who has played their part, such as
              a player leaving a cohort after their last round.
              The members finishing their own last rounds aren't told that too
              few remained.

            PsyNet itself records ``"not_admitted"`` for a pending member it
            turns away (see :attr:`pending_participants`).

            Leaving with ``"finished"`` or ``"moved_on"`` doesn't dissolve
            the group by itself; other reasons can. Either way, the group's
            next :class:`GroupBarrier` can dissolve a group left below its
            quorum. See :ref:`groups_below_quorum` for the full rule.
        """
        self._remove_without_quorum_check(participant, reason)

    def _remove_without_quorum_check(self, participant, reason: RemovalReason):
        """Remove ``participant`` as :meth:`remove_participant` does, but never dissolve the group below its quorum."""
        if reason not in REMOVAL_REASONS:
            raise ValueError(
                f"reason must be one of {REMOVAL_REASONS}, got {reason!r}."
            )
        _forget_active_sync_group(participant)
        for link in self.participant_links:
            is_member = link.participant_id == participant.id or (
                link.participant_id is None and link.participant is participant
            )
            if is_member and link.active:
                link.active = False
                link.removal_reason = reason
                link.removal_time = timenow()
                if reason == "late":
                    link.removed_on_page = participant.page_uuid
                _record_leaving_the_round(self, participant, reason)
        self.check_numbers()
        _notify_membership_change(self)
        if self.n_active_participants == 0 and not self.accepts_top_ups:
            self.close()
        else:
            self.check_leader()

    def _members_who_left_since(self, time) -> List[Participant]:
        """Return the members who left the group at or after ``time``, ordered by participant ID.

        A :class:`GroupBarrier` passes them to ``on_release`` as ``left``.
        """
        return sorted(
            (
                link.participant
                for link in self.participant_links
                if not link.active
                and link.removal_time is not None
                and (time is None or link.removal_time >= time)
            ),
            key=lambda participant: participant.id,
        )

    def rounds(self, module_id: str) -> List["SyncGroupRound"]:
        """Return the group's rounds in a module, in round order.

        Each round is a :class:`SyncGroupRound`, whose ``var`` holds what the
        round stored and ``trials`` its trials.
        It also works once the group has ended or dissolved, for example to
        show a debrief after the game::

            sentences = [r.var.get("sentence") for r in group.rounds("story")]

        Parameters
        ----------
        module_id
            The ``id_`` of the module whose rounds to return, as in
            ``participant.module_id``.

        Returns
        -------
        list of SyncGroupRound
            Ordered by ``number``, then by creation; empty if the group has
            played no round in the module.
        """
        return (
            SyncGroupRound.query.filter_by(module_id=module_id, sync_group_id=self.id)
            .order_by(SyncGroupRound.number, SyncGroupRound.id)
            .all()
        )

    def dissolve_if_below_quorum(self):
        """Dissolve the group if it fell below its quorum; groups without a quorum never do."""

    def _dissolve(self):
        """Remove every active member at once, failing them if the group says so.

        Members' rows are locked without waiting; rows this transaction
        already holds, such as the requester's own, count as free. If another
        request holds any member's row, nobody is removed: the group is marked
        ``dissolving`` and the barrier poller tries again on its next pass.
        Waiting here could deadlock with that member's request, which holds
        their row and then needs this group's row.

        Each member leaves this group as ``"group_dissolved"`` before being
        failed, as in :meth:`GroupBarrier._remove_late_participants`, because
        failing removes a member from the groups they are still in as
        ``"left_experiment"``.

        The rounds that members are still playing get their
        :class:`SyncGroupRound`'s ``dissolved_at`` (see :func:`_mark_rounds_dissolved`),
        read under the members' row locks, so a member's cue either comes
        before the dissolution or sees it. Pending members are turned away
        as ``"not_admitted"``.

        Returns
        -------
        list of Participant
            The members removed, or an empty list if the dissolution waits.
        """
        self._dissolving_below_quorum = True
        try:
            removed = _lock_all_participants(list(self.active_participants))
            if removed is None:
                if not self.dissolving:
                    logger.debug(
                        "Dissolving sync group %s waits for a member's request.",
                        self.id,
                    )
                self.dissolving = True
                return []
            rounds = _open_rounds(self, removed)
            _mark_rounds_dissolved(rounds)
            group_size = len(group_seats(self))
            fail = (self.below_quorum or "fail") == "fail"
            self._turn_away_pending()
            for participant in removed:
                self._remove_without_quorum_check(participant, "group_dissolved")
                if fail:
                    participant.fail("sync group below quorum")
                else:
                    _tell_group_ended(participant, group_size)
            self.check_numbers()
            self.dissolving = False
            if self.n_active_participants == 0:
                self.close()
        finally:
            self._dissolving_below_quorum = False
        return removed


class SimpleSyncGroup(SyncGroup):
    """
    A SyncGroup that is created by a SimpleGrouper.
    """

    # Queries for SyncGroup load these columns too, rather than in a second
    # query when one is first read.
    _load_with_base_class = True

    initial_group_size = Column(Integer)
    max_group_size = Column(Integer)
    #: How many active members the group needs to keep going.
    quorum = Column(Integer)
    accepts_top_ups = Column(Boolean)
    #: When the group stopped accepting top-ups, or ``None`` while it accepts
    #: them or if it never did.
    top_ups_stopped_at = Column(DateTime)
    #: Seconds a group below quorum waits for newcomers; see ``SimpleGrouper(top_up_wait=...)``.
    top_up_wait = Column(Float)
    #: When the group last fell below its quorum while accepting newcomers.
    below_quorum_since = Column(DateTime)
    #: What happens to members when the group dissolves below quorum: ``"fail"``
    #: or ``"continue_without_group"``.
    below_quorum = Column(String, default="fail")
    #: Whether newcomers wait as pending members for an admission point
    #: instead of joining at once; see ``SimpleGrouper(use_admission_points=...)``.
    uses_admission_points = Column(Boolean, default=False)
    #: How many members an admission point waits for, up to ``top_up_wait``;
    #: see ``SimpleGrouper(target_group_size=...)``.
    target_group_size = Column(Integer)

    def remove_participant(self, participant: Participant, reason: RemovalReason):
        super().remove_participant(participant, reason=reason)
        if reason not in _KEEPS_GROUP_REASONS:
            self.dissolve_if_below_quorum()

    def check_numbers(self):
        super().check_numbers()
        if self.n_active_participants >= (self.quorum or 0):
            self.below_quorum_since = None
        elif self.below_quorum_since is None:
            self.below_quorum_since = timenow()

    def stop_top_ups(self):
        """Stop newcomers joining this group, so that it no longer waits for them.

        For a group formed with ``join_existing_groups=True``, for example once
        the game has started, so nobody joins it under way. From then on it
        is treated as a group without top-ups (see
        :ref:`groups_below_quorum`); its pending members are turned away
        as ``"not_admitted"``, and a group already below its
        quorum is dissolved, usually at once. :ref:`groups_below_quorum` lists
        the other ways top-ups stop.
        """
        self._stop_top_ups()

    def _stop_top_ups(self, barrier=None):
        """Stop top-ups as :meth:`stop_top_ups` does; ``barrier`` gives the turned-away notice."""
        if not self.accepts_top_ups:
            return
        self._close_to_top_ups(barrier)
        self.check_numbers()
        self.dissolve_if_below_quorum()

    def _close_to_top_ups(self, barrier=None):
        """Record that newcomers can no longer join and turn away pending members, without dissolving the group."""
        self.accepts_top_ups = False
        self.top_ups_stopped_at = timenow()
        self._turn_away_pending(barrier)

    def dissolve_if_below_quorum(self):
        """Dissolve a group without top-ups that fell below its quorum.

        If a member is busy in another request, the barrier poller dissolves
        the group shortly after instead; see :meth:`SyncGroup._dissolve`.
        """
        if (
            getattr(self, "_dissolving_below_quorum", False)
            or self.accepts_top_ups
            or self.n_active_participants >= self.quorum
        ):
            return
        self._dissolve()


@register_table
class SyncGroupRound(SQLBase, SQLMixin):
    """One round that a sync group plays together, linking the members' trials in it.

    A round is made either by :meth:`~psynet.trial.main.Trial.cue` for a trial
    class with ``sync_group_type`` (``trial_maker_id`` is ``None``), when the
    round's first member cues it, or by a trial maker with
    ``sync_group_type`` each time it prepares the group's trials. See
    :ref:`sync-group-rounds` and :ref:`rounds of a trial maker
    <trial-maker-rounds>` for when rounds open and close.

    Attributes
    ----------
    sync_group_id : int
        The :class:`SyncGroup` playing the round.
    module_id : str
        The module the round was played in; for a trial maker, its ``id``.
    trial_maker_id : str or None
        The trial maker that made the round, or ``None`` for cued rounds.
    number : int
        The round's number, counted from 0 for each group, separately in each
        module of cued trials and in each trial maker. It equals
        ``sync_group_round`` on the round's trials.
    definition : dict
        For cued rounds, the definition shared by every trial in the round,
        set by its first cue. ``None`` for trial makers' rounds, whose trials
        keep their own definitions.
    var :
        A variable store for the group's results in the round, for example
        those that a :class:`GroupBarrier`'s ``on_release`` computes.
    closed_at : datetime or None
        When the round closed: when a :class:`GroupBarrier` in the round's
        trials released the group, or, for a trial maker's round that has no
        such barrier, when the group's next trials were prepared. A closed
        cued round takes no members who have no trial in it.
    dissolved_at : datetime or None
        When the group dissolved during the round, or ``None`` if it didn't.
        Set when the group dissolves (see :ref:`groups_below_quorum`) while
        a member still in the group is in their trial in this round (the
        trial's ``complete`` is ``False``) and the round is not closed. So a
        round the group finished stays ``None`` even if a member is still on
        a page after the barrier, and so does a round whose remaining
        members' trials had all ended before the group dissolved. Written
        under the members' row locks, so it is never set on a closed round.
    trials : list of Trial
        The members' trials in the round, including failed ones.
    """

    __tablename__ = "sync_group_round"

    # Unused SharedMixin columns.
    property1 = None
    property2 = None
    property3 = None
    property4 = None
    property5 = None
    details = None

    # No foreign key, as on Trial.sync_group_id.
    sync_group_id = Column(Integer, index=True)
    module_id = Column(String, index=True)
    trial_maker_id = Column(String)
    number = Column(Integer)
    definition = Column(PythonObject)
    closed_at = Column(DateTime)
    dissolved_at = Column(DateTime)

    trials = relationship(
        "psynet.trial.main.Trial",
        back_populates="group_round",
        order_by=lambda: _trial_class().id,
    )

    __table_args__ = (
        # Concurrent first cues rely on the first to create each cued round
        # once (see _find_or_create). Cues outside a module have no
        # module_id, which must still be unique, so they get their own index;
        # an expression index on the module_id would break schema reflection.
        Index(
            "ix_sync_group_round_cued",
            sync_group_id,
            module_id,
            number,
            unique=True,
            postgresql_where=text("trial_maker_id IS NULL AND module_id IS NOT NULL"),
        ),
        Index(
            "ix_sync_group_round_cued_outside_module",
            sync_group_id,
            number,
            unique=True,
            postgresql_where=text("trial_maker_id IS NULL AND module_id IS NULL"),
        ),
        Index(
            "ix_sync_group_round_trial_maker",
            sync_group_id,
            trial_maker_id,
            number,
            unique=True,
            postgresql_where=text("trial_maker_id IS NOT NULL"),
        ),
    )

    @property
    def sync_group(self) -> Optional[SyncGroup]:
        """The :class:`SyncGroup` playing the round."""
        return db.session.get(SyncGroup, self.sync_group_id)

    @classmethod
    def _find_or_create(cls, group_id, module_id, number):
        """Return the group's cued round with these keys and whether this call created it.

        Parallel requests may create the same round, for example two members'
        first cues, so this inserts it with ``ON CONFLICT DO NOTHING``. A
        request that conflicts waits for the creator's transaction to end and
        then loads its round, so only the creator sees it as new and fills it in.
        """
        values = dict(
            sync_group_id=group_id,
            module_id=module_id,
            number=number,
            type=cls.__mapper__.polymorphic_identity,
        )
        db.session.flush()
        inserted = db.session.execute(
            pg_insert(cls).values(**values).on_conflict_do_nothing().returning(cls.id)
        ).scalar()
        query = cls.query.filter_by(
            sync_group_id=group_id, module_id=module_id, number=number
        ).filter(cls.trial_maker_id.is_(None))
        return query.populate_existing().one(), inserted is not None

    def _close(self, stayed_trials):
        """Close the round, if still open, and record ``"stayed"`` on ``stayed_trials``."""
        if self.closed_at is None:
            self.closed_at = timenow()
        for trial in stayed_trials:
            trial.sync_group_outcome = "stayed"


def _trial_class():
    """Return :class:`~psynet.trial.main.Trial`, which imports this module."""
    from .trial.main import Trial

    return Trial


def _record_leaving_the_round(group, participant, reason):
    """Record why the participant left ``group`` on the round they are playing in it, if any.

    That is their trial in a round of ``group`` (see :func:`_round_trial`), if it
    is not complete yet and no barrier has released the group with them in
    it. Leaving after that, or between rounds, records nothing on the trial.
    """
    trial = _round_trial(group, participant)
    if (
        trial is not None
        and not trial.complete
        and trial.sync_group_outcome != "stayed"
    ):
        trial.sync_group_outcome = reason


def _open_rounds(group, participants):
    """Return the rounds of ``group`` in which ``participants`` have an unfinished trial.

    Expects the caller to hold the participants' row locks, and re-reads
    their current trials under them, so a trial that a member's request
    started or finished before the lock was taken is seen.
    """
    for participant in participants:
        db.session.refresh(participant, ["current_trial_id", "_current_trial"])
        if participant.current_trial is not None:
            db.session.refresh(
                participant.current_trial, ["complete", "sync_group_outcome"]
            )
    trials = [_round_trial(group, p) for p in participants]
    return list(
        {
            id(t.group_round): t.group_round
            for t in trials
            if t is not None and not t.complete
        }.values()
    )


def _mark_rounds_dissolved(rounds):
    """Record on each of ``rounds`` that its group dissolved, unless it is closed.

    Expects the caller to hold the members' row locks, and re-reads each
    round, so a release that another request committed first is seen.
    """
    db.session.flush()
    for group_round in rounds:
        db.session.refresh(group_round, ["closed_at", "dissolved_at"])
        if group_round.closed_at is None and group_round.dissolved_at is None:
            group_round.dissolved_at = timenow()


def _round_trial(group, participant):
    """Return the participant's current trial if it is in a round of ``group`` in this run of their module, else ``None``.

    A run is one ``ModuleState``, so a trial from an earlier module, or from
    an earlier run of the same module, as in a loop around the module, gives
    ``None``.
    """
    trial = participant.current_trial
    if (
        trial is None
        or trial.sync_group_id != group.id
        or trial.group_round is None
        or trial.module_state is not participant.module_state
    ):
        return None
    return trial


def _common_round(group, participants) -> Optional[SyncGroupRound]:
    """Return the round of ``group`` whose trial each of ``participants`` is in, or ``None``.

    That is a round shared by every participant's current trial, an
    unfinished trial of ``group`` in this run of their module (see
    :func:`_round_trial`), as at a barrier in ``show_trial``. Anywhere else,
    such as before the first cue, in ``show_feedback`` or after the loop,
    or if one participant isn't in that round, it is ``None``.
    """
    trials = [_round_trial(group, p) for p in participants]
    rounds = {None if t is None or t.complete else t.group_round for t in trials}
    if len(rounds) != 1 or None in rounds:
        return None
    return trials[0].group_round


class GroupDivergenceError(RuntimeError):
    """A group's members wait for each other at different group barriers, so none can pass.

    :func:`check_barriers` records it as an :class:`~psynet.error.ErrorRecord`
    and logs it (see
    :ref:`members at different barriers <rounds-group-barriers-in-loops>`);
    bot tests then fail with it (see :func:`fail_on_group_divergence`).
    """


def _divergence_token():
    """Return the SQL token of the :class:`~psynet.error.ErrorRecord` of a divergence.

    It names the group and the sorted ids of the barriers its members wait
    at, such as ``group-divergence-7:ready,submitted``, so a group that
    diverges again at other barriers is reported again. It aggregates over
    the rows of :func:`_divergence_candidates`, grouped by group.
    """
    barrier_id = BarrierInstance.barrier_id
    return func.concat(
        "group-divergence-",
        BarrierInstance.group_id,
        ":",
        func.array_to_string(
            func.array_agg(aggregate_order_by(distinct(barrier_id), barrier_id)), ","
        ),
    )


def _report_divergences():
    """Record and log each group whose members wait for each other at different barriers.

    Runs at the end of each :func:`check_barriers` sweep, after its visit
    checks, so whatever a release or time-out could do has been done. One
    statement (:func:`_divergence_candidates`) finds the groups where every
    active member waits at a barrier of the group and those waits span two
    or more barriers; only those get the full check
    (:func:`_divergence_message`). Each group is checked and recorded in its
    own transaction, so an error in one doesn't skip the others. A group's
    record carries the token from :func:`_divergence_token`, so a group with
    a record for the same barriers isn't checked again.
    """
    try:
        candidates = _divergence_candidates()
    except Exception:
        logger.warning("Failed to look for diverged sync groups.", exc_info=True)
        return
    for group_id, token in candidates:
        try:
            group = SyncGroup.query.get(group_id)
            divergence = None if group is None else _divergence_message(group)
            if divergence is None:
                db.session.rollback()
                continue
            message, participant_ids = divergence
            db.session.add(
                ErrorRecord(
                    GroupDivergenceError(message),
                    token=token,
                    participant_id=min(participant_ids),
                )
            )
            db.session.commit()
            logger.error(message)
        except Exception:
            db.session.rollback()
            logger.exception("Failed to check sync group %s for divergence.", group_id)


def _divergence_candidates() -> List[Tuple[int, str]]:
    """Return the ids and divergence tokens of active groups whose members all wait at two or more of the group's barriers.

    Dissolving groups and groups that already have a divergence record for
    the same barriers are left out. One statement, in its own session.
    """
    member = and_(
        ~Participant.failed,
        Participant.status == "working",
    )
    n_members = (
        select(func.count())
        .select_from(ParticipantLinkSyncGroup)
        .join(Participant, Participant.id == ParticipantLinkSyncGroup.participant_id)
        .where(
            ParticipantLinkSyncGroup.sync_group_id == BarrierInstance.group_id,
            ParticipantLinkSyncGroup.active.is_(True),
            ParticipantLinkSyncGroup.admitted_at.isnot(None),
            member,
        )
        .correlate(BarrierInstance)
        .scalar_subquery()
    )
    candidates = (
        select(BarrierInstance.group_id, _divergence_token().label("token"))
        .join(
            ParticipantLinkBarrier,
            ParticipantLinkBarrier.barrier_instance_id == BarrierInstance.id,
        )
        .join(SyncGroup, SyncGroup.id == BarrierInstance.group_id)
        .join(
            ParticipantLinkSyncGroup,
            and_(
                ParticipantLinkSyncGroup.sync_group_id == BarrierInstance.group_id,
                ParticipantLinkSyncGroup.participant_id
                == ParticipantLinkBarrier.participant_id,
                ParticipantLinkSyncGroup.active.is_(True),
                ParticipantLinkSyncGroup.admitted_at.isnot(None),
            ),
        )
        .join(Participant, Participant.id == ParticipantLinkBarrier.participant_id)
        .where(
            ParticipantLinkBarrier.released.is_(False),
            member,
            SyncGroup.active.is_(True),
            SyncGroup.dissolving.isnot(True),
        )
        .group_by(BarrierInstance.group_id)
        .having(
            and_(
                func.count(func.distinct(BarrierInstance.barrier_id)) >= 2,
                func.count(func.distinct(ParticipantLinkBarrier.participant_id))
                == n_members,
            )
        )
        .subquery()
    )
    query = (
        select(candidates.c.group_id, candidates.c.token)
        .where(~exists().where(ErrorRecord.token == candidates.c.token))
        .order_by(candidates.c.group_id)
    )
    with Session(bind=db.engine) as session:
        return [tuple(row) for row in session.execute(query)]


def _divergence_message(group) -> Optional[Tuple[str, Set[int]]]:
    """Describe how ``group`` can't pass any of its barriers, or return ``None`` if it can.

    Returns the message and the ids of the members it names.

    That is when the group has its quorum and every active member waits at
    a :class:`GroupBarrier` of the group, but none of those barriers has
    them all, as when a barrier is inside a ``conditional`` that only some
    members take. Each barrier waits for the members at the others, so
    only ``late_after`` or ``max_wait_time`` can end the wait. The members
    and their waits are read in one statement, so they are consistent with
    each other. Pending members (see :attr:`SyncGroup.pending_participants`)
    don't count: barriers don't wait for them.
    """
    group_instances = select(BarrierInstance.id).where(
        BarrierInstance.group_id == group.id
    )
    rows = db.session.execute(
        select(ParticipantLinkSyncGroup.participant_id, ParticipantLinkBarrier)
        .join(Participant, Participant.id == ParticipantLinkSyncGroup.participant_id)
        .outerjoin(
            ParticipantLinkBarrier,
            and_(
                ParticipantLinkBarrier.participant_id
                == ParticipantLinkSyncGroup.participant_id,
                ParticipantLinkBarrier.released.is_(False),
                ParticipantLinkBarrier.barrier_instance_id.in_(group_instances),
            ),
        )
        .where(
            ParticipantLinkSyncGroup.sync_group_id == group.id,
            ParticipantLinkSyncGroup.active.is_(True),
            ParticipantLinkSyncGroup.admitted_at.isnot(None),
            Participant.failed.is_(False),
            Participant.status == "working",
        )
    ).all()
    members = {participant_id for participant_id, _ in rows}
    if len(members) < (group.quorum or 1) or any(link is None for _, link in rows):
        return None
    waits = {}
    for _, link in rows:
        barrier = link.barrier_instance.get_barrier()
        if isinstance(barrier, GroupBarrier):
            waits.setdefault(barrier.id, (barrier, []))[1].append(link)
    if (
        len(waits) < 2
        or {link.participant_id for _, links in waits.values() for link in links}
        != members
        or any(
            {link.participant_id for link in links} == members
            for _, links in waits.values()
        )
    ):
        return None
    message = (
        f"The members of '{group.group_type}' group {group.id} wait for each "
        "other at different barriers, so none can pass: "
        + "; ".join(
            f"GroupBarrier '{barrier_id}' has participants "
            + ", ".join(str(i) for i in sorted(link.participant_id for link in links))
            for barrier_id, (_, links) in sorted(waits.items())
        )
        + ". Each GroupBarrier waits for every member of its group, so put the "
        "barriers where every member reaches them in the same order, or have "
        "members leave the group (leave_group) before their paths diverge. "
        "Until late_after or max_wait_time moves someone on, nobody passes."
    )
    return message, members


@contextmanager
def fail_on_group_divergence():
    """Raise :class:`GroupDivergenceError` after the block if :func:`check_barriers` recorded one during it.

    Bot tests run inside it, so a divergence fails ``psynet test local``
    with its message even though the poller found it in another process.
    Records from before the block, such as an earlier run against the same
    server, are ignored. The error is raised even if the block raised, as
    bots stuck at diverged barriers fail on ``max_wait_time``.
    """
    with transaction():
        start = db.session.query(func.max(ErrorRecord.id)).scalar() or 0
    try:
        yield
    finally:
        with transaction():
            messages = [
                message
                for (message,) in db.session.query(ErrorRecord.message)
                .filter(
                    ErrorRecord.kind == GroupDivergenceError.__name__,
                    ErrorRecord.id > start,
                )
                .order_by(ErrorRecord.id)
            ]
        if messages:
            raise GroupDivergenceError("\n".join(messages))


def _top_up_wait_over(group, members, barrier_id, *, below_target=False) -> bool:
    """Return whether a group has waited its ``top_up_wait`` for newcomers at barrier ``barrier_id``.

    The wait starts once the group is below its quorum (or, with
    ``below_target``, at once) and all ``members`` it would pass with have
    reached the barrier, so it doesn't run while they are still on earlier
    pages.
    """
    top_up_wait = getattr(group, "top_up_wait", None)
    below_quorum_since = getattr(group, "below_quorum_since", None)
    if top_up_wait is None or (below_quorum_since is None and not below_target):
        return False
    visits = [member.active_barriers.get(barrier_id) for member in members]
    if any(visit is None or visit.released for visit in visits):
        return False
    starts = [visit.arrival_time for visit in visits]
    if not below_target:
        starts.append(below_quorum_since)
    if not starts:
        return False
    since = max(starts)
    return (timenow() - since).total_seconds() >= top_up_wait


def _groups_left_on_failure(participant, group, reason):
    """List the groups a failing ``participant`` leaves: ``group`` with ``reason``, then each other active group as ``"left_experiment"``."""
    return [(group, reason)] + [
        (other, "left_experiment")
        for other in participant.active_sync_groups.values()
        if other.id != group.id
    ]


def _lock_free_participants(participants):
    """Lock participants' rows without waiting and return the free ones.

    ``SKIP LOCKED`` leaves out rows another transaction holds; rows this
    transaction already holds count as free. Code that fails or removes
    *other* participants uses this, because their own requests lock their
    row first and may then need a sync group row this transaction holds.
    The returned participants are refreshed, and any who failed or left
    meanwhile are dropped.
    """
    locked = _skip_locked_participant_ids(participants)
    return _still_working([p for p in participants if p.id in locked])


def _lock_all_participants(participants):
    """Lock every participant's row without waiting, or return ``None`` if another transaction holds one.

    Like :func:`_lock_free_participants`, but all or nothing. The locks are
    taken in a savepoint, rolled back if any row was skipped, so the free
    members' requests are not held up until this transaction ends. Opening
    the savepoint flushes pending changes, so rolling it back keeps them.
    """
    with db.session.begin_nested() as savepoint:
        locked = _skip_locked_participant_ids(participants)
        if any(participant.id not in locked for participant in participants):
            savepoint.rollback()
            return None
    return _still_working(participants)


def _skip_locked_participant_ids(participants):
    """Lock participants' rows with ``SKIP LOCKED`` and return the ids locked."""
    if not participants:
        return set()
    ids = sorted({participant.id for participant in participants})
    return set(
        db.session.execute(
            select(Participant.id)
            .where(Participant.id.in_(ids))
            .order_by(Participant.id)
            .with_for_update(skip_locked=True)
        ).scalars()
    )


def _still_working(participants):
    """Refresh locked participants and drop any who failed or left meanwhile."""
    working = []
    for participant in participants:
        db.session.refresh(participant, ["failed", "status", "page_uuid"])
        if not participant.failed and participant.status == "working":
            working.append(participant)
    return working


def _insert_values_from_state(record) -> dict:
    """Build insert values from an ORM instance state."""
    state = sa_inspect(record)
    mapper = state.mapper
    if mapper.polymorphic_on is not None:
        discriminator = mapper.polymorphic_on.key
        if getattr(record, discriminator) is None:
            setattr(record, discriminator, mapper.polymorphic_identity)
    column_keys = {column.key for column in mapper.columns}
    return {key: value for key, value in state.dict.items() if key in column_keys}


@register_table
class BarrierDefinition(SQLBase, SQLMixin):
    """Identify a public barrier waiting area without storing mutable visits."""

    __tablename__ = "barrier"

    id = Column(String, primary_key=True)
    barrier_class = Column(PythonClass)
    created_at = Column(DateTime, default=timenow)

    instances = relationship("BarrierInstance", back_populates="definition")

    @classmethod
    def ensure_exists(cls, barrier_id: str, barrier_class):
        """Register a definition in the caller's transaction."""
        record = cls(
            id=barrier_id,
            barrier_class=barrier_class,
            created_at=timenow(),
        )
        values = _insert_values_from_state(record)
        db.session.execute(
            pg_insert(cls)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        existing = cls.query.get(barrier_id)
        if existing.barrier_class is not barrier_class:
            raise ValueError(
                f"Barrier ID '{barrier_id}' already identifies "
                f"{existing.barrier_class.__name__}, not {barrier_class.__name__}. "
                "Use a different barrier ID."
            )


@register_table
class BarrierInstance(SQLBase, SQLMixin):
    """Persist one stable barrier behavior for a coordination visit.

    At most one active row exists per ``(barrier_id, group_id)``. Ungrouped
    barriers (``group_id`` is null), including groupers, share one active
    waiting pool per barrier ID.
    """

    __tablename__ = "barrier_instance"

    id = Column(String, primary_key=True)
    barrier_id = Column(String, ForeignKey("barrier.id"), index=True)
    group_id = Column(Integer, ForeignKey("sync_group.id"), nullable=True, index=True)
    active = Column(Boolean, default=True, index=True)
    spec = deferred(Column(Text))
    behavior_hash = Column(String(64))
    # The release time last sent to this pool's waiters, in epoch seconds
    # (see ``SimpleGrouper(start_short_after=...)``).
    announced_release_time = Column(Float)

    definition = relationship("BarrierDefinition", back_populates="instances")
    group = relationship("SyncGroup")
    participant_links = relationship(
        "ParticipantLinkBarrier", back_populates="barrier_instance"
    )
    __table_args__ = (
        Index(
            "ix_barrier_instance_active_group",
            "barrier_id",
            "group_id",
            unique=True,
            postgresql_where=text("active IS true AND group_id IS NOT NULL"),
        ),
        Index(
            "ix_barrier_instance_active_ungrouped",
            "barrier_id",
            unique=True,
            postgresql_where=text("active IS true AND group_id IS NULL"),
        ),
    )

    @classmethod
    def for_arrival(cls, barrier, participant):
        """Return the stable instance that should receive this participant."""
        # Group links may have been created immediately before this barrier.
        # Flush so association-backed ``active_sync_groups`` resolves the group.
        db.session.flush()
        BarrierDefinition.ensure_exists(barrier.id, barrier.__class__)
        group_id = cls._group_id(barrier, participant)
        spec = barrier_spec_json(barrier)
        behavior_hash = behavior_hash_from_json(spec)
        instance = cls._active_instance(barrier.id, group_id)
        if instance is not None:
            instance._validate_behavior(behavior_hash)
            return instance

        _claim_barrier_instance(_pool_claim_key(barrier.id, group_id), wait=True)

        instance = cls._active_instance(barrier.id, group_id)
        if instance is not None:
            instance._validate_behavior(behavior_hash)
            return instance

        instance = cls._waiting_inactive_instance(barrier.id, group_id)
        if instance is not None:
            instance._validate_behavior(behavior_hash)
            instance.active = True
            db.session.flush()
            return instance

        record = cls(
            id=str(uuid.uuid4()),
            barrier_id=barrier.id,
            group_id=group_id,
            active=True,
            spec=spec,
            behavior_hash=behavior_hash,
        )
        # Partial unique indexes make a SAVEPOINT-plus-IntegrityError insert
        # show up as extra profiler commits. ON CONFLICT DO NOTHING reuses the
        # committed winner without opening a nested transaction.
        values = _insert_values_from_state(record)
        values["spec"] = spec
        db.session.execute(pg_insert(cls).values(**values).on_conflict_do_nothing())
        instance = cls._active_instance(barrier.id, group_id)
        if instance is None:
            raise RuntimeError(
                f"Failed to create or load barrier instance '{barrier.id}'."
            )
        if instance.id != record.id:
            instance._validate_behavior(behavior_hash)
        return instance

    @classmethod
    def _active_instance(cls, barrier_id, group_id):
        """Return the active instance for one waiting pool."""
        return (
            cls.query.filter_by(
                barrier_id=barrier_id,
                group_id=group_id,
                active=True,
            )
            .order_by(cls.id)
            .first()
        )

    @classmethod
    def _waiting_inactive_instance(cls, barrier_id, group_id):
        """Return an inactive visit in this pool that still has working waiters.

        Last-arrival can mark a visit inactive from a snapshot that missed a
        concurrent arriver. The next arrival must join that visit instead of
        opening a second active instance for the same pool.
        """
        waiter_exists = (
            db.session.query(ParticipantLinkBarrier.id)
            .join(Participant)
            .filter(
                ParticipantLinkBarrier.barrier_instance_id == cls.id,
                ~ParticipantLinkBarrier.released,
                ~Participant.failed,
                Participant.status == "working",
            )
            .exists()
        )
        query = cls.query.filter(
            cls.barrier_id == barrier_id,
            cls.active.is_(False),
            waiter_exists,
        )
        if group_id is None:
            query = query.filter(cls.group_id.is_(None))
        else:
            query = query.filter(cls.group_id == group_id)
        return query.order_by(cls.id).first()

    def get_barrier(self):
        """Return the reconstructed release object for this visit.

        This is not the live timeline barrier. See :class:`Barrier` for which
        methods are safe here. Reconstructions are memoized on the current
        SQLAlchemy session so grouped-page render does not re-parse the spec.
        The visit-claim peek drops that memo after it rolls back.
        """
        session = object_session(self)
        cache = None
        instance_id = getattr(self, "id", None)
        if session is not None and instance_id is not None:
            cache = session.info.setdefault(_BARRIER_FROM_SPEC_CACHE_KEY, {})
            cached = cache.get(instance_id)
            if cached is not None:
                return cached
        barrier = barrier_from_spec_json(self.spec)
        if cache is not None:
            cache[instance_id] = barrier
        return barrier

    def _validate_behavior(self, behavior_hash):
        """Reject incompatible reuse of one active waiting pool."""
        if self.behavior_hash != behavior_hash:
            raise BarrierBehaviorMismatch(
                f"Barrier ID '{self.barrier_id}' was reused with different behavior "
                "while its waiting pool is active. Use a different barrier ID."
            )

    @staticmethod
    def _group_id(barrier, participant):
        group = barrier.waiting_pool_group(participant)
        return None if group is None else group.id


@register_table
class ParticipantLinkSyncGroup(SQLBase, SQLMixin):
    __tablename__ = "participant_link_sync_group"

    arrival_time = Column(DateTime)
    active = Column(Boolean, default=True)
    removal_reason = Column(String)
    removal_time = Column(DateTime)
    # The page a member removed for being late was on; see
    # ``Response.too_late_for_group``.
    removed_on_page = Column(String)
    # The member's role in the group (see ``Regrouper(roles=...)``).
    role = Column(String)
    # The deadline of the latest timed page the member started outside
    # waiting logic since the group's last barrier pass; see
    # ``GroupBarrier.late_after``.
    page_deadline = Column(DateTime)
    #: When the group took the member in: at formation, on joining with
    #: ``use_admission_points=False``, or at an admission point. ``None``
    #: while they are pending (see :attr:`SyncGroup.pending_participants`).
    admitted_at = Column(DateTime)
    #: How many of the group's admission points released the member once
    #: admitted, counting the one that admitted them.
    admission_points_passed = Column(Integer, default=0)

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant", back_populates="sync_group_links"
    )

    sync_group_id = Column(Integer, ForeignKey("sync_group.id"), index=True)
    sync_group = relationship("SyncGroup", back_populates="participant_links")


@register_table
class ParticipantLinkBarrier(SQLBase, SQLMixin):
    __tablename__ = "participant_link_barrier"

    barrier_id = Column(String, ForeignKey("barrier.id"), index=True)
    barrier_instance_id = Column(String, ForeignKey("barrier_instance.id"), index=True)
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant",
        backref=backref(
            "barrier_links", cascade="all, delete-orphan"
        ),  # for some reason backpopulates didn't work here
    )

    arrival_time = Column(DateTime)
    departure_time = Column(DateTime)
    released = Column(Boolean, default=False)
    # A Regrouper released the participant without a group.
    sat_out = Column(Boolean, default=False)
    # This visit, to an admission point, admitted the participant to their group.
    admitted = Column(Boolean, default=False)
    #: Internal: the last page the participant answered before arriving,
    #: other than a waiting page, ended on its time limit
    #: (``Participant.timed_out_since_barrier``). It drives the "ran out of
    #: time" mark of :class:`~psynet.group_prompt.GroupPrompt`. To analyse
    #: time-outs, read :attr:`psynet.trial.main.Trial.time_limit_reached` or
    #: :attr:`psynet.timeline.Response.time_limit_reached` instead.
    ran_out_of_time = Column(Boolean, default=False)
    # With explicit waiting_logic there is no hold record, so the link keeps
    # the max_wait_time deadline for the poller.
    deadline_at = Column(DateTime)
    timeline_hold_id = Column(Integer, ForeignKey("timeline_hold.id"), index=True)
    timeline_hold = relationship("TimelineHoldRecord", backref="barrier_links")

    barrier_instance = relationship(
        "BarrierInstance", back_populates="participant_links"
    )

    def get_barrier(self):
        if self.barrier_instance is None:
            raise RuntimeError(
                f"Barrier instance '{self.barrier_instance_id}' is missing or invalid."
            )
        barrier = self.barrier_instance.get_barrier()
        if not isinstance(barrier, Barrier):
            raise RuntimeError(
                f"Barrier instance '{self.barrier_instance_id}' is missing or invalid."
            )
        return barrier

    def get_waiting_participants(self, *, for_update: bool = False):
        """Return people waiting at this visit.

        Does not take extra row locks unless ``for_update`` is true.
        ``for_update`` is keyword-only, matching :meth:`Barrier.get_waiting_participants`.
        """
        return _get_waiting_participants(
            self.barrier_id,
            self.barrier_instance_id,
            for_update=for_update,
            nowait=False,
        )

    def release(self):
        timestamp = timenow()
        self.departure_time = timestamp
        self.released = True
        if self.timeline_hold is not None:
            self.timeline_hold.mark_released(self.participant, timestamp)
            _queue_timeline_hold_wake(
                self.participant_id,
                page_uuid=self.timeline_hold.page_uuid,
                reason="barrier_released",
                hold=self.timeline_hold,
            )


def _waiting_barrier_instance_ids():
    """Snapshot barrier visits that still have working waiters.

    Include inactive rows. A last-arrival snapshot can mark the visit
    finished while a concurrent arriver's link committed after that SELECT.

    Returns
    -------
    dict
        Maps each visit's instance id to a fingerprint of its waiters and
        sync group, so the poller can tell which visits changed since it
        last checked them.
    """
    with Session(bind=db.engine) as session:
        rows = (
            session.query(
                BarrierInstance.id,
                BarrierInstance.active,
                func.count(ParticipantLinkBarrier.id),
                func.max(ParticipantLinkBarrier.id),
                SyncGroup.active,
                SyncGroup.n_active_participants,
                SyncGroup.leader_id,
            )
            .join(
                ParticipantLinkBarrier,
                ParticipantLinkBarrier.barrier_instance_id == BarrierInstance.id,
            )
            .join(Participant, Participant.id == ParticipantLinkBarrier.participant_id)
            .outerjoin(SyncGroup, SyncGroup.id == BarrierInstance.group_id)
            .filter(
                ~ParticipantLinkBarrier.released,
                ~Participant.failed,
                Participant.status == "working",
            )
            .group_by(BarrierInstance.id, SyncGroup.id)
            .order_by(BarrierInstance.id)
        )
        return {instance_id: tuple(fingerprint) for instance_id, *fingerprint in rows}


def _overdue_waiter_ids():
    """Return working waiters whose current barrier hold, or waiting-page deadline, has passed."""
    now = timenow()
    deadline = func.coalesce(
        TimelineHoldRecord.deadline_at, ParticipantLinkBarrier.deadline_at
    )
    with Session(bind=db.engine) as session:
        return [
            participant_id
            for (participant_id,) in (
                session.query(ParticipantLinkBarrier.participant_id)
                .outerjoin(
                    TimelineHoldRecord,
                    TimelineHoldRecord.id == ParticipantLinkBarrier.timeline_hold_id,
                )
                .join(
                    Participant, Participant.id == ParticipantLinkBarrier.participant_id
                )
                .filter(
                    ~ParticipantLinkBarrier.released,
                    ~Participant.failed,
                    Participant.status == "working",
                    or_(
                        (TimelineHoldRecord.page_uuid == Participant.page_uuid)
                        & TimelineHoldRecord.released_at.is_(None)
                        & (TimelineHoldRecord.deadline_at <= now),
                        ParticipantLinkBarrier.timeline_hold_id.is_(None)
                        & (ParticipantLinkBarrier.deadline_at <= now),
                    ),
                )
                .group_by(ParticipantLinkBarrier.participant_id)
                .order_by(func.min(deadline), ParticipantLinkBarrier.participant_id)
            )
        ]


def _time_out_overdue_links(participant):
    """Apply the barrier's max-wait timeout to the waiter's current overdue hold.

    Like the request path, only the hold on the participant's current page
    times out. Waiters on explicit ``waiting_logic`` pages have no hold, and
    time out by their link's deadline, whichever page they are on.
    """
    now = timenow()
    for link in list(participant.active_barriers.values()):
        record = link.timeline_hold
        if record is None:
            if link.deadline_at is not None and link.deadline_at <= now:
                _BarrierHoldPage(link.get_barrier()).apply_timeout(participant)
                if not link.released:
                    link.release()
            continue
        if (
            record.page_uuid != participant.page_uuid
            or record.released_at is not None
            or record.deadline_at is None
            or record.deadline_at > now
        ):
            continue
        _BarrierHoldPage(link.get_barrier()).apply_timeout(participant)
        if not link.released:
            link.release()


def _time_out_overdue_waiters(sweep_ends):
    """Apply ``max_wait_time`` to waiters whose deadline has passed.

    A waiter's own request normally applies the timeout, so someone who
    closed the tab would otherwise keep waiting, and keep the poller busy,
    forever. Waiters are timed out earliest deadline first, each in their
    own transaction, until ``sweep_ends`` (at least one per sweep). A
    waiter whose own request holds their row is left to that request.
    Waiters whose timeout raised an error go last, so they cannot use up
    every sweep's budget.
    """
    from .experiment import get_experiment

    overdue_ids = _overdue_waiter_ids()
    _poller_failed_timeouts.intersection_update(overdue_ids)
    if not overdue_ids:
        return
    overdue_ids.sort(
        key=lambda participant_id: participant_id in _poller_failed_timeouts
    )
    experiment = get_experiment()
    for index, participant_id in enumerate(overdue_ids):
        if index and time.monotonic() >= sweep_ends:
            return
        try:
            _set_transaction_lock_timeout(
                get_config().get("timeline_lock_timeout_seconds")
            )
            participant = _lock_and_load_participant(
                experiment._participant_request_query(), participant_id, nowait=True
            )
            if participant is not None:
                _time_out_overdue_links(participant)
            db.session.commit()
        except Exception as err:
            db.session.rollback()
            if is_transient_transaction_error(err):
                logger.debug(
                    "Overdue waiter %s is busy in another request.", participant_id
                )
                continue
            _poller_failed_timeouts.add(participant_id)
            logger.exception("Failed to time out overdue waiter %s.", participant_id)


def arrival_notice_payload(unique_id):
    """Return the partner-ready notice and ready seats for one participant.

    Redis arrival wakes are fire-and-forget. The browser fetches this when
    the arrival websocket opens so a partner who arrived during connect is
    still shown.
    """
    from psynet.participant import Participant

    if not unique_id:
        return {"notice": None, "group_ready": []}
    participant = Participant.query.filter_by(unique_id=unique_id).one_or_none()
    if participant is None:
        return {"notice": None, "group_ready": []}
    return {
        **_arrival_notice_fields(participant),
        "group_ready": _ready_seats_for(participant),
    }


def _ready_seats_for(participant):
    """Return ``{group_id, seats, ran_out_of_time, members}`` for each of the participant's groups.

    ``seats`` (see :func:`group_seats`) are those of the members waiting at
    a barrier of the group, as :class:`~psynet.group_prompt.GroupPrompt`
    ticks them, ``ran_out_of_time`` those of the waiting members who came
    after their latest timed page ran out of time, and ``members`` those of all
    active members, so that it can redraw the group when someone joins or
    leaves.
    """
    ready = []
    for group in participant.active_sync_groups.values():
        seats = group_seats(group)
        members = group.active_participants
        waiting, timed_out = [], []
        for member in members:
            links = [link for _, link in _waiting_links(member, group)]
            if links:
                waiting.append(seats[member.id])
            if any(link.ran_out_of_time for link in links):
                timed_out.append(seats[member.id])
        ready.append(
            {
                "group_id": group.id,
                "seats": sorted(waiting),
                "ran_out_of_time": sorted(timed_out),
                "members": sorted(seats[m.id] for m in members),
            }
        )
    return ready


def _notify_membership_change(group, newcomer=None):
    """Have the other members of ``group`` fetch their notice and group again."""
    if getattr(group, "_dissolving_below_quorum", False):
        return
    for member in group.active_participants:
        if member is not newcomer:
            _queue_arrival_update(member.id, refresh=True)


def _waiting_links(participant, group):
    return [
        (barrier_id, link)
        for barrier_id, link in participant.active_barriers.items()
        if not link.released
        and link.barrier_instance is not None
        and link.barrier_instance.group_id == group.id
    ]


def _is_waiting_at_barrier(participant, group) -> bool:
    """Return whether ``participant`` is waiting at a barrier of ``group``.

    This is how :class:`~psynet.group_prompt.GroupPrompt` decides by default
    who has answered.
    """
    return bool(_waiting_links(participant, group))


def reached_barrier_after_time_limit(participant, group) -> bool:
    """Return whether ``participant`` reached the barrier of ``group`` they wait at because a time limit ran out.

    That is, they are waiting at a barrier of ``group`` that they reached
    after the time limit of their latest timed page ran out; untimed pages in
    between, and a trial's feedback pages even if timed, don't count.
    """
    return any(link.ran_out_of_time for _, link in _waiting_links(participant, group))


def _interruptible_waiting_barrier(page, participant):
    """Return the barrier whose ``waiting_logic`` this page belongs to, if a release may end it.

    Every such page may end, including a trial's; see :func:`_end_waiting_page`.
    """
    barrier = (getattr(page, "links", None) or {}).get("barrier")
    if not isinstance(barrier, Barrier) or barrier.release_grace is None:
        return None
    if participant.waiting_barrier_id != barrier.id:
        return None
    if participant.failed:
        return None
    return barrier


#: ``failed_reason`` of a trial whose page a barrier's release ended before it was answered.
INTERRUPTED_BY_RELEASE = "interrupted_by_release"


def _end_waiting_page(participant):
    """Fail the trial of the waiting page a release is ending, if it has not been answered.

    A barrier with ``waiting_logic`` is never inside a trial's pages (see
    :meth:`Barrier.receive_participant`), so an unanswered trial here was
    started in the waiting logic.
    """
    trial = _trial_owning_page(participant)
    if trial is not None and not trial.failed:
        trial.fail(reason=INTERRUPTED_BY_RELEASE)


def _forget_time_out(participant):
    """Skipping a barrier passes it, so a time-out before it doesn't reach the next one."""
    participant.timed_out_since_barrier = False


def _leave_waiting_logic(code_block, participant):
    """Hand the participant back to the barrier whose waiting logic encloses this one, if any.

    A trial maker in a released pass may have prepared a trial whose pages
    the participant never reached; it is failed and completed here.
    """
    from .timeline import _in_released_pass

    trial = _in_released_pass(participant) and _trial_owning_page(participant)
    if trial:
        if not trial.failed:
            trial.fail(reason=INTERRUPTED_BY_RELEASE)
        trial.complete = True
    outer = code_block.links.get("barrier")
    participant.waiting_barrier_id = None if outer is None else outer.id


def _has_left_barrier(participant, barrier_id):
    """Return whether the participant is no longer waiting at this barrier."""
    link = participant.active_barriers.get(barrier_id)
    return link is None or bool(link.released)


def released_waiting_barrier(page, participant):
    """Return the barrier if this is its interruptible waiting page and it released the participant.

    The waiting-status route uses the same test, so the browser only ends a
    waiting page when the server will accept the interrupt.
    """
    barrier = _interruptible_waiting_barrier(page, participant)
    if barrier is not None and _has_left_barrier(participant, barrier.id):
        return barrier
    return None


def _release_notice(barrier):
    """Return the notice a waiting page shows once its barrier releases the participant."""
    _p = get_translator(context=True)
    if isinstance(barrier, (GroupBarrier, Grouper)):
        return _p("waiting", "Your group is ready. Moving on in {SECONDS} s.")
    return _p("waiting", "Moving on in {SECONDS} s.")


def waiting_page_config(page, participant):
    """Return the browser config for a page shown while waiting at a barrier, or ``None``.

    Every page shown during ``waiting_logic`` checks in, including pages that
    trial makers generate there, so each can count down to the release.
    ``release_grace_ms`` is ``None`` unless a release may end the
    page. The participant may already have been released while this page was
    being built; the page's first status check then ends it. Timeline holds
    get no config, because they already poll for their release.
    """
    if _is_timeline_hold(page):
        return None
    barrier = _interruptible_waiting_barrier(page, participant)
    if barrier is not None:
        return {
            "barrier_id": barrier.id,
            "release_grace_ms": round(barrier.release_grace * 1000),
            "release_notice": _release_notice(barrier),
        }
    barrier_id = participant.waiting_barrier_id
    if (
        participant.failed
        or barrier_id is None
        or _has_left_barrier(participant, barrier_id)
    ):
        return None
    return {"barrier_id": barrier_id, "release_grace_ms": None}


def waiting_status_payload(unique_id, barrier_id):
    """Return whether a participant on a waiting page has been released.

    Waiting pages fetch this about every 2 seconds. ``ends_page`` tells
    whether the participant's current page would now accept an interrupt
    (see :func:`released_waiting_barrier`); a released participant whose
    page may not be ended, for example with ``release_grace=None``, gets
    ``released`` without ``ends_page`` and finishes the page normally.
    ``release_in_ms`` is the time left until
    :meth:`Barrier.expected_release_time`, or ``None``.
    """
    from psynet.experiment import get_experiment

    participant = (
        Participant.query.filter_by(unique_id=unique_id).one_or_none()
        if unique_id
        else None
    )
    if participant is None:
        return {"released": False, "ends_page": False, "release_in_ms": None}
    if _has_left_barrier(participant, barrier_id):
        exp = get_experiment()
        page = exp.timeline.get_current_elt(exp, participant)
        released = released_waiting_barrier(page, participant)
        return {
            "released": True,
            "ends_page": released is not None and released.id == barrier_id,
            "release_in_ms": None,
        }
    link = participant.active_barriers[barrier_id]
    release_in_ms = None
    barrier = _reconstructed_arrival_barrier(link, {})
    if barrier is not None:
        release_time = barrier.expected_release_time(participant)
        if release_time is not None:
            release_in_ms = max(0, round((release_time - time.time()) * 1000))
    return {"released": False, "ends_page": False, "release_in_ms": release_in_ms}


def _reconstructed_arrival_barrier(link, reconstructed):
    """Return a registry barrier for arrival notices, or ``None`` on spec error.

    Page render must not 500 when a stored spec cannot be reconstructed.
    Failed instance ids are remembered so a group is not retried per member.
    """
    instance_id = link.barrier_instance_id
    if instance_id in reconstructed:
        return reconstructed[instance_id]
    try:
        barrier = link.get_barrier()
    except BarrierSpecError:
        logger.exception(
            "Barrier instance %s failed arrival-notice reconstruction.",
            instance_id,
        )
        barrier = None
    reconstructed[instance_id] = barrier
    return barrier


def _tell_group_ended(participant, group_size):
    """Tell a member who carries on alone after their group dissolved, on their next page."""
    _p = get_translator(context=True)
    if group_size <= 2:
        text = _p(
            "timeline_hold",
            "Your partner is no longer in your group. Please continue.",
        )
    else:
        text = _p(
            "timeline_hold",
            "Too few members of your group remained. Please continue.",
        )
    _set_next_page_notice(participant, text)


def _set_next_page_notice(participant, text):
    """Show ``text`` on the participant's next page, unless their own request holds their row."""
    if _lock_free_participants([participant]):
        participant.group_removal_notice = {"next_page": True, "text": str(text)}


def _removed_late_on_current_page(participant) -> bool:
    """Return whether a barrier removed the participant for being late while on their current page."""
    return (
        participant.page_uuid is not None
        and ParticipantLinkSyncGroup.query.filter_by(
            participant_id=participant.id, removed_on_page=participant.page_uuid
        ).first()
        is not None
    )


def _removed_from_group_notice(participant) -> Optional[str]:
    """Return the notice for a participant removed from a group on their current page."""
    stored = getattr(participant, "group_removal_notice", None)
    if (
        stored is None
        or stored.get("next_page")
        or stored["page_uuid"] != participant.page_uuid
    ):
        return None
    return stored["text"]


def _arrival_notice_fields(participant):
    """Return ``{"notice": ...}``, adding ``"removed": True`` for a removal notice.

    Pages that hide arrival notices, such as live-tick GroupPrompt pages,
    still show a removal notice.
    """
    notice = pending_arrival_notice_for(participant)
    if notice is not None and _removed_from_group_notice(participant) is not None:
        return {"notice": notice, "removed": True}
    return {"notice": notice}


def pending_arrival_notice_for(participant):
    """Return a partner-ready notice if this participant is behind a waiter.

    Reconstructs registry barriers for this call only. Overlay HTML stays on
    the live timeline barrier. Unreconstructable specs are skipped.
    """
    if participant is None or getattr(participant, "failed", False):
        return None
    removed_notice = _removed_from_group_notice(participant)
    if removed_notice is not None:
        return removed_notice
    groups = getattr(participant, "active_sync_groups", None) or {}
    reconstructed = {}
    notice = None
    for group in groups.values():
        for member in group.active_participants:
            if member.id == participant.id:
                continue
            for link in list(member.active_barriers.values()):
                if link.released:
                    continue
                instance = link.barrier_instance
                if instance is not None and instance.group_id != group.id:
                    continue
                barrier = _reconstructed_arrival_barrier(link, reconstructed)
                if (
                    not isinstance(barrier, GroupBarrier)
                    or barrier.on_arrival_message is None
                ):
                    continue
                if barrier._participant_is_waiting(participant):
                    continue
                if group._is_pending(participant) and not barrier.admission_point:
                    # Pending members pass straight through this barrier.
                    continue
                waiting_count = sum(
                    1
                    for other in group.active_participants
                    if barrier._participant_is_waiting(other)
                )
                if waiting_count == 0:
                    continue
                text = barrier._call_arrival_message(
                    kind="notice",
                    waiting_count=waiting_count,
                    group_size=len(group.active_participants),
                    participant=participant,
                    group=group,
                )
                if text:
                    notice = str(text)
    return notice


def _barrier_instance_has_waiters(instance):
    """Return whether a visit still has an unreleased working participant."""
    return (
        db.session.query(ParticipantLinkBarrier.id)
        .join(Participant)
        .filter(
            ParticipantLinkBarrier.barrier_instance_id == instance.id,
            ~ParticipantLinkBarrier.released,
            ~Participant.failed,
            Participant.status == "working",
        )
        .first()
        is not None
    )


def _check_claimed_barrier_instance(instance, *, wait=False, already_claimed=False):
    """Evaluate one instance, or report that the work is already done.

    Last-arrival and the poller hold the visit claim on a dedicated
    connection (``already_claimed=True``) so this ORM session does not take
    the same key. Instance creation still uses ``wait`` on the ORM session.

    Returns
    -------
    bool
        ``True`` if this request ran the check or the instance is already
        finished. ``False`` only when another request currently owns the
        advisory claim (on the visit, or on its pool while an arrival opens
        or reactivates it), so the check should run again later.
    """
    if instance is None:
        return True
    if not instance.active:
        if not isinstance(
            instance, BarrierInstance
        ) or not _barrier_instance_has_waiters(instance):
            return True
        pool_key = _pool_claim_key(instance.barrier_id, instance.group_id)
        if not _claim_barrier_instance(pool_key, wait=False):
            return False
        other = BarrierInstance._active_instance(instance.barrier_id, instance.group_id)
        if other is None:
            instance.active = True
    if not already_claimed and not _claim_barrier_instance(instance.id, wait=wait):
        return False
    barrier = instance.get_barrier()
    if not isinstance(barrier, Barrier):
        raise RuntimeError(f"Barrier instance '{instance.id}' is missing or invalid.")
    barrier._check_instance(instance.id)
    return True


_WAITER_LOCKED_DEFERRAL = (
    "because another request holds the row of a waiter or their group "
    "(expected under load; "
    "PostgreSQL logs it as 'could not obtain lock on row')."
)


def _evaluate_held_instance(instance_id):
    """Evaluate one already-claimed visit and commit.

    Sets the ORM ``lock_timeout`` so check/commit cannot wait forever while
    the extra connection holds the visit key. Nested ``NOWAIT`` misses, on a
    waiter's row or on the row of their group that accepts top-ups, roll
    back the check and return ``(False, [])`` so last-arrival can retry. Author ``on_release``
    and spec errors also return ``(False, [])`` so the group stays waiting.
    Other non-transient check errors propagate so ``GET /timeline`` does not
    first-paint a hold. Released waiter ids are drained here so they cannot
    leak in ``session.info``; last-arrival discards them, the poller skips.
    """
    db.session.expire_all()
    _set_transaction_lock_timeout(get_config().get("timeline_lock_timeout_seconds"))
    instance = BarrierInstance.query.options(undefer(BarrierInstance.spec)).get(
        instance_id
    )
    try:
        with db.session.begin_nested():
            ok = _check_claimed_barrier_instance(instance, already_claimed=True)
    except Exception as err:
        if is_transient_transaction_error(err):
            logger.debug(
                "Barrier '%s' instance %s deferred " + _WAITER_LOCKED_DEFERRAL,
                instance.barrier_id if instance is not None else None,
                instance_id,
            )
            return False, []
        logger.exception(
            "Barrier '%s' instance %s failed during a last-arrival check.",
            instance.barrier_id if instance is not None else None,
            instance_id,
        )
        if isinstance(err, (BarrierSpecError, _BarrierAuthorHookError)):
            return False, []
        raise
    released_ids = _take_released_hold_waiter_ids()
    db.session.commit()
    return ok, released_ids


def _check_held_instance(instance_id):
    """Evaluate one visit without advancing partner timeline cursors.

    Last-arrival GET/POST uses this path. Released waiter ids are drained
    so they cannot leak; partners leave on overlay wake.
    """
    ok, _released_ids = _evaluate_held_instance(instance_id)
    return ok


def _check_and_skip_held_instance(instance_id):
    """Evaluate one visit and skip waiters this poller just released."""
    ok, released_ids = _evaluate_held_instance(instance_id)
    _advance_released_hold_waiters_after_commit(released_ids)
    return ok


def _check_held_instance_with_claim(instance_id, *, wait):
    """Peek the visit claim, optionally wait, then evaluate without skipping.

    A free claim is taken without waiting. Last-arrival may then wait for
    a held claim; unfilled waiter GET recovery must pass ``wait=False``.
    Each peek uses an extra pooled connection; last-arrival can open one
    per queued instance when the first peek misses.
    """
    with _hold_barrier_instance_claim(instance_id, wait=False) as claimed:
        if claimed:
            return _check_held_instance(instance_id)
    if not wait:
        return False
    with _hold_barrier_instance_claim(instance_id, wait=True):
        return _check_held_instance(instance_id)


def _run_pending_barrier_checks(instance_ids, *, wait=True):
    """Run post-commit checks, optionally waiting for each instance claim.

    Last-arrival waits for the extra-connection claim so it can release
    without waiting for the 0.5 s poller. It does not skip partner cursors
    after that commit. Waiter rows stay ``FOR UPDATE NOWAIT`` during the
    check, as are the rows of their groups that accept top-ups. A blocking
    claim wait that hits ``lock_timeout`` raises so ``GET /timeline`` can
    return HTTP 503. A ``NOWAIT`` miss on a waiter's or group's row still
    returns ``False`` so the caller can retry once.

    Unfilled waiter GET recovery must pass ``wait=False``. Those requests try
    the claim so a dropped last-arrival check can still finish, but they must
    not occupy a worker in ``lock_timeout`` while last-arrival already holds
    the visit.
    """
    all_claimed = True
    for instance_id in instance_ids:
        try:
            if not _check_held_instance_with_claim(instance_id, wait=wait):
                all_claimed = False
        except Exception as err:
            if is_transient_transaction_error(err):
                raise
            logger.exception(
                "Barrier instance %s failed while waiting for its visit claim.",
                instance_id,
            )
            raise
    return all_claimed


def _process_barrier_instance(instance_id, *, retry=False):
    """Try one barrier visit and report whether contention deferred it.

    Contention is another request holding the visit claim, or a locked
    waiter or top-up group. Author ``on_release`` and spec errors are reported the same way.
    The poller retries once in the same sweep, then queues the visit like a
    checked one. Errors during the check itself are logged with the barrier
    ID by :func:`_evaluate_held_instance`.
    """
    try:
        with _hold_barrier_instance_claim(instance_id, wait=False) as claimed:
            if not claimed:
                return True
            if not _check_and_skip_held_instance(instance_id):
                return True
            return False
    except Exception as err:
        db.session.rollback()
        if is_transient_transaction_error(err):
            qualifier = " deferred again on retry" if retry else " deferred"
            logger.debug(
                "Barrier instance %s%s " + _WAITER_LOCKED_DEFERRAL,
                instance_id,
                qualifier,
            )
            return True
        qualifier = " on retry" if retry else ""
        logger.exception(
            "Failed to process barrier instance %s%s.",
            instance_id,
            qualifier,
        )
    return False


def _finish_dissolving_groups():
    """Try again to dissolve groups whose dissolution waited for a busy member.

    Each group is handled in its own transaction. A group another request
    holds, or with a member still busy, is left for the next sweep. A group
    back at its quorum by then is no longer dissolved. Group and member rows
    are taken without waiting; other lock waits while failing a member, for
    example on their trials, are bounded by ``timeline_lock_timeout_seconds``.
    """
    with Session(bind=db.engine) as session:
        group_ids = [
            group_id
            for (group_id,) in session.query(SyncGroup.id)
            .filter(SyncGroup.active.is_(True), SyncGroup.dissolving.is_(True))
            .order_by(SyncGroup.id)
        ]
    for group_id in group_ids:
        try:
            _set_transaction_lock_timeout(
                get_config().get("timeline_lock_timeout_seconds")
            )
            group = _lock_sync_group(group_id, skip_locked=True)
            if group is not None and group.active and group.dissolving:
                group.check_numbers()
                quorum = group.quorum or 0
                if 0 < quorum <= group.n_active_participants:
                    group.dissolving = False
                else:
                    group._dissolve()
            db.session.commit()
        except Exception as err:
            db.session.rollback()
            if is_transient_transaction_error(err):
                logger.debug("Dissolving sync group %s is busy.", group_id)
                continue
            logger.exception("Failed to finish dissolving sync group %s.", group_id)


def _visits_due(waiting, sweep_ends):
    """Yield waiting visits in check order until ``sweep_ends``, at least one.

    Least recently checked visits come first. Visits that are new to this
    process, or whose fingerprint changed since it last checked them, get a
    head start of ``_POLLER_CHANGE_HEAD_START_SECONDS``, so they are checked
    promptly without starving unchanged visits whose release depends on time.
    """
    now = time.monotonic()

    def priority(instance_id):
        last = _poller_checked_visits.get(instance_id)
        if last is None:
            return (now - _POLLER_CHANGE_HEAD_START_SECONDS, instance_id)
        fingerprint, checked_at = last
        if fingerprint != waiting[instance_id]:
            checked_at -= _POLLER_CHANGE_HEAD_START_SECONDS
        return (checked_at, instance_id)

    for index, instance_id in enumerate(sorted(waiting, key=priority)):
        if index and time.monotonic() >= sweep_ends:
            return
        yield instance_id


def check_barriers():
    """Process waiting barrier visits, including stacked holds created here.

    Last-arrival GET waits for this poller's extra-connection instance claim.
    The poller keeps that claim until its own skip-after-commit finishes.
    It skips waiters **this poller** released; last-arrival does not skip
    partner cursors. Walk newly created holds in this sweep and keep wake
    publishes unpublished until that walk returns. Each visit still commits
    before the next check so a locked waiter cannot poison sibling checks.

    Each sweep first retries group dissolutions that waited for a busy member
    and times out overdue waiters, then checks visits, least
    recently checked first, with new or changed ones given a head start. Each
    of the two steps stops starting new work after
    ``_POLLER_SWEEP_BUDGET_SECONDS``, so thousands of idle waiters cannot
    keep the poller busy; the rest wait for later sweeps. One item can still
    overrun the budget while it waits for a row lock. A waiter's page reload
    (``GET /timeline``) or a bot's poll also checks their own visit; a
    browser's hold poll does not. A sweep that found waiting visits ends by
    reporting groups whose members wait at different barriers (see
    :func:`_report_divergences`).
    """
    seen = set()
    _check_barriers(seen)
    if seen:
        _report_divergences()


def _check_barriers(seen):
    """Do the work of :func:`check_barriers`, adding each visit checked to ``seen``."""
    with _defer_timeline_hold_wakes():
        _finish_dissolving_groups()
        _time_out_overdue_waiters(time.monotonic() + _POLLER_SWEEP_BUDGET_SECONDS)
        sweep_ends = time.monotonic() + _POLLER_SWEEP_BUDGET_SECONDS
        # Settle on an empty snapshot *before* more work. The False yield is
        # the observation after the last processed generation.
        for can_work in _barrier_walk_budget():
            snapshot = _waiting_barrier_instance_ids()
            if not seen:
                for instance_id in set(_poller_checked_visits) - set(snapshot):
                    del _poller_checked_visits[instance_id]
            waiting = {
                instance_id: fingerprint
                for instance_id, fingerprint in snapshot.items()
                if instance_id not in seen
            }
            if not waiting:
                return
            if not can_work:
                raise RuntimeError(
                    "Barrier poller sweep did not settle after "
                    f"{_MAX_BARRIER_WALK_PASSES} passes."
                )
            seen.update(waiting)
            deferred_ids = []
            for instance_id in _visits_due(waiting, sweep_ends):
                if _process_barrier_instance(instance_id):
                    deferred_ids.append(instance_id)
                else:
                    _remember_poller_check(instance_id, waiting[instance_id])
            for instance_id in deferred_ids:
                # Even if still deferred: a visit whose check keeps failing
                # must not stay ahead of every other visit.
                _process_barrier_instance(instance_id, retry=True)
                _remember_poller_check(instance_id, waiting[instance_id])


def _remember_poller_check(instance_id, fingerprint):
    """Record that this process checked a visit in the given state."""
    _poller_checked_visits[instance_id] = (fingerprint, time.monotonic())


def check_sync_groups():
    """Recount active membership and close groups with no active members left.

    Members who finish or return the experiment stay linked to their groups,
    so this is what closes a group once all of them are gone. It closes any
    active :class:`SyncGroup` with no admitted or pending members, including
    emptied groups that accept top-ups, unless the group is still dissolving.
    Groups locked by another request are skipped until the next tick.

    One query first counts every active group's members (see
    :func:`_groups_to_recount`), so only groups whose stored counts are
    stale, or that may close, are locked and recounted.

    Dedicated sessions keep these maintenance commits separate from any
    transaction owned by the caller. Each group's recount runs in its own
    transaction so a failure cannot roll back sibling groups already processed.
    """
    for group_id in _groups_to_recount():
        try:
            with Session(bind=db.engine) as session:
                _set_transaction_lock_timeout(
                    get_config().get("timeline_lock_timeout_seconds"),
                    session=session,
                )
                group = _lock_sync_group(group_id, session=session, skip_locked=True)
                if group is None:
                    continue
                group.check_numbers()
                if (
                    group.n_active_participants == 0
                    and not group.dissolving
                    and not group.pending_participants
                ):
                    group.close()
                session.commit()
        except Exception as err:
            if is_transient_transaction_error(err):
                logger.debug(
                    "Sync group %s skipped this tick because it is locked.",
                    group_id,
                )
            else:
                logger.exception("Failed to process sync group %s.", group_id)


def _groups_to_recount():
    """Return the active groups that :func:`check_sync_groups` must lock and recount.

    Counts each active group's admitted and pending working members as
    :attr:`SyncGroup.active_participants` and
    :attr:`SyncGroup.pending_participants` do, and returns the groups whose
    stored ``n_active_participants``, or :class:`SimpleSyncGroup`'s
    ``below_quorum_since``, disagrees with that count, the groups that may
    close, and every group of a class that overrides ``check_numbers``.
    """
    link = ParticipantLinkSyncGroup
    # Only SimpleSyncGroup maps these columns of the shared table.
    columns = SyncGroup.__table__.c
    working = and_(
        link.active.is_(True),
        ~Participant.failed,
        Participant.status == "working",
    )
    known_types = [
        mapper.polymorphic_identity
        for mapper in SyncGroup.__mapper__.self_and_descendants
        if mapper.class_.check_numbers
        in (SyncGroup.check_numbers, SimpleSyncGroup.check_numbers)
    ]
    with Session(bind=db.engine) as session:
        counts = (
            session.query(
                link.sync_group_id.label("group_id"),
                func.count(link.id)
                .filter(working & link.admitted_at.isnot(None))
                .label("n_admitted"),
                func.count(link.id)
                .filter(working & link.admitted_at.is_(None))
                .label("n_pending"),
            )
            .join(Participant, Participant.id == link.participant_id)
            .group_by(link.sync_group_id)
            .subquery()
        )
        n_admitted = func.coalesce(counts.c.n_admitted, 0)
        below_quorum = n_admitted < func.coalesce(columns.quorum, 0)
        return [
            group_id
            for (group_id,) in (
                session.query(SyncGroup.id)
                .outerjoin(counts, counts.c.group_id == SyncGroup.id)
                .filter(
                    SyncGroup.active.is_(True),
                    or_(
                        SyncGroup.type.notin_(known_types),
                        SyncGroup.n_active_participants.is_distinct_from(n_admitted),
                        below_quorum & columns.below_quorum_since.is_(None),
                        ~below_quorum & columns.below_quorum_since.isnot(None),
                        (n_admitted == 0)
                        & ~SyncGroup.dissolving.is_(True)
                        & (func.coalesce(counts.c.n_pending, 0) == 0),
                    ),
                )
                .order_by(SyncGroup.id)
            )
        ]


Participant.sync_group_links = relationship(
    "ParticipantLinkSyncGroup",
    cascade="all, delete-orphan",
)


def _participant_sync_groups(participant) -> List["SyncGroup"]:
    """Sync groups with an active participant-group link for this participant."""
    return [
        link.sync_group
        for link in participant.sync_group_links
        if getattr(link, "active", True)
    ]


Participant.sync_groups = property(lambda self: _participant_sync_groups(self))

# No association proxy for barrier links because barriers are not exposed as objects


class GroupCloser(GroupBarrier):
    """
    A timeline construct for closing a previously created group.
    This is required before creating a new group with the same ``group_type``.
    """

    def __init__(self, group_type: str, **kwargs):
        if "id_" not in kwargs:
            kwargs["id_"] = f"closer_{group_type}"

        super().__init__(group_type=group_type, on_release=close_sync_group, **kwargs)


def close_sync_group(group):
    group.close()

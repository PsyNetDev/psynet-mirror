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
    forms new groups every round, optionally within an existing group, and
    keeps when each pool was last split in ``var`` (on the ``within`` group,
    or on the ``BarrierDefinition``).

Barrier definition and instance
    A ``BarrierDefinition`` identifies the public waiting area. A
    ``BarrierInstance`` stores the stable behavior for one group visit.
    ``ParticipantLinkBarrier`` rows attach participants to that visit. At most
    one active instance exists per group visit, and ungrouped barriers share
    one active pool per barrier ID. Keeping definition, visit, and work-claim
    identities separate lets multiple worker processes cooperate without using
    mutable metadata as a mutex.

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

- Finishes dissolving sync groups whose dissolution skipped members who were
  busy in their own request (see ``SyncGroup._dissolve``).
- Applies ``max_wait_time`` to waiters whose hold or waiting-page deadline has
  passed. Their own request normally does this, so waiters who left would
  otherwise stay.
- Finds waiting barrier instances and checks them least recently checked
  first, new or changed ones with a head start, within a per-sweep time budget.
- Claims each with a PostgreSQL advisory transaction lock on a dedicated
  connection, leaving definition and instance metadata available to arrival
  requests. That extra transaction stays open until this poller's
  skip-after-commit finishes.
- Locks waiters with ``FOR UPDATE NOWAIT``. If any waiter is already locked
  (for example by ``POST /response``), it skips that barrier this tick instead
  of blocking the poller.
- Evaluates the barrier's release hooks in an isolated transaction, then
  skips waiters **this poller** released, one row at a time, after that commit.
- Logs and skips failures per barrier so one bad barrier does not stall others.
- Keeps hold-wake publishes unpublished until the sweep returns.

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
Last-arrival does not skip partner timeline cursors after that commit; partners
leave on overlay wake (or this poller, if it won the release). Waiter rows stay
``NOWAIT`` during the check so a locked partner cannot stall that request for
``lock_timeout``.

Callable attributes on barriers (e.g., ``on_release``) persist through
:mod:`psynet.barrier_spec` so each ``BarrierInstance`` keeps stable release
behavior without pickling waiting pages. The reconstructed object is a
release/callback receiver, not a wait page. See :class:`Barrier` for which
methods are live-only.
"""

import inspect
import random
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta
from math import ceil, floor
from typing import (
    Callable,
    Dict,
    List,
    Literal,
    NamedTuple,
    Optional,
    Sequence,
    Union,
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
    func,
    or_,
    select,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import (
    Session,
    backref,
    deferred,
    joinedload,
    lazyload,
    object_session,
    relationship,
    selectinload,
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
    _SessionQueue,
    _set_transaction_lock_timeout,
    is_transient_transaction_error,
)
from psynet.field import PythonClass
from psynet.page import UnsuccessfulEndPage
from psynet.participant import Participant
from psynet.serialize import SerializedCallable, serialize_callable
from psynet.timeline import (
    TIME_LIMIT_GRACE_SECONDS,
    CodeBlock,
    EltCollection,
    EndWhile,
    StartWhile,
    _is_timeline_hold,
    conditional,
)
from psynet.timeline_hold import (
    HoldMessage,
    TimelineHoldRecord,
    _defer_timeline_hold_wakes,
    _queue_arrival_update,
    _queue_countdown_update,
    _queue_timeline_hold_wake,
    _TimelineHoldPage,
    compose_hold_overlay_html,
    default_group_barrier_arrival_message,
    default_hold_progress,
)
from psynet.utils import (
    NoArgumentProvided,
    call_function_with_context,
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
            timeout = get_config().get("timeline_lock_timeout_seconds")
            conn.execute(
                text("SELECT set_config('lock_timeout', :timeout, true)"),
                {"timeout": f"{timeout}s"},
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
    """
    query = (
        ParticipantLinkBarrier.query.join(Participant)
        .filter(
            ParticipantLinkBarrier.barrier_id == barrier_id,
            ParticipantLinkBarrier.barrier_instance_id == barrier_instance_id,
            ~ParticipantLinkBarrier.released,
            ~Participant.failed,
            Participant.status == "working",
        )
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
            max_wait_time=barrier.max_wait_time,
            fix_time_credit=barrier.fix_time_credit,
            check_interval=2.0,
            content=barrier.content,
            message_kind="barrier" if barrier.content is None else None,
            on_timeout=barrier.handle_max_wait_timeout,
            waiting_screen=barrier.waiting_screen,
        )

    @property
    def fail_on_timeout(self):
        return self.barrier.max_wait_action == "fail"

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

    def hold_progress_text(self, participant):
        """Return arrival progress for a participant waiting at this barrier."""
        if participant is None:
            return None
        return self.barrier._hold_progress_text(participant)

    def overlay_html(self, participant=None, release_time=NoArgumentProvided):
        """Return hold copy, calling a ``content`` function and filling in ``{SECONDS}``.

        ``release_time`` (epoch seconds, or ``None`` if unknown) defaults to the
        barrier's :meth:`~Barrier.expected_release_time`.
        """
        content = self.content
        content_is_function = isinstance(content, SerializedCallable)
        if not content_is_function and "{SECONDS}" not in str(content or ""):
            return super().overlay_html(participant)
        if self._is_silent_for(participant):
            return compose_hold_overlay_html("", None)
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
        if content_is_function:
            context = {} if participant is None else {"participant": participant}
            content = content(
                barrier=self.barrier,
                seconds_left=seconds,
                **context,
                **self.barrier._hold_message_counts(participant),
            )
        html = compose_hold_overlay_html(content, self.hold_progress_text(participant))
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
    ``content`` with a smaller progress line underneath in groups of three or
    more ("1 of 3 not ready yet"). Return ``hold_message(title, progress)``
    from a ``content`` function to write that line yourself, or leave out
    ``progress`` to show no progress line. The message is redrawn as members
    arrive unless the barrier has ``notify_arrivals=False``.

    Parameters
    ----------
    title
        The waiting message, as for ``content``.
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

        GroupBarrier(id_="chosen", group_type="room", content=waiting_text)
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
    object has ``id``, custom release state, scalar presentation (``content``,
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
        Several barriers can share the same elements.

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
        How long participants are expected to wait here, in seconds, for
        progress estimates and fixed time credit. With ``waiting_logic``, the
        waiting logic is expected to repeat often enough to fill this time,
        rounded up to whole passes (at least one). If omitted, a default hold expects 1.5 seconds and
        ``waiting_logic`` three repetitions.

    content
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. If omitted, participants see
        "Waiting for other participants…". Plain strings are shown as text;
        pass ``markupsafe.Markup`` or a dominate tag for HTML. A ``{SECONDS}``
        placeholder counts down to :meth:`expected_release_time`, showing "…"
        while it is unknown. ``content`` can also be a module-level function
        that returns the message, for example one that depends on the
        participant's role; it may take ``participant``, ``seconds_left``
        (whole seconds, or ``None`` while the release time is unknown) and
        ``barrier``, and on a :class:`GroupBarrier` also ``waiting_count``
        and ``group_size`` (both ``None`` if the participant has no group).
        Return :func:`hold_message` to set the progress
        line under the message yourself.

    waiting_screen
        What to show in place of the current page while the participant
        waits: a prompt, text or HTML (shown without a Next button), or a
        :class:`~psynet.modular_page.ModularPage` that nothing submits, for
        example with ``NullControl(show_next_button=False)``. Pass a
        module-level function ``waiting_screen(participant)`` to show each
        participant their own screen. It runs on each request (a page load
        or a check for the release), sometimes more than once, so base it on
        the participant's state
        rather than on chance. Returning ``None`` keeps the current page, as
        omitting ``waiting_screen`` does; if that page is another barrier's
        waiting screen, a plain waiting page replaces it. The ``content`` message still shows
        on top. A page with a Next button, push buttons or ``auto_advance``,
        or one that needs a full page reload (for
        example deprecated ``js_links``) while
        ``inplace_timeline_transitions`` is on, raises ``ValueError`` when
        it is shown. Only used when ``waiting_logic`` is omitted.

    release_grace
        Seconds a participant on a ``waiting_logic`` page has to finish it
        once they are released; the page then ends without an answer,
        recorded with ``"interrupted": True`` in its response metadata.
        ``None`` lets each waiting page run to its end. Pages inside trials
        always run to their end. Default: 3 seconds.
    """

    # Reconstructed barriers skip ``__init__`` and never render a hold page.
    waiting_screen = None

    def __init__(
        self,
        id_: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=None,
        max_wait_time=20,
        fix_time_credit=False,
        expected_wait=None,
        content=None,
        release_grace: Optional[float] = 3,
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
        self.content = content
        self.waiting_screen = waiting_screen
        self._uses_timeline_hold = waiting_logic is None
        if waiting_logic is not None and content is not None:
            raise ValueError("content only applies when waiting_logic is omitted.")
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
        if name.startswith("on_") or (name == "content" and inspect.isroutine(value)):
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
        from psynet.timeline import join, while_loop

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
                fail_on_timeout=(self.max_wait_action == "fail"),
                on_timeout=self.handle_max_wait_timeout,
            )

        elts = join(
            CodeBlock(lambda participant: self.receive_participant(participant)),
            waiting_elts,
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
            elt.links.setdefault("barrier", self)
        # Page makers can resolve the waiting logic again elsewhere, carrying
        # this link with it, so the loop's own markers say where it really is.
        self._waiting_loop_markers = [
            elt
            for elt in elts
            if isinstance(elt, (StartWhile, EndWhile))
            and elt.label == f"barrier:{self.id}"
        ]

        return elts

    def handle_max_wait_timeout(self, participant: Participant):
        """Release the participant's active barrier link after a max-wait timeout."""
        if self.id in participant.active_barriers:
            self.release(participant)

    def receive_participant(self, participant: Participant):
        """Register this participant on the live timeline barrier.

        Live timeline only. Default holds queue the release check from the
        hold page after the wait row exists.
        """
        if object_session(participant) is None:
            db.session.add(participant)

        barrier_instance = BarrierInstance.for_arrival(self, participant)

        now = timenow()
        link = ParticipantLinkBarrier(
            participant=participant,
            barrier_id=self.id,
            barrier_instance=barrier_instance,
            arrival_time=now,
        )
        participant.active_barriers[self.id] = link
        if not self._uses_timeline_hold:
            max_wait_time = call_if_callable(
                self.max_wait_time, participant=participant
            )
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

    def _hold_progress_text(self, participant):
        """Return hold-overlay progress copy, if this barrier publishes arrivals."""
        return None

    def _hold_message_counts(self, participant):
        """Return extra arguments for a ``content`` function; groups add their counts."""
        return {}

    def expected_release_time(self, participant) -> Optional[float]:
        """Return when this participant will be released at the latest, in epoch seconds.

        Used for the ``{SECONDS}`` countdown in ``content``. ``None`` (default)
        means the release time is unknown.
        """
        return None

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

        logger.info(
            "Barrier '%s' currently has %i participant(s) waiting (ids = %s)",
            self.id,
            len(waiting_participants),
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
            participant = (
                experiment._participant_request_query()
                .with_for_update(of=Participant, nowait=True)
                .populate_existing()
                .get(participant_id)
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


def _group_barrier_outcome(group, members, waiting_ids):
    """Return ``"dissolve"``, ``"release"`` or ``"wait"`` for one group visit.

    Pure: ``GroupBarrier.would_release`` passes the members it projects will
    remain, and ``choose_who_to_release`` passes the live members, so the
    peek and the real release share one decision.
    """
    if len(members) < group.min_group_size:
        return "wait" if group.accepts_top_ups else "dissolve"
    if all(participant.id in waiting_ids for participant in members):
        return "release"
    return "wait"


class _DefaultMaxWaitTime(float):
    """Marks a ``max_wait_time`` that was not passed, so it can follow the between-barrier timeout."""


_DEFAULT_MAX_WAIT_TIME = _DefaultMaxWaitTime(20.0)


class GroupBarrier(Barrier):
    """
    A GroupBarrier is a Barrier that waits until all participants in a given :class:`~psynet.sync.SyncGroup`
    have reached the Barrier. It also checks the current group size against the group's minimum size parameter;
    the group won't be allowed to proceed if it's below this size.
    If ``accepts_top_ups=True`` for that group, it'll wait just in case new participants join the group.
    If ``accepts_top_ups=False``, then there's no hope for new participants, so the group will be released
    and failed.

    After the arrival write commits, the same request evaluates the barrier in
    a short transaction so partners are released without waiting for the 0.5 s
    poller. On the default hold path that arriver then skips their own wait
    indicator. Partners leave on overlay wake; the poller skips waiters only
    when it won the release.
    ``on_release`` receives the reconstructed registry barrier; see
    :class:`Barrier` for the live-versus-reconstructed method split.

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
        waiting indicator. Pass ``content`` to customize that indicator's
        message.

    waiting_logic_expected_repetitions
        Deprecated; pass ``expected_wait`` instead. Expected repetitions of
        ``waiting_logic``.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded, the participant is either failed or kicked (see ``max_wait_action``).
        Defaults to 20 seconds, or to no limit with ``timeout_between_barriers_time``, which then moves
        slow members on instead, however long their pages' time limits are. Must be longer than
        ``timeout_between_barriers_time``; this is not checked when ``max_wait_time`` is a function.
        ``None`` means no limit.
        This is a hard limit counted from arrival: with explicit ``waiting_logic``, the server applies it
        even while the participant is partway through a filler page, so make it long enough to cover long
        filler pages (for example trials used as filler).

    max_wait_action
        When ``max_wait_time`` is exceeded: ``"fail"`` fails the participant and sends them to the end of the
        experiment; ``"kick"`` removes them from the group and lets them continue. Default is ``"fail"``.

    timeout_between_barriers_time
        The maximum amount of time in seconds that a participant is allowed to reach the barrier, measured from when
        the group last passed a ``GroupBarrier`` or the participant joined the group, whichever is later. If
        ``None`` (default), no between-barrier timeout is applied. If the participant has reached a page with a
        ``time_limit`` since then, the timeout counts from when that time limit runs out instead, and is at least
        ``2 * TIME_LIMIT_GRACE_SECONDS`` (10 s), so that an answer sent at the deadline can arrive. So this
        timeout need not be longer than the pages' time limits; it only has to cover pages without one, such as
        the time before the timed page loads, or a short page after it.

    timeout_between_barriers_action
        When a participant exceeds ``timeout_between_barriers_time``: ``"kick"`` removes them from the group (so the
        rest can proceed without them), or ``"fail"`` fails the participant and sends them to the end of the experiment.
        Default is ``"fail"``. A kicked participant is no longer in the group when they reach the barrier, so
        ``"kick"`` also makes ``skip_if_not_in_group`` default to ``True``.

    on_release
        Optional callback invoked when the barrier releases participants.
        Must be a module-level function, ``@staticmethod``/``@classmethod``,
        or a bound method on a TrialMaker or ORM instance with a primary key.
        The ``barrier`` argument is the reconstructed registry object for this
        visit (scalar presentation and notification settings, not wait pages).

    fix_time_credit
        If set to ``True``, award fixed expected time credit. Otherwise default
        holds credit actual visible waiting time up to ``max_wait_time``.

    expected_wait
        See :class:`Barrier`.

    content
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. If omitted, participants see
        "Waiting for other participants…". Plain strings are shown as text;
        pass ``markupsafe.Markup`` or a dominate tag for HTML, or a
        module-level function ``content(participant)`` returning either (see
        :class:`Barrier`). Independent of
        a preceding :class:`~psynet.sync.Grouper`'s ``content`` and of
        trial-maker ``sync_group_wait_content``.

    notify_arrivals
        If ``True`` (default), group members who have not reached this barrier
        yet see a pill on the progress bar, and waiting participants in groups
        of three or more see remaining-not-ready copy on the hold overlay.
        Pairs show only the message. Set ``False`` to disable both. A
        member removed by ``timeout_between_barriers_action="kick"`` is told
        either way; return ``None`` from ``on_arrival_message`` for
        ``kind="removed"`` to hide it. To change the waiting indicator's
        progress line, return :func:`hold_message` from a ``content``
        function.

    skip_if_not_in_group
        If ``True``, a participant who is not in a group of this ``group_type``
        passes straight through, for example after being kicked by a timeout in
        a round-based design. If ``False``, they get an error, which usually
        means a grouper is missing from the timeline. Defaults to ``True`` when
        ``timeout_between_barriers_action="kick"``, and ``False`` otherwise.

    release_grace
        See :class:`Barrier`. Default: 3 seconds.

    waiting_screen
        See :class:`Barrier`.

    on_arrival_message
        Optional callable that returns copy for one recipient. It receives
        ``kind`` (``"notice"`` or ``"removed"``), ``waiting_count``,
        ``group_size``, and the usual context arguments (``recipient``,
        ``group``, ``barrier``, ``experiment``). Return ``None`` to hide that
        surface. Same serialization rules as ``on_release``.

        ``"notice"`` is the progress-bar notice for members who have not
        reached the barrier yet. It defaults to "Your partner is ready." in
        pairs and ``"{ARRIVED}/{TOTAL} of your group are ready."`` in larger
        groups. It is called whenever the recipient's browser fetches its
        notice, which can be several times per arrival, so it should depend
        only on its arguments and have no side effects. Notices stay on one
        line (overflow ellipsizes), so keep them to a short sentence.

        ``"removed"`` is the progress-bar notice for someone kicked by
        ``timeout_between_barriers_action="kick"``, shown until they leave
        their page. It defaults to "Your partner went on without you. Please
        continue." or "Your group went on without you. Please continue.", and
        ``group_size`` counts the group before anyone was removed.

    """

    @staticmethod
    def _kick_participant_after_max_wait(
        participant: Participant, group_type: str
    ) -> None:
        """Remove the participant from their sync group when max wait uses action ``'kick'``."""
        if group_type in participant.active_sync_groups:
            participant.active_sync_groups[group_type].remove_participant(participant)

    @staticmethod
    def _check_max_wait_time(max_wait_time, timeout_between_barriers_time):
        """Return ``max_wait_time``, with no default limit when the between-barrier timeout is set.

        That timeout removes or fails every member who is late, including
        those whose page's time limit ran out, so prompt members never need
        a limit of their own; one fixed on arrival could not know how long a
        slower member's page still has. Requiring ``max_wait_time >
        timeout_between_barriers_time`` guarantees that prompt members
        outlast slow ones only while membership is fixed. In a group that
        accepts top-ups, a newcomer who joins while others wait has their
        between-barrier timeout counted from when they joined, so the waiters
        can still reach ``max_wait_time`` first.
        """
        if isinstance(max_wait_time, _DefaultMaxWaitTime):
            return (
                None
                if timeout_between_barriers_time is not None
                else float(max_wait_time)
            )
        if (
            max_wait_time is not None
            and timeout_between_barriers_time is not None
            and not callable(max_wait_time)
            and max_wait_time <= timeout_between_barriers_time
        ):
            raise ValueError(
                f"max_wait_time ({max_wait_time} s) must be longer than "
                f"timeout_between_barriers_time ({timeout_between_barriers_time} s), "
                "otherwise members who arrive promptly time out while waiting "
                "for slower ones."
            )
        return max_wait_time

    def _validate_max_wait_action(self, max_wait_action):
        if max_wait_action not in ("fail", "kick"):
            raise ValueError(
                f"max_wait_action must be 'fail' or 'kick', got {max_wait_action!r}."
            )

    def __init__(
        self,
        id_: str,
        group_type: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=None,
        max_wait_time: Optional[float] = _DEFAULT_MAX_WAIT_TIME,
        max_wait_action: Literal["fail", "kick"] = "fail",
        on_release: Optional[Callable] = None,
        fix_time_credit=False,
        timeout_between_barriers_time: Optional[float] = None,
        timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
        expected_wait=None,
        content=None,
        notify_arrivals: bool = True,
        on_arrival_message: Optional[Callable] = None,
        skip_if_not_in_group: Optional[bool] = None,
        release_grace: Optional[float] = 3,
        waiting_screen=None,
    ):
        self._validate_max_wait_action(max_wait_action)
        max_wait_time = self._check_max_wait_time(
            max_wait_time, timeout_between_barriers_time
        )
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            fix_time_credit=fix_time_credit,
            expected_wait=expected_wait,
            content=content,
            release_grace=release_grace,
            waiting_screen=waiting_screen,
        )
        self.max_wait_action = max_wait_action
        self.group_type = group_type
        self.on_release = on_release
        self.on_arrival_message = on_arrival_message
        self.notify_arrivals = bool(notify_arrivals)
        self.timeout_between_barriers_time = timeout_between_barriers_time
        if timeout_between_barriers_action not in ("kick", "fail"):
            raise ValueError(
                "timeout_between_barriers_action must be 'kick' or 'fail', "
                f"got {timeout_between_barriers_action!r}"
            )
        self.timeout_between_barriers_action = timeout_between_barriers_action
        if skip_if_not_in_group is None:
            skip_if_not_in_group = timeout_between_barriers_action == "kick"
        self.skip_if_not_in_group = skip_if_not_in_group

    def resolve(self):
        elts = super().resolve()
        if not self.skip_if_not_in_group:
            return elts
        return conditional(
            f"barrier:{self.id}:in_group",
            condition=lambda participant: (
                self.group_type in participant.active_sync_groups
            ),
            logic_if_true=elts,
            log_chosen_branch=False,
        )

    def waiting_pool_group(self, participant) -> "SyncGroup":
        """Return the participant's group of ``group_type``; its members wait together."""
        group = participant.active_sync_groups.get(self.group_type)
        if group is None:
            raise RuntimeError(
                f"Participant {participant.id} has no active sync group "
                f"of type '{self.group_type}' for barrier '{self.id}'."
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

    def _hold_progress_text(self, participant):
        """Return hold-overlay progress when arrival notices are enabled."""
        if not self.notify_arrivals or not self._participant_is_waiting(participant):
            return None
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
        return {
            "waiting_count": sum(
                1
                for member in group.active_participants
                if self._participant_is_waiting(member)
            ),
            "group_size": len(group.active_participants),
        }

    def _call_arrival_message(self, **kwargs):
        """Return author or default arrival copy for one recipient.

        Safe on reconstructed registry barriers.
        """
        callback = self.on_arrival_message
        if callback is None:
            return call_function_with_context(
                default_group_barrier_arrival_message, barrier=self, **kwargs
            )
        return callback(barrier=self, **kwargs)

    def _notify_arrivals(self, arriving_participant):
        """Publish hold progress and partner-ready notices after an arrival.

        Live timeline only. Overlay HTML comes from ``waiting_logic``.
        """
        if not self.notify_arrivals:
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
        if self._uses_timeline_hold:
            _prime_timeline_hold_records(waiting, self.id)
        # Arrivals in concurrent requests don't see each other, so the browser
        # fetches the notice and ready seats after the commit instead of being
        # sent the counts this request sees.
        for member in members:
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
                    hold_html = hold_page.overlay_html(member)
                _queue_arrival_update(member.id, hold_message=hold_html, refresh=True)
                continue
            _queue_arrival_update(member.id, refresh=True)

    def handle_max_wait_timeout(self, participant: Participant):
        """Kick from the sync group when requested, then release the barrier link."""
        if self.max_wait_action == "kick":
            self._kick_participant_after_max_wait(
                participant=participant, group_type=self.group_type
            )
        super().handle_max_wait_timeout(participant)

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        waiting_participant_ids = {p.id for p in waiting_participants}
        participants_to_release = []
        groups = self.get_waiting_groups(waiting_participants)

        for group in groups.values():
            group.check_numbers()
            outcome = _group_barrier_outcome(
                group, group.active_participants, waiting_participant_ids
            )

            if outcome == "dissolve":
                # The group can never reach its minimum size, so remove everyone
                # and release whoever is waiting here, failing them first when
                # fail_participants_below_min_size is True.
                participants_to_release.extend(
                    participant
                    for participant in group._dissolve()
                    if participant.id in waiting_participant_ids
                )
            elif outcome == "release":
                group.check_leader()
                for participant in group.active_participants:
                    participants_to_release.append(participant)

                group.last_barrier_pass_time = timenow()

                if self.on_release:
                    try:
                        self.on_release(
                            group=group,
                            participants=group.active_participants,
                            participant=group.leader,
                            barrier=self,
                        )
                    except Exception as err:
                        if is_transient_transaction_error(err):
                            raise
                        raise _BarrierAuthorHookError(
                            f"Barrier '{self.id}' on_release failed."
                        ) from err

        participants_to_release_ids = {p.id for p in participants_to_release}
        for participant in waiting_participants:
            # Release participants who reached this barrier but no longer belong
            # to the sync group (e.g., max-wait kicks or below-min-size dissolution).
            if (
                self.group_type not in participant.active_sync_groups
                and participant.id not in participants_to_release_ids
            ):
                participants_to_release.append(participant)
                participants_to_release_ids.add(participant.id)

        return participants_to_release

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        """Return whether this group visit would release, without mutating state.

        Mirrors :meth:`check_waiting_participants` followed by
        :meth:`choose_who_to_release`: late members that the between-barrier
        timeout would kick or fail count as already gone, and group size is
        recounted rather than read from ``n_active_participants``.
        """
        waiting_ids = {participant.id for participant in waiting_participants}
        for group in self.get_waiting_groups(waiting_participants).values():
            late_ids = {
                participant.id
                for participant in self._late_between_barriers(group, waiting_ids)
            }
            members = [
                participant
                for participant in group.active_participants
                if participant.id not in late_ids
            ]
            if _group_barrier_outcome(group, members, waiting_ids) != "wait":
                return True
        return any(
            self.group_type not in participant.active_sync_groups
            for participant in waiting_participants
        )

    def check_waiting_participants(self, waiting_participants: List[Participant]):
        for group in self.get_waiting_groups(waiting_participants).values():
            group.check_numbers()
            self._timeout_participants_between_barriers(group, waiting_participants)

    def get_waiting_groups(self, waiting_participants: List[Participant]):
        groups = {
            participant.active_sync_groups[
                self.group_type
            ].id: participant.active_sync_groups[self.group_type]
            for participant in waiting_participants
            if self.group_type in participant.active_sync_groups
        }
        return groups

    def _timeout_participants_between_barriers(
        self, group: "SyncGroup", waiting_participants: List[Participant]
    ):
        """Kick or fail group members who are late reaching this barrier.

        A late member whose own request holds their row is not failed now;
        they are still late on the next check.
        """
        waiting_participant_ids = {p.id for p in waiting_participants}
        late = self._late_between_barriers(group, waiting_participant_ids)
        if self.timeout_between_barriers_action == "fail":
            late = _lock_free_participants(late)
        group_size = len(group.active_participants)
        if self.timeout_between_barriers_action == "kick":
            for participant in late:
                logger.info(
                    "GroupBarrier '%s': kicking participant %s from group %s (timeout between barriers)",
                    self.id,
                    participant.id,
                    group.id,
                )
                group.remove_participant(participant, reason="out_of_time")
            if group.n_active_participants > 0 and not group.dissolving:
                for participant in late:
                    self._tell_removed_participant(participant, group, group_size)
            return
        for participant in late:
            logger.info(
                "GroupBarrier '%s': failing participant %s (timeout between barriers)",
                self.id,
                participant.id,
            )
            participant.fail("timeout between barriers")

    def _tell_removed_participant(self, participant, group, group_size):
        """Show a kicked participant a notice that their group went on without them.

        The notice lasts until they leave their current page. It is skipped if
        their own request holds their row, since they are leaving the page. A
        failing message callback is logged rather than stopping the kick.
        """
        try:
            text = self._call_arrival_message(
                kind="removed",
                waiting_count=0,
                group_size=group_size,
                recipient=participant,
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
        if not text or not _lock_free_participants([participant]):
            return
        text = str(text)
        participant.group_removal_notice = {
            "page_uuid": participant.page_uuid,
            "text": text,
        }
        _queue_arrival_update(participant.id, notice=text, removed=True)

    def _late_between_barriers(self, group: "SyncGroup", waiting_ids) -> list:
        """Return active members past the between-barrier timeout who are not waiting.

        Each member is timed from the group's last barrier pass or from when
        they joined the group, whichever is later, so newcomers to an open
        group are not late as soon as they join. A member who has started a
        page with a time limit since then is timed from that page's deadline.
        """
        if self.timeout_between_barriers_time is None:
            return []
        now = timenow()
        left_timed_page = timedelta(seconds=2 * TIME_LIMIT_GRACE_SECONDS)
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
            starts = [t for t in (group.last_barrier_pass_time, link.arrival_time) if t]
            if not starts:
                continue
            start = max(starts)
            allowed = timedelta(seconds=self.timeout_between_barriers_time)
            set_at = participant.page_deadline_set_at
            # A timed page since the last barrier or joining moves the start
            # to its deadline, leaving time for an answer sent at the deadline
            # to arrive. An earlier timed page belongs to an earlier round.
            if set_at is not None and set_at >= start:
                start = participant.page_deadline
                allowed = max(allowed, left_timed_page)
            if now > start + allowed:
                late.append(participant)
        return late


class Grouper(Barrier):
    """
    A Grouper is a kind of Barrier that assigns incoming participants into groups.
    This is a generic class that requires several methods to be overrun, in particular
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
        waiting indicator.

    waiting_logic_expected_repetitions
        Deprecated; pass ``expected_wait`` instead. Expected repetitions of
        ``waiting_logic``.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded and the participant is still not released, then the participant will be failed
        and sent to the end of the experiment. This is a hard limit counted from arrival: with explicit
        ``waiting_logic``, the server applies it even while the participant is partway through a filler page,
        so make it long enough to cover long filler pages (for example trials used as filler).

    expected_wait
        See :class:`Barrier`.

    content
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. Plain strings are shown as text; pass
        ``markupsafe.Markup`` or a dominate tag for HTML. This Grouper's
        overlay is independent of trial-maker ``sync_group_wait_content``;
        pass ``content`` here and on later :class:`~psynet.sync.GroupBarrier`
        waits if they should match. Can be a function of ``seconds_left``, as
        for :class:`Barrier`.

    fix_time_credit
        If ``True``, award fixed ``expected_wait`` credit instead of actual
        visible waiting time.

    fail_participants_below_min_size
        Applies to groups that have a minimum size and don't accept top-ups, such as those created
        by :class:`~psynet.sync.SimpleGrouper`. When a member leaves and the group falls below its
        minimum size, the group is dissolved at once. If ``True`` (default), the remaining members
        are failed. If ``False``, they are removed from the group without being failed and continue
        alone. A member whose own request is in progress is handled within about a second by the
        barrier poller instead.

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
        fail_participants_below_min_size: bool = True,
        expected_wait=None,
        fix_time_credit=False,
        content=None,
        release_grace: Optional[float] = 3,
        waiting_screen=None,
    ):
        if not id_:
            id_ = f"{group_type}_grouper"
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            expected_wait=expected_wait,
            fix_time_credit=fix_time_credit,
            content=content,
            release_grace=release_grace,
            waiting_screen=waiting_screen,
        )
        self.group_type = group_type
        self.fail_participants_below_min_size = fail_participants_below_min_size

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
            created_at=timenow(),
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

    min_group_size
        If the current group size is below this value (taking into account failed participants
        and participants who have left the experiment), then the group will be considered under-quota.
        The group will not be allowed to pass through barriers until it is at or above this size.
        If set to ``"initial_group_size"`` (default), then the minimum size will be set to the initial group size.

    batch_size
        Number of participants that should be waiting until the groups are created.
        If set to ``"initial_group_size"`` (default), then the batch size will be set to the initial group size.

    join_existing_groups
        If set to ``True``, then before a new group is created, the Grouper will check if there are any existing
        groups that are under-quota (e.g. because some participants left the experiment early).
        If so, the arriving participant will be assigned to one of these groups instead.
        Participants already waiting at the grouper join such a group on the next barrier check.
        Closed groups and groups with no active members are not joined.
        This behavior can be further customized via the ``join_criterion`` argument.

    join_criterion
        A callable that takes ``group`` and ``participant`` as arguments, and returns ``True``
        if the participant should be allowed to join the group, and ``False`` otherwise.
        To be used in conjunction with ``join_existing_groups=True``.

    fail_participants_below_min_size
        When a member leaves a group that doesn't accept top-ups and the group falls below
        ``min_group_size``, the group is dissolved at once. If ``True`` (default), the remaining
        members are failed. If ``False``, they are removed from the group without being failed and
        continue alone. A member whose own request is in progress is handled within about a second
        by the barrier poller instead.

    start_short_after
        If set, a group may start with fewer than ``batch_size`` participants once the
        longest-waiting participant has waited this many seconds and at least
        ``min_group_size`` participants are waiting. If fewer than ``initial_group_size``
        are waiting, they form one smaller group. Requires
        ``min_group_size < initial_group_size`` and a ``max_wait_time`` longer than
        ``start_short_after`` (not checked when ``max_wait_time`` is a function).
        Default: ``None`` (always wait for ``batch_size``).

    kwargs
        Further arguments to pass to Grouper.
    """

    def __init__(
        self,
        group_type: str,
        *,
        initial_group_size: Optional[int] = None,
        max_group_size: Optional[Union[int, str]] = "initial_group_size",
        min_group_size: Union[int, str] = "initial_group_size",
        batch_size: Union[int, str] = "initial_group_size",
        join_existing_groups: bool = False,
        join_criterion: Optional[Callable] = None,
        fail_participants_below_min_size: bool = True,
        start_short_after: Optional[float] = None,
        **kwargs,
    ):
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
                    "If max_group_size != 'initial_group_size', you probably want to set join_existing_groups=True."
                )

        if min_group_size == "initial_group_size":
            min_group_size = initial_group_size

        if batch_size == "initial_group_size":
            batch_size = initial_group_size

        self.initial_group_size = initial_group_size
        self.max_group_size = max_group_size
        self.min_group_size = min_group_size
        self.batch_size = batch_size
        self.join_existing_groups = join_existing_groups
        self.join_criterion = join_criterion
        self.fail_participants_below_min_size = fail_participants_below_min_size
        if start_short_after is not None and min_group_size >= initial_group_size:
            raise ValueError(
                "start_short_after needs min_group_size < initial_group_size, "
                "otherwise there is no smaller group to start with."
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

    def resolve(self):
        from .timeline import conditional, join

        return join(
            CodeBlock(self._join_existing_groups),
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
        ``batch_size``. Uses the stored member counts, which a concurrent
        join may have made stale.
        """
        if not self.join_existing_groups:
            return

        query = SimpleSyncGroup.query.filter(
            SimpleSyncGroup.group_type == self.group_type,
            SimpleSyncGroup.active.is_(True),
            SimpleSyncGroup.n_active_participants > 0,
        )

        if self.max_group_size is not None:
            query = query.filter(
                SimpleSyncGroup.n_active_participants < self.max_group_size
            )

        # Preferentially join the smallest groups, and among those, the oldest
        query = query.order_by(
            SimpleSyncGroup.n_active_participants, SimpleSyncGroup.id
        )

        for group in query.all():
            if self.join_criterion is None or self.join_criterion(
                group=group, participant=participant
            ):
                yield group

    def _claim_group_to_join(self, participant: Participant):
        """Lock and return the best group with room for this participant.

        Each candidate's row is locked ``FOR NO KEY UPDATE SKIP LOCKED``, and
        its active members are re-counted under that lock, so two joiners
        cannot both take a group's last place. A group another transaction
        is changing is skipped rather than waited for; the participant can
        try it again on a later barrier check. The joiner already holds its
        own participant row (or, in a barrier check, the waiters' rows), so
        this keeps the order participants before group without waiting on
        the group.

        Returns
        -------
        SimpleSyncGroup or None
            The locked group, or ``None`` if no candidate is free and has room.
        """
        for candidate in self._groups_to_join(participant):
            group = (
                SimpleSyncGroup.query.filter_by(id=candidate.id)
                .with_for_update(of=SimpleSyncGroup, key_share=True, skip_locked=True)
                .populate_existing()
                .first()
            )
            if group is None or not group.active:
                continue
            db.session.expire(group, ["participant_links"])
            n_members = len(group.active_participants)
            group.n_active_participants = n_members
            if n_members == 0 or (
                self.max_group_size is not None and n_members >= self.max_group_size
            ):
                continue
            return group
        return None

    def _join_existing_groups(self, participant: Participant):
        group = self._claim_group_to_join(participant)
        if group is not None:
            group.add_participant(participant)
            assert participant.active_sync_groups[self.group_type] == group
            group.check_numbers()
            group.check_leader()

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
        if len(participants) >= self.batch_size:
            return True
        return self._can_start_short(participants)

    def _can_start_short(self, participants: List[Participant]) -> bool:
        """Return whether enough people have waited long enough for a short start."""
        start_time = self._short_start_time(participants)
        return start_time is not None and time.time() >= start_time

    def _short_start_time(self, participants) -> Optional[float]:
        """Return when these waiters can start short, in epoch seconds, if they ever can."""
        if self.start_short_after is None or len(participants) < self.min_group_size:
            return None
        first_arrival = min(_arrival_time(self, p) for p in participants)
        return first_arrival.timestamp() + self.start_short_after

    def expected_release_time(self, participant) -> Optional[float]:
        """Return when the waiting participants will start short, in epoch seconds.

        ``None`` until ``min_group_size`` participants are waiting, or without
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
        content = getattr(self, "content", None)
        if self.start_short_after is None or (
            not isinstance(content, SerializedCallable)
            and "{SECONDS}" not in str(content or "")
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
            min_group_size=self.min_group_size,
            accepts_top_ups=self.join_existing_groups,
            fail_participants_below_min_size=self.fail_participants_below_min_size,
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


class Clock:
    """A :class:`Regrouper` deadline that falls every ``period`` seconds of wall-clock time.

    For example, ``deadline=Clock(45)`` starts rounds at fixed 45-second ticks.

    Parameters
    ----------
    period
        Seconds between ticks.
    """

    def __init__(self, period: float):
        if period <= 0:
            raise ValueError("Clock period must be positive.")
        self.period = float(period)


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
    ``within`` each existing group (such as a team) is its own pool. A pool is
    split into groups when every active member of its ``within`` group is
    waiting, or when its ``deadline`` passes, whichever comes first. With a
    :class:`Clock` deadline, splits happen only on clock ticks. Absent
    members are not waited for beyond the deadline once a group can be
    formed without them, and are never failed for missing a split; they join
    the pool again when they come back.

    Groups made by a regrouper don't accept top-ups and are never dissolved
    when a member leaves, so a member who drops out of a round leaves their
    partners in a smaller group rather than failing them.

    By default, when not everyone waiting fits into a group, those who have
    played the most rounds sit out, and members are kept apart from the
    people they were grouped with last time where possible. The regrouper
    counts each participant's rounds (:meth:`rounds_played`,
    :meth:`rounds_sat_out`) and, with ``roles``, gives out roles
    (:meth:`role`), all while it holds its lock, so two splits cannot give
    out the same seat twice. Each group records the regrouper that formed
    it, and each member's link to it records their role, so these counts
    come from the groups themselves.

    Parameters
    ----------
    group_type
        Type of the groups this regrouper creates, for example ``"pair"``.

    within
        Optional ``group_type`` of an existing group to regroup within, for
        example ``"team"``. Participants are only grouped with members of the
        same ``within`` group, and a pool counts as complete once all that
        group's active members are waiting. A participant without such a group
        is released ungrouped. If ``None`` (default), everyone waiting is one pool,
        which is only split at the deadline.

    group_size
        Largest group to form. The pool is split into balanced groups of at
        most this size, for example rooms of 8, 8, 7 and 7 for 30 people.

    min_group_size
        Smallest group to form: 2 by default, or ``group_size`` with
        ``roles``. A pool is only split once this many of its members are
        waiting.

    deadline
        When to stop waiting for absent members. A number is seconds since the
        first of the pool's waiting members arrived, or since the pool's
        previous split if that is later. Make it longer than a round takes:
        otherwise members who finish a round early are split again before
        the rest are back. ``Clock(period)`` splits at fixed wall-clock ticks
        instead, even when everyone is already waiting, if at least
        ``min_group_size`` members were waiting at the tick. ``None`` (default)
        waits until the pool is complete, which needs ``within``.

    roles
        Optional role names, for example ``["proposer", "responder"]``. Each
        group then has one member per role, so ``group_size`` must equal the
        number of roles, and groups are never smaller. Read a member's role
        with :meth:`role`. By default each member gets the role they have had
        least often, so roles alternate from round to round.

    keep_roles
        If ``True``, a participant keeps the role they first play for the
        rest of the experiment. Participants without a role get one when they
        are split, choosing the role that lets the most waiting participants
        play, or else the role that fewer participants still in the
        experiment play. Those of a role nobody is free to pair with sit out;
        a newcomer who sits out gets a role again at the next split.

    form_groups
        Optional callable ``form_groups(members, within_group, regrouper)``
        that returns a list of groups, each a list of participants, replacing
        the default grouping described above. Members who are not placed are
        left over. With ``roles``, list each group's members in the order of
        ``roles`` if ``keep_roles`` is ``False``; with ``keep_roles``, members
        already have their roles when it is called. Subclasses can override
        :meth:`form_groups` instead. The callable must be a module-level
        function so it can be stored with the barrier.

    release_left_over
        If ``True``, participants left over after a split continue ungrouped,
        for example to a sit-out page, and come back for the next split. If
        ``False`` (default), they keep waiting for the next split. With
        ``within``, when too few are waiting to form any group, for example
        one player whose teammates are still playing a round, they wait for
        those teammates for up to one more ``deadline`` (or ``Clock`` tick)
        before they are released ungrouped, or until ``max_wait_time`` if
        there is no deadline. Taking members who stop playing out of the
        ``within`` group, for example with ``remove_participant``, means
        nobody waits for them.

    on_release
        Optional callback ``on_release(within_group, groups, left_over, regrouper)``
        run after each split that forms at least one group, after roles are
        given out. A late member can make a split of their own in the same
        round, so count rounds per participant (see :meth:`rounds_played`)
        rather than here. ``barrier`` is passed too, as for
        :class:`GroupBarrier`.

    max_wait_time
        Longest a participant waits at the regrouper before being failed.
        Default: 300 seconds. With ``release_left_over`` and ``within``, it
        must be longer than twice the ``deadline`` (or ``Clock`` period), so
        that a player waiting alone sits out instead of being failed.

    content
        Message shown while waiting. A ``{SECONDS}`` placeholder becomes a live
        countdown to the pool's deadline, for example
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
        group_size: int,
        within: Optional[str] = None,
        min_group_size: Optional[int] = None,
        deadline: Optional[Union[float, Clock]] = None,
        roles: Optional[Sequence[str]] = None,
        keep_roles: bool = False,
        form_groups: Optional[Callable] = None,
        release_left_over: bool = False,
        on_release: Optional[Callable] = None,
        max_wait_time: Optional[float] = 300,
        **kwargs,
    ):
        if roles is not None:
            if len(roles) != group_size or len(set(roles)) != len(roles):
                raise ValueError(
                    "Pass one distinct role per member: len(roles) must equal group_size."
                )
            if min_group_size not in (None, group_size):
                raise ValueError("With roles, every group has group_size members.")
            min_group_size = group_size
        elif keep_roles:
            raise ValueError("keep_roles needs roles.")
        if min_group_size is None:
            min_group_size = 2
        if min_group_size < 1 or group_size < min_group_size:
            raise ValueError("Need 1 <= min_group_size <= group_size.")
        if deadline is None and within is None:
            raise ValueError(
                "A Regrouper without `within` needs a deadline, because it cannot "
                "tell when everyone is present."
            )
        kwargs.setdefault("id_", f"{group_type}_regrouper")
        super().__init__(group_type=group_type, max_wait_time=max_wait_time, **kwargs)
        self.within = within
        self.group_size = group_size
        self.min_group_size = min_group_size
        self.clock_period = deadline.period if isinstance(deadline, Clock) else None
        self.deadline = None if isinstance(deadline, Clock) else deadline
        self.roles = None if roles is None else list(roles)
        self.keep_roles = keep_roles
        self.form_groups_function = form_groups
        self.release_left_over = release_left_over
        self.on_release = on_release
        longest_lone_wait = self.clock_period or self.deadline
        if (
            release_left_over
            and within is not None
            and longest_lone_wait is not None
            and isinstance(max_wait_time, (int, float))
            and max_wait_time <= 2 * longest_lone_wait
        ):
            raise ValueError(
                f"max_wait_time ({max_wait_time} s) must be longer than twice the "
                f"deadline ({longest_lone_wait} s): with release_left_over, a player "
                "waiting alone for teammates who are still playing waits up to two "
                "deadlines before sitting out."
            )

    def receive_participant(self, participant: Participant):
        previous = participant.active_sync_groups.get(self.group_type)
        if previous is not None:
            previous.remove_participant(participant, reason="moved_on")
        Barrier.receive_participant(self, participant)

    def form_groups(self, members, within_group=None):
        """Return the groups to form from one pool's waiting members.

        By default members are put into balanced groups of at most
        ``group_size`` and at least ``min_group_size``, or into one group per
        set of ``roles``. Those who have played the most rounds sit out, and
        members are kept apart from last time's group where possible.
        """
        if self.form_groups_function is not None:
            return self.form_groups_function(
                members=members, within_group=within_group, regrouper=self
            )
        history = self._history(members)
        # Shuffled first, so that ties are broken at random.
        members = sorted(
            random.sample(members, len(members)), key=lambda m: history.rounds[m.id]
        )
        if self.keep_roles:
            by_role = [[m for m in members if self.role(m) == r] for r in self.roles]
            n_groups = min(len(players) for players in by_role)
            players = [players[:n_groups] for players in by_role]
            return self._best_groups(
                lambda: [
                    list(group)
                    for group in zip(*(random.sample(p, n_groups) for p in players))
                ],
                history,
            )
        n_placed = sum(
            len(group)
            for group in _balanced_groups(members, self.group_size, self.min_group_size)
        )
        players = members[:n_placed]
        return self._best_groups(
            lambda: _balanced_groups(players, self.group_size, self.min_group_size),
            history,
        )

    def rounds_played(self, participant) -> int:
        """Return how many groups this regrouper has put ``participant`` in."""
        return len(self._links([participant.id]))

    def rounds_sat_out(self, participant) -> int:
        """Return how often ``participant`` was released without a group (see ``release_left_over``)."""
        return ParticipantLinkBarrier.query.filter_by(
            barrier_id=self.id, participant_id=participant.id, sat_out=True
        ).count()

    def role(self, participant) -> Optional[str]:
        """Return ``participant``'s role (see ``roles``).

        Without ``keep_roles`` this is their role in the latest group this
        regrouper put them in, even after they were removed from it, so a
        reloaded page still shows it. It is ``None`` before their first
        group, and from when they come back to the regrouper until their
        next group, so also after they sat a round out.
        """
        links = self._links([participant.id])
        if self.keep_roles:
            kept = next((link.role for link in links if link.role), None)
            return kept or self._waiting_role(participant)
        if not links:
            return None
        latest_visit = (
            ParticipantLinkBarrier.query.filter_by(
                barrier_id=self.id, participant_id=participant.id
            )
            .order_by(ParticipantLinkBarrier.id.desc())
            .first()
        )
        if (
            latest_visit is not None
            and latest_visit.arrival_time > links[-1].arrival_time
        ):
            return None
        return links[-1].role

    def _waiting_role(self, participant) -> Optional[str]:
        """Return the role given to a waiting newcomer for the coming split."""
        visit = self._visits([participant]).get(participant.id)
        return None if visit is None else visit.role

    @property
    def _custom_grouping(self) -> bool:
        return (
            self.form_groups_function is not None
            or type(self).form_groups is not Regrouper.form_groups
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

    def _history(self, members) -> "_RegroupHistory":
        """Return the members' rounds, last group-mates and role counts, keyed by ID."""
        rounds = {m.id: 0 for m in members}
        role_counts = {m.id: {} for m in members}
        latest_group = {}
        for link in self._links(list(rounds)):
            rounds[link.participant_id] += 1
            latest_group[link.participant_id] = link.sync_group_id
            if link.role:
                counts = role_counts[link.participant_id]
                counts[link.role] = counts.get(link.role, 0) + 1
        mates = {}
        if latest_group:
            for link in ParticipantLinkSyncGroup.query.filter(
                ParticipantLinkSyncGroup.sync_group_id.in_(set(latest_group.values()))
            ):
                mates.setdefault(link.sync_group_id, set()).add(link.participant_id)
        last_mates = {
            pid: mates.get(latest_group.get(pid), set()) - {pid} for pid in rounds
        }
        return _RegroupHistory(rounds, last_mates, role_counts)

    def _best_groups(self, make_groups, history, attempts: int = 50):
        """Return the groups from ``make_groups()`` with the fewest repeats.

        A repeat is a member grouped with someone from their last group, or,
        when roles alternate, a member who must take a role they have had
        more often than another.
        """
        best, best_cost = [], None
        for _ in range(attempts):
            groups = make_groups()
            cost = sum(self._repeats(group, history) for group in groups)
            if best_cost is None or cost < best_cost:
                best, best_cost = groups, cost
            if cost == 0:
                break
        return best

    def _repeats(self, group, history) -> int:
        repeats = sum(
            other.id in history.last_mates[member.id]
            for member in group
            for other in group
        )
        if self.roles and not self.keep_roles:
            for member, role in self._least_held_roles(group, history).items():
                counts = history.role_counts[member.id]
                repeats += counts.get(role, 0) - min(
                    counts.get(r, 0) for r in self.roles
                )
        return repeats

    def _give_kept_roles(self, members):
        """Give members without a role the role that lets the most of them play.

        When the waiting members' roles are balanced, a newcomer takes the
        role that fewer participants still in the experiment play.
        """
        roles = {member.id: self.role(member) for member in members}
        newcomers = [m for m in members if roles[m.id] is None]
        if not newcomers:
            return
        waiting = {role: 0 for role in self.roles}
        for role in roles.values():
            if role is not None:
                waiting[role] += 1
        in_game = {role: 0 for role in self.roles}
        in_game.update(self._players_per_role())
        visits = self._visits(newcomers)
        for member in random.sample(newcomers, len(newcomers)):
            tally = next(
                (t for t in (waiting, in_game) if len(set(t.values())) > 1), waiting
            )
            fewest = min(tally.values())
            role = random.choice([r for r, n in tally.items() if n == fewest])
            visits[member.id].role = role
            waiting[role] += 1
            in_game[role] += 1

    def _players_per_role(self) -> Dict[str, int]:
        """Return how many participants still in the experiment have played each role."""
        link = ParticipantLinkSyncGroup
        rows = (
            db.session.query(link.role, func.count(link.participant_id.distinct()))
            .join(SyncGroup)
            .join(Participant, Participant.id == link.participant_id)
            .filter(
                SyncGroup.grouper_id == self.id,
                link.role.isnot(None),
                Participant.status == "working",
                Participant.failed.is_(False),
            )
            .group_by(link.role)
        )
        return dict(rows.all())

    def _record_roles(self, group, members):
        """Store each member's role on their link to the new group."""
        if not self.roles:
            return
        if self.keep_roles:
            roles = {member: self.role(member) for member in members}
        elif self._custom_grouping:
            roles = dict(zip(members, self.roles))
        else:
            roles = self._least_held_roles(members, self._history(members))
        db.session.flush()
        links = {link.participant_id: link for link in group.participant_links}
        for member, role in roles.items():
            links[member.id].role = role

    def _least_held_roles(self, members, history) -> dict:
        """Return ``{member: role}``, giving each role to whoever has had it least.

        Ties go by member order, which ``form_groups`` shuffles, so the
        assignment scored when choosing groups is the one that is stored.
        """
        unassigned = list(members)
        roles = {}
        for role in self.roles:
            member = min(
                unassigned,
                key=lambda m: history.role_counts[m.id].get(role, 0),
            )
            unassigned.remove(member)
            roles[member] = role
        return roles

    def expected_release_time(self, participant) -> Optional[float]:
        """Return when this participant's pool will be split at the latest, in epoch seconds."""
        if self.id not in participant.active_barriers:
            return None
        within_group = self._within_group(participant)
        if self.within is not None and within_group is None:
            return None
        if self.clock_period is None and self.deadline is None:
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
        if self.clock_period is None:
            return self._deadline_reference(within_group, pool) + self.deadline
        now = time.time()
        tick = _latest_tick(now, self.clock_period)
        waited_for_tick = _arrival_time(self, participant).timestamp() <= tick
        if waited_for_tick and self._enough_waiting_at_tick(within_group, pool, now):
            # Due now: the poller has not split the pool yet.
            return tick
        return tick + self.clock_period

    def waiting_pool_group(self, participant) -> Optional["SyncGroup"]:
        """Return the participant's ``within`` group, so each team waits in its own pool."""
        return self._within_group(participant)

    def choose_who_to_release(self, waiting_participants: List[Participant]):
        released = []
        for within_group, members in self._pools(waiting_participants):
            if self.within is not None and within_group is None:
                released += members
                continue
            if not self._pool_is_ready(within_group, members):
                continue
            if self.clock_period is not None:
                members = self._waiting_at_tick(members, time.time())
            released += self._split(within_group, members)
        return released

    def would_release(self, waiting_participants: List[Participant]) -> bool:
        return any(
            (self.within is not None and within_group is None)
            or self._pool_is_ready(within_group, members)
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
        if self.clock_period is None and self._pool_is_complete(within_group, members):
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

        Not while teammates are still active elsewhere, for example still
        playing a round, so that a lone waiter waits for them rather than
        sitting out round after round; but only for one more deadline, in case
        those teammates have stopped playing.
        """
        return self.release_left_over and (
            within_group is None
            or self._pool_is_complete(within_group, members)
            or self._waited_an_extra_deadline(within_group, members)
        )

    def _waited_an_extra_deadline(self, within_group, members) -> bool:
        """Return whether the pool has waited a deadline (or ``Clock`` tick) past the usual one."""
        now = time.time()
        if self.clock_period is not None:
            previous_tick = _latest_tick(now, self.clock_period) - self.clock_period
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
        return self.min_group_size

    def _deadline_passed(self, within_group, members) -> bool:
        now = time.time()
        if self.clock_period is not None:
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
        tick = _latest_tick(now, self.clock_period)
        return [p for p in members if _arrival_time(self, p).timestamp() <= tick]

    def _enough_waiting_at_tick(self, within_group, members, now) -> bool:
        """Return whether enough members were already waiting at the latest unused tick."""
        last_split = self._last_split(within_group)
        if last_split is not None and last_split >= _latest_tick(
            now, self.clock_period
        ):
            return False
        at_tick = self._waiting_at_tick(members, now)
        return len(at_tick) >= self._smallest_pool_to_split(within_group, at_tick)

    def _last_split(self, within_group) -> Optional[float]:
        """Return when this regrouper last formed groups in this pool, in epoch seconds."""
        within_id = None if within_group is None else within_group.id
        latest = (
            db.session.query(func.max(SyncGroup.created_at))
            .filter(
                SyncGroup.grouper_id == self.id,
                SyncGroup.within_group_id.is_(None)
                if within_id is None
                else SyncGroup.within_group_id == within_id,
            )
            .scalar()
        )
        return None if latest is None else latest.timestamp()

    def _split(self, within_group, members):
        """Form this pool's groups and return the participants to release."""
        if self.keep_roles:
            self._give_kept_roles(members)
        plan = [
            list(group_members)
            for group_members in self.form_groups(members, within_group=within_group)
            if group_members
        ]
        self._check_plan(plan, members)
        if self.roles:
            for group_members in plan:
                if len(group_members) != len(self.roles):
                    raise ValueError(
                        f"Regrouper '{self.id}': with roles, form_groups must "
                        f"return groups of {len(self.roles)}."
                    )
        groups = [
            self._make_group(group_members, within_group) for group_members in plan
        ]
        for group, group_members in zip(groups, plan):
            self._record_roles(group, group_members)
        placed = {p.id for group in groups for p in group.participants}
        left_over = [p for p in members if p.id not in placed]
        if not groups:
            if self._may_release_only_left_over(within_group, members):
                self._record_sit_outs(left_over)
                return left_over
            return []
        if self.on_release:
            try:
                self.on_release(
                    within_group=within_group,
                    groups=groups,
                    left_over=left_over,
                    regrouper=self,
                    barrier=self,
                )
            except Exception as err:
                if is_transient_transaction_error(err):
                    raise
                raise _BarrierAuthorHookError(
                    f"Regrouper '{self.id}' on_release failed."
                ) from err
        released = [p for group in groups for p in group.participants]
        if self.release_left_over:
            self._record_sit_outs(left_over)
            released += left_over
        return released

    def _record_sit_outs(self, left_over):
        for visit in self._visits(left_over).values():
            visit.sat_out = True

    def _check_plan(self, plan, members):
        """Raise if ``form_groups`` placed someone twice or placed a non-member."""
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

    def _make_group(self, participants, within_group=None):
        """Create a fixed group that never dissolves or fails its members."""
        return self._create_group(
            participants,
            within_group_id=None if within_group is None else within_group.id,
            initial_group_size=len(participants),
            max_group_size=len(participants),
            min_group_size=1,
            accepts_top_ups=False,
            fail_participants_below_min_size=False,
        )


class _RegroupHistory(NamedTuple):
    """Regrouper history of a set of members, each field keyed by participant ID."""

    rounds: Dict[int, int]
    last_mates: Dict[int, set]
    role_counts: Dict[int, Dict[str, int]]


def group_seats(group) -> Dict[int, int]:
    """Return ``{participant_id: seat}`` for everyone who has been in ``group``.

    Seats number members in the order they first joined. Links are kept when
    members leave, so seats never change while the group exists, and pages
    can refer to members without their IDs.
    """
    seats = {}
    links = sorted(
        group.participant_links, key=lambda link: (link.id is None, link.id or 0)
    )
    for link in links:
        seats.setdefault(link.participant_id, len(seats))
    return seats


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
    leader_id = Column(Integer, ForeignKey("participant.id"))
    # Dissolution started but skipped members whose rows were busy; the
    # barrier poller finishes it.
    dissolving = Column(Boolean, default=False)
    # The grouper that formed the group, when, and for a Regrouper with
    # ``within``, the group it regrouped within.
    grouper_id = Column(String, index=True)
    created_at = Column(DateTime)
    within_group_id = Column(Integer, index=True)

    participant_links = relationship(
        "ParticipantLinkSyncGroup",
        cascade="all, delete-orphan",
    )

    n_active_participants = Column(Integer)

    @property
    def participants(self) -> List[Participant]:
        """Read-only list of participants currently in the group (links with ``active=True``).

        Use ``group.add_participant(participant)`` to add a participant.
        """
        links = [
            link for link in self.participant_links if getattr(link, "active", True)
        ]
        _load_link_participants(links)
        return _ReadOnlyParticipantList(link.participant for link in links)

    def add_participant(self, participant: Participant):
        """Add a participant to the group (creates an active link).

        If an active member already has the newcomer's pseudonym and this is
        the newcomer's first group, the newcomer is given a free one, so
        members can tell each other apart. Later groups never rename anyone,
        so a pseudonym stays the same once others have seen it.
        """
        self._give_distinct_pseudonym(participant)
        _forget_active_sync_group(participant)
        # Setting ``sync_group`` also appends to ``participant_links``, and lets
        # ``participant.active_sync_groups`` see the group before a flush.
        ParticipantLinkSyncGroup(
            participant=participant,
            sync_group=self,
            active=True,
            arrival_time=timenow(),
        )
        _notify_membership_change(self, newcomer=participant)

    @property
    def active_participants(self) -> List[Participant]:
        return [p for p in self.participants if not p.failed and p.status == "working"]

    def _give_distinct_pseudonym(self, participant):
        """Store a free pseudonym for ``participant`` if an active member has theirs.

        Only in the participant's first group; see :meth:`add_participant`.
        """
        # Cached for this transaction, so forming a large group stays linear.
        transaction = db.session().get_transaction()
        cached = self.__dict__.get("_pseudonym_keys")
        if cached is not None and transaction is not None and cached[0] is transaction:
            taken = cached[1]
        else:
            others = [p for p in self.active_participants if p.id != participant.id]
            taken = {(p.pseudonym.color, p.pseudonym.animal) for p in others}
            self.__dict__["_pseudonym_keys"] = (transaction, taken)
        pseudonym = participant.pseudonym
        keys = (pseudonym.color, pseudonym.animal)
        first_group = not participant.sync_group_links
        if keys in taken and first_group:
            from .experiment import get_experiment

            replacement = get_experiment().pseudonym_scheme.replacement(
                taken, participant
            )
            if replacement is not None:
                participant.set_pseudonym(*replacement)
                keys = replacement
        taken.add(keys)

    leader = relationship(
        "psynet.participant.Participant",
        cascade="all",
    )

    def check_leader(self):
        """Make the lowest-id active member leader if the leader has left.

        Setting ``leader_id`` makes PostgreSQL lock the new leader's row for
        its foreign-key check, so only a member whose row is free (or already
        held by this transaction) is chosen, and only that member's row is
        locked. If every remaining member is busy in their own request, the
        old leader stays until the next call, for example the group's next
        barrier release.
        """
        active_participants = sorted(self.active_participants, key=lambda p: p.id)
        if len(active_participants) == 0:
            self.leader = None
        elif self.leader not in active_participants:
            for participant in active_participants:
                if _lock_free_participants([participant]):
                    self.leader = participant
                    break

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
        self.active = False
        self.end_time = timenow()
        for participant in self.participants:
            _forget_active_sync_group(participant)

    def check_numbers(self):
        self.n_active_participants = len(self.active_participants)

    def remove_participant(
        self, participant: Participant, reason: Optional[str] = None
    ):
        """Remove a participant from the group.

        Parameters
        ----------
        participant
            The member to remove.
        reason
            Optional reason stored on their link, such as ``"moved_on"`` for a
            member who went on to their next group or ``"out_of_time"`` for one
            kicked by a timeout. :class:`~psynet.group_prompt.GroupPrompt`
            uses it to label former members.
        """
        _forget_active_sync_group(participant)
        for link in self.participant_links:
            is_member = (
                link.participant is participant or link.participant_id == participant.id
            )
            if is_member and link.active:
                link.active = False
                link.removal_reason = reason
        self.check_numbers()
        _notify_membership_change(self)
        if self.n_active_participants == 0 and not getattr(
            self, "accepts_top_ups", False
        ):
            self.close()
        else:
            self.check_leader()

    def _dissolve(self):
        """Remove every active member, failing them if the group says so.

        Other members' rows are locked without waiting. A member whose own
        request holds their row is skipped and the group is marked
        ``dissolving``, so the barrier poller finishes the job once that
        request commits. Waiting here could deadlock with that member's
        request, which holds their row and then needs this group's row.

        Returns
        -------
        list of Participant
            The members removed now.
        """
        self._dissolving_below_min_size = True
        try:
            remaining = list(self.active_participants)
            removed = _lock_free_participants(remaining)
            for participant in removed:
                if getattr(self, "fail_participants_below_min_size", True):
                    participant.fail("sync group below minimum size")
                SyncGroup.remove_participant(self, participant)
            self.check_numbers()
            self.dissolving = len(removed) < len(remaining)
            if self.n_active_participants == 0:
                self.close()
        finally:
            self._dissolving_below_min_size = False
        return removed


class SimpleSyncGroup(SyncGroup):
    """
    A SyncGroup that is created by a SimpleGrouper.
    """

    initial_group_size = Column(Integer)
    max_group_size = Column(Integer)
    min_group_size = Column(Integer)
    accepts_top_ups = Column(Boolean)
    fail_participants_below_min_size = Column(Boolean, default=True)

    def remove_participant(
        self, participant: Participant, reason: Optional[str] = None
    ):
        super().remove_participant(participant, reason=reason)
        self.dissolve_if_below_min_size()

    def dissolve_if_below_min_size(self):
        """Dissolve a group without top-ups that fell below its minimum size.

        Members who are busy in another request are handled shortly after
        by the barrier poller; see :meth:`SyncGroup._dissolve`.
        """
        if (
            getattr(self, "_dissolving_below_min_size", False)
            or self.accepts_top_ups
            or self.n_active_participants >= self.min_group_size
        ):
            return
        self._dissolve()


def _lock_free_participants(participants):
    """Lock participants' rows without waiting and return the free ones.

    ``SKIP LOCKED`` leaves out rows another transaction holds; rows this
    transaction already holds count as free. Code that fails or removes
    *other* participants uses this, because their own requests lock their
    row first and may then need a sync group row this transaction holds.
    The returned participants are refreshed, and any who failed or left
    meanwhile are dropped.
    """
    if not participants:
        return []
    ids = sorted({participant.id for participant in participants})
    locked = set(
        db.session.execute(
            select(Participant.id)
            .where(Participant.id.in_(ids))
            .order_by(Participant.id)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    free = []
    for participant in participants:
        if participant.id not in locked:
            continue
        db.session.refresh(participant, ["failed", "status", "page_uuid"])
        if not participant.failed and participant.status == "working":
            free.append(participant)
    return free


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
            raise ValueError(
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
    # The member's role in the group (see ``Regrouper(roles=...)``).
    role = Column(String)

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
    # A Regrouper with ``keep_roles`` gave a newcomer this role for the
    # coming split; it is kept once they play it.
    role = Column(String)
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
            participant = (
                experiment._participant_request_query()
                .with_for_update(of=Participant, nowait=True)
                .populate_existing()
                .get(participant_id)
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
    """Return ``{group_id, seats, members}`` for each of the participant's groups.

    ``seats`` (see :func:`group_seats`) are those of the members waiting at
    a barrier of the group, as :class:`~psynet.group_prompt.GroupPrompt`
    ticks them, and ``members`` those of all active members, so that it can
    redraw the group when someone joins or leaves.
    """
    ready = []
    for group in participant.active_sync_groups.values():
        seats = group_seats(group)
        members = group.active_participants
        waiting = [seats[m.id] for m in members if waiting_barrier_ids(m, group)]
        ready.append(
            {
                "group_id": group.id,
                "seats": sorted(waiting),
                "members": sorted(seats[m.id] for m in members),
            }
        )
    return ready


def _notify_membership_change(group, newcomer=None):
    """Have the other members of ``group`` fetch their notice and group again."""
    if getattr(group, "_dissolving_below_min_size", False):
        return
    for member in group.active_participants:
        if member is not newcomer:
            _queue_arrival_update(member.id, refresh=True)


def waiting_barrier_ids(participant, group):
    """Return the IDs of the barriers of ``group`` that ``participant`` is waiting at."""
    return [
        barrier_id
        for barrier_id, link in participant.active_barriers.items()
        if not link.released
        and link.barrier_instance is not None
        and link.barrier_instance.group_id == group.id
    ]


def _interruptible_waiting_barrier(page, participant):
    """Return the barrier whose ``waiting_logic`` this page belongs to, if a release may end it.

    Pages of a trial that is still waiting for its answer are left to run
    to their end, so that the trial is not finalized without an answer.
    ``participant.current_trial`` is not cleared after a trial, so an
    earlier, answered trial doesn't count.
    """
    barrier = (getattr(page, "links", None) or {}).get("barrier")
    if not isinstance(barrier, Barrier) or barrier.release_grace is None:
        return None
    if not _is_inside_waiting_loop(barrier, participant):
        return None
    if participant.failed:
        return None
    trial = participant.current_trial
    if trial is not None and not trial.complete:
        return None
    return barrier


def _is_inside_waiting_loop(barrier, participant):
    """Return whether the participant's timeline position is inside the barrier's ``waiting_logic`` loop."""
    markers = getattr(barrier, "_waiting_loop_markers", None)
    position = participant.elt_id
    if not markers or position is None:
        return True
    start, end = (marker.id for marker in markers)
    depth = len(start)
    return (
        len(position) >= depth
        and list(position[: depth - 1]) == list(start[:-1])
        and start[-1] < position[depth - 1] < end[-1]
    )


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


def _waiting_page_barrier_id(participant):
    """Return the ID of the barrier whose ``waiting_logic`` the participant is in, or ``None``."""
    for barrier_id, link in participant.active_barriers.items():
        # A hold's record may not be flushed yet, so test the object, not its id.
        if not link.released and link.timeline_hold is None:
            return barrier_id
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
    barrier_id = None if participant.failed else _waiting_page_barrier_id(participant)
    if barrier_id is None:
        return None
    return {"barrier_id": barrier_id, "release_grace_ms": None}


def waiting_status_payload(unique_id, barrier_id):
    """Return whether a participant on a waiting page has been released.

    Waiting pages fetch this about every 2 seconds. ``ends_page`` tells
    whether the participant's current page would now accept an interrupt
    (see :func:`released_waiting_barrier`); a released participant whose
    page may not be ended, for example inside an unfinished trial, gets
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


def _removed_from_group_notice(participant) -> Optional[str]:
    """Return the notice for a participant removed from a group on their current page."""
    stored = getattr(participant, "group_removal_notice", None)
    if stored is None or stored["page_uuid"] != participant.page_uuid:
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
                if not isinstance(barrier, GroupBarrier) or not barrier.notify_arrivals:
                    continue
                if barrier._participant_is_waiting(participant):
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
                    recipient=participant,
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


def _evaluate_held_instance(instance_id):
    """Evaluate one already-claimed visit and commit.

    Sets the ORM ``lock_timeout`` so check/commit cannot wait forever while
    the extra connection holds the visit key. Nested waiter ``NOWAIT`` misses
    return ``(False, [])`` so last-arrival can retry. Author ``on_release``
    and spec errors also return ``(False, [])`` so the group stays waiting.
    Other non-transient check errors propagate so ``GET /timeline`` does not
    first-paint a hold. Released waiter ids are drained here so they cannot
    leak in ``session.info``; last-arrival discards them, the poller skips.
    """
    db.session.expire_all()
    _set_transaction_lock_timeout(get_config().get("timeline_lock_timeout_seconds"))
    instance = BarrierInstance.query.get(instance_id)
    try:
        with db.session.begin_nested():
            ok = _check_claimed_barrier_instance(instance, already_claimed=True)
    except Exception as err:
        if is_transient_transaction_error(err):
            logger.debug(
                "Barrier '%s' instance %s deferred because a waiter is locked.",
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
    check. A blocking claim wait that hits ``lock_timeout`` raises so
    ``GET /timeline`` can return HTTP 503. A waiter-row ``NOWAIT`` miss
    still returns ``False`` so the caller can retry once.

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
    waiter. Author ``on_release`` and spec errors are reported the same way.
    The poller retries once in the same sweep, then queues the visit like a
    checked one.
    """
    barrier_id = None
    try:
        with _hold_barrier_instance_claim(instance_id, wait=False) as claimed:
            if not claimed:
                return True
            instance = BarrierInstance.query.get(instance_id)
            barrier_id = None if instance is None else instance.barrier_id
            if not _check_and_skip_held_instance(instance_id):
                return True
            return False
    except Exception as err:
        db.session.rollback()
        if is_transient_transaction_error(err):
            qualifier = " still locked on retry" if retry else " deferred"
            logger.debug(
                "Barrier '%s' instance %s%s because a waiter is locked.",
                barrier_id,
                instance_id,
                qualifier,
            )
            return True
        qualifier = " on retry" if retry else ""
        logger.exception(
            "Failed to process barrier '%s' instance %s%s.",
            barrier_id,
            instance_id,
            qualifier,
        )
    return False


def _finish_dissolving_groups():
    """Remove or fail members that a group dissolution had to skip.

    Each group is handled in its own transaction. A group another request
    holds, and members still busy, are left for the next sweep. Group and
    member rows are taken without waiting; other lock waits while failing a
    member, for example on their trials, are bounded by
    ``timeline_lock_timeout_seconds``.
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
            group = (
                SyncGroup.query.filter_by(id=group_id)
                .with_for_update(of=SyncGroup, key_share=True, skip_locked=True)
                .populate_existing()
                .first()
            )
            if group is not None and group.active and group.dissolving:
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

    Each sweep first finishes group dissolutions that skipped busy members
    and times out overdue waiters, then checks visits, least
    recently checked first, with new or changed ones given a head start. Each
    of the two steps stops starting new work after
    ``_POLLER_SWEEP_BUDGET_SECONDS``, so thousands of idle waiters cannot
    keep the poller busy; the rest wait for later sweeps. One item can still
    overrun the budget while it waits for a row lock. Live waiters still
    check their own visit on each hold poll.
    """
    seen = set()
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
    active :class:`SyncGroup` with no active members, including emptied
    groups that accept top-ups, unless the group is still dissolving.
    Groups locked by another request are skipped until the next tick.

    Dedicated sessions keep these maintenance commits separate from any
    transaction owned by the caller. Each group's recount runs in its own
    transaction so a failure cannot roll back sibling groups already processed.
    """
    with Session(bind=db.engine) as session:
        group_ids = [
            group_id
            for (group_id,) in (
                session.query(SyncGroup.id)
                .filter(SyncGroup.active.is_(True))
                .order_by(SyncGroup.id)
            )
        ]

    for group_id in group_ids:
        try:
            with Session(bind=db.engine) as session:
                _set_transaction_lock_timeout(
                    get_config().get("timeline_lock_timeout_seconds"),
                    session=session,
                )
                group = (
                    session.query(SyncGroup)
                    .filter_by(id=group_id)
                    .with_for_update(of=SyncGroup, skip_locked=True)
                    .populate_existing()
                    .first()
                )
                if group is None:
                    continue
                group.check_numbers()
                if group.n_active_participants == 0 and not group.dissolving:
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

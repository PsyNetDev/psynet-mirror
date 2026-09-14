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
    rely on these groups to decide who to release together.

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

- Finds waiting barrier instances.
- Claims each with a PostgreSQL advisory transaction lock on a dedicated
  connection, leaving definition and instance metadata available to arrival
  requests. That extra transaction stays open until skip-after-commit
  finishes, so last-arrival ``GET /timeline`` still waits for the same key
  after waiter row locks drop.
- Locks waiters with ``FOR UPDATE NOWAIT``. If any waiter is already locked
  (for example by ``POST /response``), it skips that barrier this tick instead
  of blocking the poller.
- Evaluates the barrier's release hooks in an isolated transaction, then
  skips released hold waiters one row at a time after that commit.
- Logs and skips failures per barrier so one bad barrier does not stall others.
- Keeps hold-wake publishes unpublished until the sweep returns.

Each default barrier visit links to a durable ``TimelineHoldRecord``. Releasing
the link accounts waiting through the release time and queues a targeted browser
wake. Each participant's hold channel (`psynet_timeline_hold:<id>`) publishes
that wake only after the database transaction commits; the browser then
rechecks the authoritative link state.

``Barrier`` also queues those hooks when a participant arrives. After the
arrival transaction commits, the response route evaluates the barrier in a
short coordination transaction before rendering. That lets a ``Grouper`` form
groups and a ``GroupBarrier`` release the group without waiting for the poller,
while waiter locks remain outside the main write transaction. After that
check commits, released hold waiters are skipped one row at a time so a
partner ``GET /timeline`` can lock itself. The visit claim is held on a
second connection until that skip finishes, so last-arrival's wait for the
same key cannot first-paint a hold in the gap after partner row locks drop.
The ORM session must not acquire that key while the extra transaction is
open. Last-arrival also pins those visits in Redis until HTML/JSON render
returns, so this poller (another process) does not publish hold wakes during
that render. Waiter rows stay ``NOWAIT`` so a locked partner cannot stall
that request for ``lock_timeout``.

Callable attributes on barriers (e.g., ``on_release``) persist through
:mod:`psynet.barrier_spec` so each ``BarrierInstance`` keeps stable release
behavior without pickling waiting pages. The reconstructed object is a
release/callback receiver, not a wait page. See :class:`Barrier` for which
methods are live-only.
"""

import random
import uuid
from contextlib import contextmanager
from math import floor
from typing import Callable, List, Literal, Optional, Union

from dallinger import db
from dallinger.models import timenow
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import (
    Session,
    backref,
    deferred,
    joinedload,
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
    _set_transaction_lock_timeout,
    is_transient_transaction_error,
)
from psynet.field import PythonClass
from psynet.page import UnsuccessfulEndPage
from psynet.participant import Participant
from psynet.serialize import serialize_callable
from psynet.timeline import CodeBlock, EltCollection, conditional
from psynet.timeline_hold import (
    _defer_timeline_hold_wakes,
    _mark_last_arrival_follow_instance,
    _mark_last_arrival_render_instance,
    _queue_arrival_update,
    _queue_timeline_hold_wake,
    _TimelineHoldPage,
    default_group_barrier_arrival_message,
)
from psynet.utils import call_function_with_context, get_config, get_logger

logger = get_logger()

_PENDING_BARRIER_CHECKS_KEY = "psynet_pending_barrier_checks"
_RELEASED_HOLD_WAITER_IDS_KEY = "psynet_released_hold_waiter_ids"
_NESTED_BARRIER_QUEUE_SNAPSHOTS_KEY = "psynet_nested_barrier_queue_snapshots"


class _BarrierAuthorHookError(Exception):
    """Author ``on_release`` failed; last-arrival keeps the group waiting."""


def _queue_barrier_check(barrier_instance_id):
    """Queue one instance for checking after the arrival transaction commits."""
    db.session.info.setdefault(_PENDING_BARRIER_CHECKS_KEY, set()).add(
        barrier_instance_id
    )


def _take_pending_barrier_checks():
    """Take the barrier checks queued by the preceding successful transaction."""
    return sorted(db.session.info.pop(_PENDING_BARRIER_CHECKS_KEY, set()))


def _follow_pin_barrier_instances(instance_ids):
    """Park publish for queued visits before their arrival becomes visible."""
    for instance_id in instance_ids:
        _mark_last_arrival_follow_instance(instance_id)


def _follow_pin_pending_barrier_checks():
    """Follow-pin checks still sitting in this request's session.info."""
    _follow_pin_barrier_instances(
        db.session.info.get(_PENDING_BARRIER_CHECKS_KEY) or []
    )


def _queue_released_hold_waiters(participants):
    """Remember released waiters so they can be skipped after partner locks drop."""
    db.session.info.setdefault(_RELEASED_HOLD_WAITER_IDS_KEY, []).extend(
        participant.id for participant in participants
    )


def _take_released_hold_waiter_ids():
    """Take waiter ids queued by the barrier check that just ran."""
    ids = db.session.info.pop(_RELEASED_HOLD_WAITER_IDS_KEY, [])
    return sorted(set(ids))


def _rollback_preserving_barrier_queues():
    """Roll back without dropping queued post-commit barrier work.

    Skip-after-commit may ``NOWAIT``-miss a waiter whose own request already
    holds the row. PostgreSQL aborts that transaction, so the session must
    roll back before the next waiter. ``after_rollback`` would otherwise
    discard stacked checks queued by a waiter this loop already skipped.
    """
    pending = set(db.session.info.get(_PENDING_BARRIER_CHECKS_KEY, set()))
    released = list(db.session.info.get(_RELEASED_HOLD_WAITER_IDS_KEY, []))
    db.session.rollback()
    if pending:
        db.session.info[_PENDING_BARRIER_CHECKS_KEY] = pending
    if released:
        db.session.info[_RELEASED_HOLD_WAITER_IDS_KEY] = released


def _hold_instance_id_for_page(participant, page):
    """Return the unreleased hold instance for this page, if any."""
    if not getattr(page, "is_timeline_hold", False):
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
        with db.session.begin_nested():
            instance = BarrierInstance.query.get(instance_id)
            if instance is None:
                return False
            barrier = instance.get_barrier()
            if not isinstance(barrier, Barrier):
                return True
            waiting = _get_waiting_participants(
                instance.barrier_id,
                instance.id,
                for_update=False,
                nowait=False,
            )
            return bool(barrier.would_release(waiting))
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


@event.listens_for(db.session, "after_transaction_create")
def _snapshot_pending_barrier_queues_for_nested(session, transaction):
    """Remember queued checks so a SAVEPOINT rollback can restore them."""
    if not transaction.nested:
        return
    pending = set(session.info.get(_PENDING_BARRIER_CHECKS_KEY, set()))
    released = list(session.info.get(_RELEASED_HOLD_WAITER_IDS_KEY, []))
    session.info.setdefault(_NESTED_BARRIER_QUEUE_SNAPSHOTS_KEY, []).append(
        (pending, released)
    )


@event.listens_for(db.session, "after_rollback")
def _discard_pending_barrier_checks(session):
    """Restore pre-savepoint queues on nested rollback; drop them on root rollback.

    Detect the SAVEPOINT via the snapshot stack. ``in_nested_transaction()``
    may already be false when this handler runs. A later instance's waiter
    ``NOWAIT`` miss must not wipe stacked checks queued by an earlier skip
    in the same ``_run_pending_barrier_checks`` sweep.
    """
    stack = session.info.get(_NESTED_BARRIER_QUEUE_SNAPSHOTS_KEY) or []
    if stack:
        pending, released = stack[-1]
        if pending:
            session.info[_PENDING_BARRIER_CHECKS_KEY] = set(pending)
        else:
            session.info.pop(_PENDING_BARRIER_CHECKS_KEY, None)
        if released:
            session.info[_RELEASED_HOLD_WAITER_IDS_KEY] = list(released)
        else:
            session.info.pop(_RELEASED_HOLD_WAITER_IDS_KEY, None)
        return
    session.info.pop(_PENDING_BARRIER_CHECKS_KEY, None)
    session.info.pop(_RELEASED_HOLD_WAITER_IDS_KEY, None)


@event.listens_for(db.session, "after_transaction_end")
def _pop_nested_barrier_queue_snapshot(session, transaction):
    if not transaction.nested:
        return
    stack = session.info.get(_NESTED_BARRIER_QUEUE_SNAPSHOTS_KEY)
    if stack:
        stack.pop()


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
    rows; joining ``timeline_hold`` or collections would add outer joins to a
    ``FOR UPDATE`` statement (a PostgreSQL footgun) or a cartesian product.
    The follow-up ``IN`` queries do not take extra row locks.

    ``sync_group_links`` is populated separately; see
    ``_populate_sync_group_links``.
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
                selectinload(Participant.active_barriers),
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
    waiters = [link.participant for link in query.all()]
    _populate_sync_group_links(waiters)
    return waiters


def _populate_sync_group_links(participants):
    """Batch-load ``sync_group_links`` without a relationship loader option.

    ``selectinload(Participant.sync_group_links)`` on the waiter query makes
    later group walks lazy-load that collection once per member, which shows
    up as extra statements in arrival-notice lookups. An explicit ``IN``
    query plus ``set_committed_value`` keeps the check O(1) without that
    side effect.
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
    return session.info.setdefault("_psynet_has_active_sync_group", {})


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
        )

    @property
    def fail_on_timeout(self):
        return self.barrier.max_wait_action == "fail"

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
    construction (``waiting_logic``, ``_uses_timeline_hold``,
    ``waiting_logic_expected_repetitions``).

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
        to the participant while they are waiting at the barrier. If left at the
        default value of ``None``, the current page remains visible beneath a
        lightweight waiting indicator.

    waiting_logic_expected_repetitions
        Expected repetitions for explicit ``waiting_logic``. For a default
        hold, this is used only to derive the legacy ``expected_wait`` when no
        explicit estimate is supplied.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded then the participant will be failed and sent to the end of the experiment.

    fix_time_credit
        If set to ``True``, award fixed expected time credit. Otherwise default
        holds credit actual visible waiting time up to ``max_wait_time``.

    expected_wait
        Expected duration of a default timeline hold. If omitted, preserves the
        historical default estimate of 0.5 seconds multiplied by
        ``waiting_logic_expected_repetitions``.

    content
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. If omitted, participants see
        "Waiting for other participants…".
    """

    def __init__(
        self,
        id_: str,
        waiting_logic=None,
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        fix_time_credit=False,
        expected_wait=None,
        content=None,
    ):
        self.id = id_
        self.max_wait_time = max_wait_time
        self.fix_time_credit = fix_time_credit
        self.waiting_logic_expected_repetitions = waiting_logic_expected_repetitions
        self.content = content
        self._uses_timeline_hold = waiting_logic is None
        if waiting_logic is not None and expected_wait is not None:
            raise ValueError(
                "expected_wait only applies when waiting_logic is omitted."
            )
        if waiting_logic is not None and content is not None:
            raise ValueError("content only applies when waiting_logic is omitted.")
        self.expected_wait = (
            0.5 * waiting_logic_expected_repetitions
            if expected_wait is None
            else expected_wait
        )
        if self.expected_wait < 0:
            raise ValueError("expected_wait must be non-negative.")
        if waiting_logic is None:
            waiting_logic = _BarrierHoldPage(self)

        self.waiting_logic = waiting_logic
        self.max_wait_action = "fail"

    def __setattr__(self, name, value):
        if name.startswith("on_"):
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
                expected_repetitions=self.waiting_logic_expected_repetitions,
                max_loop_time=self.max_wait_time,
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
            elt.links["barrier"] = self

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

        link = ParticipantLinkBarrier(
            participant=participant,
            barrier_id=self.id,
            barrier_instance=barrier_instance,
            arrival_time=timenow(),
        )
        participant.active_barriers[self.id] = link
        if not self._uses_timeline_hold:
            self._queue_check_on_arrival(barrier_instance)
            self._notify_arrivals(participant)

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
        barrier_is_active = self.id in participant.active_barriers
        return not barrier_is_active

    def get_waiting_participants(self, participant=None, *, for_update: bool = False):
        """Return people currently waiting at this barrier visit.

        Pass ``participant`` to scope the list to that person's instance.
        Ungrouped barriers (groupers) fall back to the one active pool for
        this barrier ID. Grouped barriers require a participant; see
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

        Released hold waiters are queued and skipped after this check
        commits, so partner row locks do not span ``_advance_past_ready_holds``.

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
            if instance is not None:
                # Pin only after this request actually released waiters. Pinning
                # an unfilled visit (waiter GET / still-waiting skip) keeps the
                # 0.5 s poller from finishing the same barrier.
                _mark_last_arrival_render_instance(instance.id)
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
    """Skip each released hold waiter after partner row locks are dropped.

    Partners otherwise stay at this hold until their next request, so the
    last arriver would immediately sit on the next barrier (often with the
    same wait copy) until those clients catch up. The waiter's later
    hold-resume POST still carries the hold page's uuid; ``process_response``
    treats that as an in-place catch-up when it is still this waiter's
    hold uuid, rather than a sync failure.

    Each waiter is locked alone so a partner ``GET /timeline`` can take
    ``FOR UPDATE`` on itself. ``NOWAIT`` skips a waiter whose own request
    already holds the row.
    """
    from .experiment import get_experiment

    if not participant_ids:
        return
    experiment = get_experiment()
    for participant_id in participant_ids:
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
            raise
        if participant is None:
            _rollback_preserving_barrier_queues()
            continue
        try:
            page = experiment.timeline.get_current_elt(experiment, participant)
            if getattr(page, "is_timeline_hold", False):
                experiment._advance_past_ready_holds(participant, page)
            db.session.commit()
        except Exception:
            _rollback_preserving_barrier_queues()
            raise


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
    poller. On the default hold path that arriver then skips the wait indicator
    and released partners are skipped after the check commits. If a partner
    wait row is locked, the poller finishes the skip.
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
        to the participant while they are waiting at the barrier. If left at
        ``None``, the current page remains visible beneath a lightweight
        waiting indicator. Pass ``content`` to customize that indicator's
        message.

    waiting_logic_expected_repetitions
        Expected repetitions for explicit ``waiting_logic``. For a default
        hold, this is used only to derive the legacy ``expected_wait`` when no
        explicit estimate is supplied.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded, the participant is either failed or kicked (see ``max_wait_action``).

    max_wait_action
        When ``max_wait_time`` is exceeded: ``"fail"`` fails the participant and sends them to the end of the
        experiment; ``"kick"`` removes them from the group and lets them continue. Default is ``"fail"``.

    timeout_between_barriers_time
        The maximum amount of time in seconds that a participant is allowed to reach the barrier, measured from when
        the group collectively passed the previous barrier. If ``None`` (default), no between-barrier timeout is applied.
        Only applies from the second barrier onward (time since previous barrier pass).

    timeout_between_barriers_action
        When a participant exceeds ``timeout_between_barriers_time``: ``"kick"`` removes them from the group (so the
        rest can proceed without them), or ``"fail"`` fails the participant and sends them to the end of the experiment.
        Default is ``"fail"``.

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
        Expected duration of a default timeline hold. If omitted, preserves the
        historical default estimate.

    content
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. If omitted, participants see
        "Waiting for other participants…". Independent of a preceding
        :class:`~psynet.sync.Grouper`'s ``content`` and of trial-maker
        ``sync_group_wait_content``.

    notify_arrivals
        If ``True`` (default), group members who have not reached this barrier
        yet see a pill on the progress bar, and waiting participants in groups
        of three or more see remaining-not-ready copy on the hold overlay.
        Pairs keep the hold title only. Set ``False`` to disable both.
        Passing ``on_arrival_message`` implies ``True``.

    on_arrival_message
        Optional callable that returns copy for one recipient. It receives
        ``kind`` (``"hold"`` or ``"notice"``), ``waiting_count``,
        ``group_size``, and the usual context arguments (``recipient``,
        ``group``, ``barrier``, ``experiment``). Return ``None`` to hide that
        surface. Same serialization rules as ``on_release``. The default pair
        notice is "Your partner is ready."; pair holds omit a second line.
        Groups of three or more default to ``"{REMAINING} of {TOTAL} not ready yet"``
        on the hold and ``"{ARRIVED}/{TOTAL} of your group are ready."`` on the
        pill. Notice copy stays on one line (overflow ellipsizes) and sits
        on the progress bar, so keep ``kind="notice"`` return values to a
        short sentence. Hold overlay copy may use a second line.

    """

    @staticmethod
    def _kick_participant_after_max_wait(
        participant: Participant, group_type: str
    ) -> None:
        """Remove the participant from their sync group when max wait uses action ``'kick'``."""
        if group_type in participant.active_sync_groups:
            participant.active_sync_groups[group_type].remove_participant(participant)

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
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        max_wait_action: Literal["fail", "kick"] = "fail",
        on_release: Optional[Callable] = None,
        fix_time_credit=False,
        timeout_between_barriers_time: Optional[float] = None,
        timeout_between_barriers_action: Literal["kick", "fail"] = "fail",
        expected_wait=None,
        content=None,
        notify_arrivals: bool = True,
        on_arrival_message: Optional[Callable] = None,
    ):
        self._validate_max_wait_action(max_wait_action)
        super().__init__(
            id_=id_,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            fix_time_credit=fix_time_credit,
            expected_wait=expected_wait,
            content=content,
        )
        self.max_wait_action = max_wait_action
        self.group_type = group_type
        self.on_release = on_release
        self.on_arrival_message = on_arrival_message
        self.notify_arrivals = bool(notify_arrivals) or on_arrival_message is not None
        self.timeout_between_barriers_time = timeout_between_barriers_time
        if timeout_between_barriers_action not in ("kick", "fail"):
            raise ValueError(
                "timeout_between_barriers_action must be 'kick' or 'fail', "
                f"got {timeout_between_barriers_action!r}"
            )
        self.timeout_between_barriers_action = timeout_between_barriers_action

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
        group = participant.active_sync_groups.get(self.group_type)
        if group is None:
            return None
        waiting_count = sum(
            1
            for member in group.active_participants
            if self._participant_is_waiting(member)
        )
        return self._call_arrival_message(
            kind="hold",
            waiting_count=waiting_count,
            group_size=len(group.active_participants),
            recipient=participant,
            group=group,
        )

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
        waiting_count = sum(
            1
            for member in group.active_participants
            if self._participant_is_waiting(member)
        )
        group_size = len(group.active_participants)
        for member in group.active_participants:
            if member.failed:
                continue
            if self._participant_is_waiting(member):
                hold_html = None
                if self._uses_timeline_hold:
                    hold_html = self.waiting_logic.overlay_html(member)
                _queue_arrival_update(member.id, hold_message=hold_html)
                continue
            text = self._call_arrival_message(
                kind="notice",
                waiting_count=waiting_count,
                group_size=group_size,
                recipient=member,
                group=group,
            )
            if text:
                _queue_arrival_update(member.id, notice=str(text))

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

            if group.n_active_participants < group.min_group_size:
                # If join_existing_groups is False, then the group will never be able
                # to get to the minimum size, so we remove all participants from the group
                # and release participants who are waiting at this barrier. Optionally fail them
                # (when fail_participants_below_min_size is True).
                if not group.accepts_top_ups:
                    for participant in list(group.active_participants):
                        if group.fail_participants_below_min_size:
                            participant.fail("sync group below minimum size")
                        group.remove_participant(participant)
                        if participant.id in waiting_participant_ids:
                            participants_to_release.append(participant)
                    group.check_numbers()
                    if group.n_active_participants == 0:
                        group.close()
                continue

            all_participants_present = all(
                [
                    participant.id in waiting_participant_ids
                    for participant in group.active_participants
                ]
            )
            if all_participants_present:
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
        """Return whether this group visit would release, without mutating state."""
        waiting_ids = {participant.id for participant in waiting_participants}
        for group in self.get_waiting_groups(waiting_participants).values():
            if group.n_active_participants < group.min_group_size:
                if not group.accepts_top_ups:
                    return True
                continue
            if all(
                participant.id in waiting_ids
                for participant in group.active_participants
            ):
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
        """Kick or fail group members who are late reaching this barrier."""
        if (
            self.timeout_between_barriers_time is None
            or group.last_barrier_pass_time is None
        ):
            return

        elapsed_seconds = (timenow() - group.last_barrier_pass_time).total_seconds()
        if elapsed_seconds <= self.timeout_between_barriers_time:
            return

        waiting_participant_ids = {p.id for p in waiting_participants}
        missing = [
            p for p in group.active_participants if p.id not in waiting_participant_ids
        ]
        for participant in missing:
            if self.timeout_between_barriers_action == "kick":
                logger.info(
                    "GroupBarrier '%s': kicking participant %s from group %s (timeout between barriers)",
                    self.id,
                    participant.id,
                    group.id,
                )
                group.remove_participant(participant)
            else:
                logger.info(
                    "GroupBarrier '%s': failing participant %s (timeout between barriers)",
                    self.id,
                    participant.id,
                )
                participant.fail("timeout between barriers")


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
        to the participant while they are waiting at the barrier. If left at
        ``None``, the current page remains visible beneath a lightweight
        waiting indicator.

    waiting_logic_expected_repetitions
        Expected repetitions for explicit ``waiting_logic``. For a default
        hold, this is used only to derive the legacy ``expected_wait`` when no
        explicit estimate is supplied.

    max_wait_time
        The maximum amount of time in seconds that the participant will be allowed to wait at the barrier;
        if this time is exceeded and the participant is still not released, then the participant will be failed
        and sent to the end of the experiment.

    expected_wait
        Expected duration of a default timeline hold. If omitted, preserves the
        historical default estimate.

    content
        Message displayed by the default timeline hold overlay. Only used when
        ``waiting_logic`` is omitted. This Grouper's overlay is independent of
        trial-maker ``sync_group_wait_content``; pass ``content`` here and on
        later :class:`~psynet.sync.GroupBarrier` waits if they should match.

    fix_time_credit
        If ``True``, award fixed ``expected_wait`` credit instead of actual
        visible waiting time.

    fail_participants_below_min_size
        If ``True`` (default), participants in a group that is below minimum size and does not accept
        top-ups are failed and released when they hit a GroupBarrier. If ``False``, they are released
        without being failed. (Only applies to groups that have a minimum size, e.g. created by SimpleGrouper.)
    """

    def __init__(
        self,
        group_type: str,
        id_: Optional[str] = None,
        waiting_logic=None,
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        fail_participants_below_min_size: bool = True,
        expected_wait=None,
        fix_time_credit=False,
        content=None,
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
        This behavior can be further customized via the ``join_criterion`` argument.

    join_criterion
        A callable that takes ``group`` and ``participant`` as arguments, and returns ``True``
        if the participant should be allowed to join the group, and ``False`` otherwise.
        To be used in conjunction with ``join_existing_groups=True``.

    fail_participants_below_min_size
        If ``True`` (default), participants in a group below minimum size that does not accept top-ups
        are failed and released at GroupBarriers. If ``False``, they are released without being failed.

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

    def _join_existing_groups(self, participant: Participant):
        # The current logic is flawed, in that participants end up joining groups that are no longer active.
        # It's difficult to figure out a good general-purpose solution here that works well for all possible applications.
        # I think we should disable this behaviour for now, and wait until we experience some real-world use cases,
        # which can inform the future API.
        if not self.join_existing_groups:
            return

        query = SimpleSyncGroup.query.filter(
            SimpleSyncGroup.group_type == self.group_type
        )

        if self.max_group_size is not None:
            query = query.filter(
                SimpleSyncGroup.n_active_participants < self.max_group_size
            )

        # Preferentially join the smallest groups, and among those, the oldest
        query = query.order_by(
            SimpleSyncGroup.n_active_participants, SimpleSyncGroup.id
        )

        groups = query.all()

        # Only keep groups that satisfy the joining criterion (if provided)
        groups = [
            g
            for g in groups
            if self.join_criterion is None
            or self.join_criterion(group=g, participant=participant)
        ]

        if len(groups) > 0:
            group = groups[0]
            group.add_participant(participant)
            assert participant.active_sync_groups[self.group_type] == group
            group.check_numbers()
            group.check_leader()

    def ready_to_group(self, participants: List[Participant]) -> bool:
        return len(participants) >= self.batch_size

    def group(self, participants: List[Participant]) -> List["SyncGroup"]:
        n_groups = floor(len(participants) / self.initial_group_size)
        n_participants_to_group = n_groups * self.initial_group_size
        participants_to_group = participants[:n_participants_to_group]

        grouped_participants = self.randomly_partition_list(
            participants_to_group, group_size=self.initial_group_size
        )
        groups = []
        for _participants in grouped_participants:
            _group = SimpleSyncGroup(
                group_type=self.group_type,
                initial_group_size=self.initial_group_size,
                max_group_size=self.max_group_size,
                min_group_size=self.min_group_size,
                n_active_participants=len(_participants),
                accepts_top_ups=self.join_existing_groups,
                fail_participants_below_min_size=self.fail_participants_below_min_size,
            )
            groups.append(_group)

            for _participant in _participants:
                _group.add_participant(_participant)

            _group.leader = self.select_leader(_participants)

        return groups

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
        return _ReadOnlyParticipantList(
            link.participant
            for link in self.participant_links
            if getattr(link, "active", True)
        )

    def add_participant(self, participant: Participant):
        """Add a participant to the group (creates an active link)."""
        _forget_active_sync_group(participant)
        self.participant_links.append(
            ParticipantLinkSyncGroup(participant=participant, active=True)
        )

    @property
    def active_participants(self) -> List[Participant]:
        return [p for p in self.participants if not p.failed and p.status == "working"]

    leader = relationship(
        "psynet.participant.Participant",
        cascade="all",
    )

    def check_leader(self):
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
        self.active = False
        self.end_time = timenow()

    def check_numbers(self):
        self.n_active_participants = len(self.active_participants)

    def remove_participant(self, participant: Participant):
        _forget_active_sync_group(participant)
        for link in self.participant_links:
            if link.participant_id == participant.id:
                link.active = False
        self.check_numbers()
        if self.n_active_participants == 0 and not getattr(
            self, "accepts_top_ups", False
        ):
            self.close()
        else:
            self.check_leader()


class SimpleSyncGroup(SyncGroup):
    """
    A SyncGroup that is created by a SimpleGrouper.
    """

    initial_group_size = Column(Integer)
    max_group_size = Column(Integer)
    min_group_size = Column(Integer)
    accepts_top_ups = Column(Boolean)
    fail_participants_below_min_size = Column(Boolean, default=True)

    def remove_participant(self, participant: Participant):
        super().remove_participant(participant)
        self.dissolve_if_below_min_size()

    def dissolve_if_below_min_size(self):
        if (
            getattr(self, "_dissolving_below_min_size", False)
            or self.accepts_top_ups
            or self.n_active_participants >= self.min_group_size
        ):
            return

        self._dissolving_below_min_size = True
        try:
            remaining_participants = list(self.active_participants)
            for participant in remaining_participants:
                if self.fail_participants_below_min_size:
                    participant.fail("sync group below minimum size")
                else:
                    super().remove_participant(participant)

            self.check_numbers()
            if self.n_active_participants == 0:
                self.close()
        finally:
            self._dissolving_below_min_size = False


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

        scope = f"{barrier.id}:group:{group_id}" if group_id is not None else barrier.id
        _claim_barrier_instance(scope, wait=True)

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
        methods are safe here.
        """
        return barrier_from_spec_json(self.spec)

    def _validate_behavior(self, behavior_hash):
        """Reject incompatible reuse of one active waiting pool."""
        if self.behavior_hash != behavior_hash:
            raise ValueError(
                f"Barrier ID '{self.barrier_id}' was reused with different behavior "
                "while its waiting pool is active. Use a different barrier ID."
            )

    @staticmethod
    def _group_id(barrier, participant):
        if not isinstance(barrier, GroupBarrier):
            return None
        group = participant.active_sync_groups.get(barrier.group_type)
        if group is None:
            raise RuntimeError(
                f"Participant {participant.id} has no active sync group "
                f"of type '{barrier.group_type}' for barrier '{barrier.id}'."
            )
        return group.id


@register_table
class ParticipantLinkSyncGroup(SQLBase, SQLMixin):
    __tablename__ = "participant_link_sync_group"

    arrival_time = Column(DateTime)
    active = Column(Boolean, default=True)

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
                instance_id=self.barrier_instance_id,
            )


def _waiting_barrier_instance_ids():
    """Snapshot barrier visits that still have working waiters.

    Include inactive rows. A last-arrival snapshot can mark the visit
    finished while a concurrent arriver's link committed after that SELECT.
    """
    with Session(bind=db.engine) as session:
        return [
            instance_id
            for (instance_id,) in (
                session.query(BarrierInstance.id)
                .filter(
                    session.query(ParticipantLinkBarrier.id)
                    .join(Participant)
                    .filter(
                        ParticipantLinkBarrier.barrier_instance_id
                        == BarrierInstance.id,
                        ~ParticipantLinkBarrier.released,
                        ~Participant.failed,
                        Participant.status == "working",
                    )
                    .exists(),
                )
                .order_by(BarrierInstance.id)
            )
        ]


def arrival_notice_payload(participant_id):
    """Return the partner-ready notice snapshot for one participant.

    Redis arrival wakes are fire-and-forget. The browser fetches this when
    the arrival websocket opens so a partner who arrived during connect is
    still shown.
    """
    from psynet.participant import Participant

    if participant_id is None or participant_id == "":
        return {"notice": None}
    participant = Participant.query.get(participant_id)
    if participant is None:
        return {"notice": None}
    return {"notice": pending_arrival_notice_for(participant)}


def pending_arrival_notice_for(participant):
    """Return a partner-ready notice if this participant is behind a waiter.

    Reconstructs registry barriers for this call only. Overlay HTML stays on
    the live timeline barrier.
    """
    if participant is None or getattr(participant, "failed", False):
        return None
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
                barrier = reconstructed.get(link.barrier_instance_id)
                if barrier is None:
                    barrier = link.get_barrier()
                    reconstructed[link.barrier_instance_id] = barrier
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
        advisory claim, so waiters may still be locked.
    """
    if instance is None:
        return True
    if not instance.active:
        if not isinstance(
            instance, BarrierInstance
        ) or not _barrier_instance_has_waiters(instance):
            return True
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


def _check_and_skip_held_instance(instance_id):
    """Evaluate one visit whose extra-connection claim is already held.

    Sets the ORM ``lock_timeout`` so check/commit cannot wait forever while
    the extra connection holds the visit key. Nested waiter ``NOWAIT`` misses
    return ``False`` so last-arrival can retry. Author ``on_release`` and spec
    errors also return ``False`` so the group stays waiting. Other
    non-transient check errors and skip errors propagate so
    ``GET /timeline`` does not first-paint a hold. Expire the identity map
    first so a release peek that ran before the claim wait cannot hide
    visit or group mutations from the worker that held the claim.
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
            return False
        logger.exception(
            "Barrier '%s' instance %s failed during a last-arrival check.",
            instance.barrier_id if instance is not None else None,
            instance_id,
        )
        if isinstance(err, (BarrierSpecError, _BarrierAuthorHookError)):
            return False
        raise
    released_ids = _take_released_hold_waiter_ids()
    db.session.commit()
    _advance_released_hold_waiters_after_commit(released_ids)
    return ok


def _run_pending_barrier_checks(instance_ids, *, wait=True):
    """Run post-commit checks, optionally waiting for each instance claim.

    Last-arrival must not first-paint a hold because the 0.5 s poller already
    holds this visit. Waiting for the extra-connection claim (not for waiter
    rows) serializes with that poller through skip-after-commit. Waiter rows
    stay ``FOR UPDATE NOWAIT``. Each check commits before skip so partner
    row locks do not span ``_advance_past_ready_holds``.

    A blocking claim wait that hits ``lock_timeout`` raises so ``GET
    /timeline`` can return HTTP 503 rather than first-painting the live hold.
    A waiter-row ``NOWAIT`` miss still returns ``False`` so the caller can
    retry immediately. Follow-pin every queued visit before the try-lock so
    poller publish cannot fire in the gap after a missed claim. That pin parks
    publish only; unfilled waiter GETs still leave poller processing free.

    Unfilled waiter GET recovery must pass ``wait=False``. Those requests try
    the claim so a dropped last-arrival check can still finish, but they must
    not occupy a worker in ``lock_timeout`` while last-arrival already holds
    the visit. Try-miss first-paints the live hold and leaves the skip to
    last-arrival or the poller.
    """
    for instance_id in instance_ids:
        _mark_last_arrival_follow_instance(instance_id)
    all_claimed = True
    for instance_id in instance_ids:
        try:
            _mark_last_arrival_follow_instance(instance_id)
            ran = False
            with _hold_barrier_instance_claim(instance_id, wait=False) as claimed:
                if claimed:
                    ran = True
                    if not _check_and_skip_held_instance(instance_id):
                        all_claimed = False
            if ran:
                continue
            if not wait:
                all_claimed = False
                continue
            with _hold_barrier_instance_claim(instance_id, wait=True):
                if not _check_and_skip_held_instance(instance_id):
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
    """Try one barrier visit and report whether waiter contention deferred it."""
    from .timeline_hold import _last_arrival_render_in_progress

    if _last_arrival_render_in_progress(instance_id):
        logger.debug(
            "Barrier instance %s skipped because last-arrival is still rendering.",
            instance_id,
        )
        return False
    barrier_id = None
    try:
        with _hold_barrier_instance_claim(instance_id, wait=False) as claimed:
            if not claimed:
                return False
            if _last_arrival_render_in_progress(instance_id):
                logger.debug(
                    "Barrier instance %s skipped because last-arrival started rendering.",
                    instance_id,
                )
                return False
            _set_transaction_lock_timeout(
                get_config().get("timeline_lock_timeout_seconds")
            )
            instance = BarrierInstance.query.get(instance_id)
            if instance is None:
                return False
            barrier_id = instance.barrier_id
            with db.session.begin_nested():
                _check_claimed_barrier_instance(instance, already_claimed=True)
            released_ids = _take_released_hold_waiter_ids()
            db.session.commit()
            _advance_released_hold_waiters_after_commit(released_ids)
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


def check_barriers():
    """Process waiting barrier visits, including stacked holds created here.

    Last-arrival GET waits for this poller's extra-connection instance claim,
    then still uses waiter ``NOWAIT``. The poller keeps that claim until
    skip-after-commit finishes, so last-arrival cannot first-paint a hold in
    the gap after partner row locks drop. If a partner row stays busy, this
    poller finishes the stacked skip: walk newly created holds in this sweep
    and keep wake publishes unpublished until that walk returns, so waiters do
    not hold-resume onto the next barrier one at a time. Skip visits a
    last-arrival request already released and is still rendering; that request
    render-pins those in Redis so this process cannot process or publish
    during HTML/JSON render. Publish also parks wakes whose visit has a
    render or follow pin, including a GET that is still waiting for this
    claim. Unfilled waiter GETs never take the render pin, so this poller
    can still finish those visits. Each visit
    still commits before the next check so a locked waiter cannot poison
    sibling checks.
    """
    seen = set()
    with _defer_timeline_hold_wakes():
        while True:
            waiting = [
                instance_id
                for instance_id in _waiting_barrier_instance_ids()
                if instance_id not in seen
            ]
            if not waiting:
                break
            deferred_ids = []
            for instance_id in waiting:
                seen.add(instance_id)
                if _process_barrier_instance(instance_id):
                    deferred_ids.append(instance_id)
            for instance_id in deferred_ids:
                _process_barrier_instance(instance_id, retry=True)


def check_sync_groups():
    """Recount active membership, skipping groups locked by another request.

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

"""Durable in-place waiting for server-side timeline conditions.

Timeline holds preserve the currently rendered participant page while the
server waits for a condition to clear. This module owns the durable accounting
record and the internal page protocol shared by barriers and ``wait_while``.
Hold-release websocket wakes publish after the next database commit. Last-arrival
finalize and the barrier poller can defer those publishes until stacked checks
finish so waiting partners are not woken while later checks still lock their
rows. After a request actually releases waiters, it takes a Redis render pin
until HTML/JSON render returns, so the 0.5 s poller (a different process) does
not process or publish those visits while that request is still building the next
page. A GET that is about to claim or follow a visit takes a follow pin first
(publish park only) so poller publish cannot fire in the gap after the claim
drops. Park and unpin use atomic Redis scripts so a wake cannot land on the
parked list after the last owner token is gone. Each request stores a
distinct owner token in the pin set so a stale exit after TTL expiry
cannot drop a later owner's pin. Unfilled waiter GETs never take the
render pin, so the poller can still finish those visits. The poller uses a
fresh session per visit, so wake deferral is stored in a context variable
rather than ``session.info``.
``GET /timeline`` and ``POST /response`` skip ready holds under a participant
row lock, but they do not share that lock protocol. The page lifecycle
developer docs describe the resume protocol.
"""

import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from dallinger import db
from dallinger.models import timenow
from markupsafe import Markup, escape
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    event,
)
from sqlalchemy.orm import relationship

from psynet.data import SQLBase, SQLMixin, register_table
from psynet.timeline import Page, get_template
from psynet.utils import call_function_with_context, get_logger, get_translator

_TIMELINE_HOLD_CHANNEL = "psynet_timeline_hold"


def _timeline_hold_channel(participant_id):
    """Return the Redis/Websocket channel for one participant's holds."""
    return f"{_TIMELINE_HOLD_CHANNEL}:{participant_id}"


_PENDING_WAKE_KEY = "psynet_timeline_hold_wakes"
_NESTED_WAKE_SNAPSHOTS_KEY = "psynet_nested_timeline_hold_wake_keys"
_wake_defer_depth = ContextVar("psynet_timeline_hold_wake_defer_depth", default=0)
_deferred_wake_stash = ContextVar("psynet_timeline_hold_deferred_wakes", default=None)
_LAST_ARRIVAL_RENDER_PREFIX = "psynet:last-arrival-render:"
_LAST_ARRIVAL_FOLLOW_PREFIX = "psynet:last-arrival-follow:"
_LAST_ARRIVAL_PARKED_WAKE_PREFIX = "psynet:last-arrival-parked-wakes:"
_LAST_ARRIVAL_RENDER_TTL_SECONDS = 15
_last_arrival_render_active = ContextVar(
    "psynet_last_arrival_render_active", default=False
)
_last_arrival_render_ids = ContextVar(
    "psynet_last_arrival_render_ids", default=frozenset()
)
_last_arrival_follow_ids = ContextVar(
    "psynet_last_arrival_follow_ids", default=frozenset()
)
_last_arrival_pin_owner = ContextVar("psynet_last_arrival_pin_owner", default="")
logger = get_logger()

# Park and unpin must be atomic: a publisher that sees a pin and then RPUSH
# after the last owner leaves would otherwise leave a wake that nobody drains.
# Pins are sets of per-request owner tokens, not integer refcounts, so a stale
# owner whose key expired cannot remove a later generation's token.
_PARK_WAKE_IF_PINNED_LUA = """
if redis.call('exists', KEYS[1]) == 1 or redis.call('exists', KEYS[2]) == 1 then
  redis.call('rpush', KEYS[3], ARGV[1])
  redis.call('expire', KEYS[3], tonumber(ARGV[2]))
  return 1
end
return 0
"""
_UNPIN_AND_DRAIN_LUA = """
if redis.call('exists', KEYS[1]) == 1 then
  redis.call('srem', KEYS[1], ARGV[1])
  if redis.call('scard', KEYS[1]) == 0 then
    redis.call('del', KEYS[1])
  end
end
if redis.call('exists', KEYS[2]) == 0 and redis.call('exists', KEYS[3]) == 0 then
  local wakes = redis.call('lrange', KEYS[4], 0, -1)
  redis.call('del', KEYS[4])
  return wakes
end
return {}
"""
# SADD without EXPIRE can leave a pin that outlives this request.
_PIN_AND_EXPIRE_LUA = """
if ARGV[2] == '1' then
  redis.call('sadd', KEYS[1], ARGV[3])
end
if redis.call('exists', KEYS[1]) == 1 then
  redis.call('expire', KEYS[1], tonumber(ARGV[1]))
  return 1
end
return 0
"""


def _last_arrival_render_key(instance_id):
    """Return the Redis key that marks a visit still owned by last-arrival render."""
    return f"{_LAST_ARRIVAL_RENDER_PREFIX}{instance_id}"


def _last_arrival_follow_key(instance_id):
    """Return the Redis key that parks publish while a GET follows this visit."""
    return f"{_LAST_ARRIVAL_FOLLOW_PREFIX}{instance_id}"


def _parked_hold_wake_key(instance_id):
    """Return the Redis list that holds wakes until last-arrival pins clear."""
    return f"{_LAST_ARRIVAL_PARKED_WAKE_PREFIX}{instance_id}"


@contextmanager
def _last_arrival_render_gate():
    """Keep the barrier poller off visits this request released and is rendering.

    Inner last-arrival commits release waiter rows before HTML/JSON render.
    The poller is a different process, so ``_defer_timeline_hold_wakes``
    cannot hide those rows from it. Redis records visits this request
    released (process skip + publish park) and visits it is about to claim
    (publish park only). Unfilled waiter GETs do not take the render pin, so
    the poller can still finish those barriers. Nested last-arrival requests
    add distinct owner tokens to the same set so an overlapping GET cannot
    clear the mark while the other is still rendering. A stale owner whose
    key expired cannot remove a later generation.
    """
    active_token = _last_arrival_render_active.set(True)
    ids_token = _last_arrival_render_ids.set(frozenset())
    follow_token = _last_arrival_follow_ids.set(frozenset())
    owner_token = _last_arrival_pin_owner.set(uuid.uuid4().hex)
    try:
        yield
    finally:
        _clear_last_arrival_render_marks()
        _last_arrival_pin_owner.reset(owner_token)
        _last_arrival_follow_ids.reset(follow_token)
        _last_arrival_render_ids.reset(ids_token)
        _last_arrival_render_active.reset(active_token)


def _incr_last_arrival_pin(instance_id, *, ids_var, key_for):
    """Add this request's owner token to one last-arrival Redis pin."""
    owner = _last_arrival_pin_owner.get()
    if instance_id is None or not _last_arrival_render_active.get() or not owner:
        return
    owned = ids_var.get()
    key = key_for(instance_id)
    incr = "1" if instance_id not in owned else "0"
    try:
        ok = db.redis_conn.eval(
            _PIN_AND_EXPIRE_LUA,
            1,
            key,
            _LAST_ARRIVAL_RENDER_TTL_SECONDS,
            incr,
            owner,
        )
    except Exception:
        logger.warning(
            "Failed to mark last-arrival pin for barrier instance %s.",
            instance_id,
            exc_info=True,
        )
        return
    if incr == "1" and ok:
        ids_var.set(owned | {instance_id})


def _mark_last_arrival_render_instance(instance_id):
    """Pin a visit this request released until last-arrival render finishes."""
    _incr_last_arrival_pin(
        instance_id,
        ids_var=_last_arrival_render_ids,
        key_for=_last_arrival_render_key,
    )


def _mark_last_arrival_follow_instance(instance_id):
    """Park publish for a visit this request is about to claim or follow.

    Does not skip poller processing. Unfilled waiter GETs may take this pin
    under claim contention; the 0.5 s poller can still finish the barrier.
    """
    _incr_last_arrival_pin(
        instance_id,
        ids_var=_last_arrival_follow_ids,
        key_for=_last_arrival_follow_key,
    )


def _last_arrival_render_in_progress(instance_id):
    """Return whether a last-arrival request is still rendering this visit."""
    if instance_id is None:
        return False
    try:
        return bool(db.redis_conn.exists(_last_arrival_render_key(instance_id)))
    except Exception:
        logger.warning(
            "Failed to read last-arrival render mark for barrier instance %s.",
            instance_id,
            exc_info=True,
        )
        return False


def _last_arrival_follow_in_progress(instance_id):
    """Return whether a GET is still following this visit for publish parking."""
    if instance_id is None:
        return False
    try:
        return bool(db.redis_conn.exists(_last_arrival_follow_key(instance_id)))
    except Exception:
        logger.warning(
            "Failed to read last-arrival follow mark for barrier instance %s.",
            instance_id,
            exc_info=True,
        )
        return False


def _any_last_arrival_pin_in_progress(instance_ids):
    """Return whether a follow or render pin currently owns any of these visits."""
    instance_ids = tuple(instance_ids)
    keys = []
    for instance_id in instance_ids:
        if instance_id is None:
            continue
        keys.append(_last_arrival_follow_key(instance_id))
        keys.append(_last_arrival_render_key(instance_id))
    if not keys:
        return False
    try:
        return bool(db.redis_conn.exists(*keys))
    except Exception:
        logger.warning(
            "Failed to read last-arrival pins for barrier instances %s.",
            instance_ids,
            exc_info=True,
        )
        return False


def _clear_last_arrival_render_marks():
    """Drop this request's last-arrival pins and publish atomically drained wakes."""
    parked = []
    for instance_id in _last_arrival_render_ids.get():
        parked.extend(_unpin_and_drain_hold_wakes(instance_id, kind="render"))
    for instance_id in _last_arrival_follow_ids.get():
        parked.extend(_unpin_and_drain_hold_wakes(instance_id, kind="follow"))
    _publish_wakes(parked)


def _park_wake_if_pinned(instance_id, wake):
    """Atomically park ``wake`` when a render or follow pin still exists.

    Returns
    -------
    bool
        ``True`` if the wake was parked. ``False`` if the caller should publish.
    """
    if instance_id is None:
        return False
    try:
        parked = db.redis_conn.eval(
            _PARK_WAKE_IF_PINNED_LUA,
            3,
            _last_arrival_render_key(instance_id),
            _last_arrival_follow_key(instance_id),
            _parked_hold_wake_key(instance_id),
            json.dumps(wake),
            _LAST_ARRIVAL_RENDER_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "Failed to park a hold wake for barrier instance %s.",
            instance_id,
            exc_info=True,
        )
        return False
    return bool(parked)


def _unpin_and_drain_hold_wakes(instance_id, *, kind):
    """Remove this request's owner token and drain parked wakes if no pin remains."""
    owner = _last_arrival_pin_owner.get()
    if not owner:
        return []
    this_key = (
        _last_arrival_render_key(instance_id)
        if kind == "render"
        else _last_arrival_follow_key(instance_id)
    )
    try:
        raw = db.redis_conn.eval(
            _UNPIN_AND_DRAIN_LUA,
            4,
            this_key,
            _last_arrival_render_key(instance_id),
            _last_arrival_follow_key(instance_id),
            _parked_hold_wake_key(instance_id),
            owner,
        )
    except Exception:
        logger.warning(
            "Failed to unpin last-arrival marks for barrier instance %s.",
            instance_id,
            exc_info=True,
        )
        return []
    wakes = []
    for item in raw or []:
        try:
            wakes.append(json.loads(item))
        except Exception:
            logger.warning(
                "Failed to decode a parked hold wake for barrier instance %s.",
                instance_id,
                exc_info=True,
            )
    return wakes


def _enqueue_timeline_hold_wake(
    participant_id, *, page_uuid=None, reason=None, hold=None, instance_id=None
):
    """Queue a targeted hold wake for publication after the next commit.

    Pass ``hold`` when the caller already has the unresumed record so this
    path does not look it up again. ``instance_id`` lets publish park the wake
    while last-arrival is still rendering that visit.
    """
    if hold is not None:
        if hold.resumed_at is not None:
            return
        page_uuid = hold.page_uuid if page_uuid is None else page_uuid
        active_hold = hold
    else:
        if page_uuid is None:
            from psynet.participant import Participant

            page_uuid = (
                Participant.query.with_entities(Participant.page_uuid)
                .filter_by(id=participant_id)
                .scalar()
            )
        if page_uuid is None:
            return
        active_hold = TimelineHoldRecord.query.filter_by(
            participant_id=participant_id,
            page_uuid=page_uuid,
            resumed_at=None,
        ).first()
        if active_hold is None:
            return
    if page_uuid is None:
        return
    wake = {
        "wake_token": active_hold.wake_token,
        "reason": reason,
        "participant_id": participant_id,
    }
    if instance_id is not None:
        wake["instance_id"] = instance_id
    db.session.info.setdefault(_PENDING_WAKE_KEY, {})[active_hold.wake_token] = wake


def _queue_timeline_hold_wake(
    participant_id, *, page_uuid=None, reason=None, hold=None, instance_id=None
):
    """Queue a wake without allowing notification failure to break core work."""
    try:
        _enqueue_timeline_hold_wake(
            participant_id,
            page_uuid=page_uuid,
            reason=reason,
            hold=hold,
            instance_id=instance_id,
        )
    except Exception:
        logger.warning(
            "Failed to queue a timeline hold wake for participant %s.",
            participant_id,
            exc_info=True,
        )


def _queue_arrival_update(participant_id, *, hold_message=None, notice=None):
    """Queue an arrival-progress or partner-ready update after the next commit."""
    try:
        db.session.info.setdefault(_PENDING_WAKE_KEY, {})[
            f"arrival:{participant_id}"
        ] = {
            "participant_id": participant_id,
            "reason": "arrival_update",
            "hold_message": hold_message,
            "notice": notice,
        }
    except Exception:
        logger.warning(
            "Failed to queue an arrival update for participant %s.",
            participant_id,
            exc_info=True,
        )


def default_group_barrier_arrival_message(
    *, kind, waiting_count, group_size, **_kwargs
):
    """Return default GroupBarrier arrival copy for one recipient.

    Pair holds keep the title only. Larger groups report how many members are
    not ready yet. Notices tell people still on an earlier page that partners
    are already waiting.
    """
    _p = get_translator(context=True)
    remaining = max(group_size - waiting_count, 0)
    if kind == "hold":
        if group_size <= 2 or remaining == 0:
            return None
        return _p("timeline_hold", "{REMAINING} of {TOTAL} not ready yet").format(
            REMAINING=remaining,
            TOTAL=group_size,
        )
    if group_size == 2:
        return _p("timeline_hold", "Your partner is ready.")
    return _p("timeline_hold", "{ARRIVED}/{TOTAL} of your group are ready.").format(
        ARRIVED=waiting_count,
        TOTAL=group_size,
    )


def _html_overlay_line(text):
    """Escape overlay text unless the author passed trusted ``Markup``."""
    if text is None:
        return ""
    if isinstance(text, Markup):
        return str(text)
    return str(escape(text))


def compose_hold_overlay_html(title_html, progress_text=None):
    """Join a hold title with an optional progress line."""
    title = f'<span class="psynet-timeline-hold-title">{title_html}</span>'
    if not progress_text:
        return title
    return (
        f"{title}"
        f'<span class="psynet-timeline-hold-progress">'
        f"{_html_overlay_line(progress_text)}</span>"
    )


def _copy_pending_wakes(wakes):
    """Copy queued wakes so later publish can pop ``participant_id`` safely."""
    return {key: dict(wake) for key, wake in wakes.items()}


@contextmanager
def _defer_timeline_hold_wakes():
    """Hold Redis wake publishes across inner commits, then flush on exit.

    Stacked last-arrival finalize commits after each barrier check. Publishing
    on those commits would wake waiting partners while later checks still lock
    their rows. ``GET /timeline`` and ``POST /response`` nest this context
    through page render so waiters also stay unpublished until the last arriver
    has a response body. The barrier poller uses the same context around a
    sweep: each visit commits in its own session, so the stash lives in a
    context variable that survives ``session.remove()``. SAVEPOINT releases are
    not durable: nested ``after_commit`` does not publish or stash. Nested
    rollback restores pending wakes to the keys that existed when that
    savepoint began. Root rollback still discards uncommitted pending wakes;
    already committed wakes stay deferred and flush here even if a later
    check fails.
    """
    depth = _wake_defer_depth.get()
    depth_token = _wake_defer_depth.set(depth + 1)
    stash_token = None
    if depth == 0:
        stash_token = _deferred_wake_stash.set({})
    try:
        yield
    finally:
        _wake_defer_depth.reset(depth_token)
        if depth == 0:
            deferred = _deferred_wake_stash.get() or {}
            if stash_token is not None:
                _deferred_wake_stash.reset(stash_token)
            _publish_wakes(list(deferred.values()))


def _stash_committed_wakes(pending):
    """Move committed wakes into the deferred stash instead of publishing."""
    if not pending:
        return
    deferred = _deferred_wake_stash.get()
    if deferred is None:
        _publish_wakes(list(pending.values()))
        return
    deferred.update(_copy_pending_wakes(pending))


def _publish_wakes(wakes):
    """Publish copied wake payloads on their participant Redis channels.

    Wakes whose visit still has a last-arrival render or follow pin are
    parked atomically in Redis instead of published. The gate drains that
    list when both pins are gone.
    """
    if not wakes:
        return
    remaining = []
    for wake in wakes:
        payload = dict(wake)
        instance_id = payload.get("instance_id")
        if instance_id is not None and _park_wake_if_pinned(instance_id, payload):
            continue
        remaining.append(payload)
    if not remaining:
        return
    try:
        from collections import defaultdict

        by_channel = defaultdict(list)
        for wake in remaining:
            payload = dict(wake)
            participant_id = payload.pop("participant_id", None)
            payload.pop("instance_id", None)
            channel = (
                _timeline_hold_channel(participant_id)
                if participant_id is not None
                else _TIMELINE_HOLD_CHANNEL
            )
            by_channel[channel].append(payload)
        for channel, targets in by_channel.items():
            db.redis_conn.publish(
                channel,
                json.dumps({"type": "timeline_hold_wake", "targets": targets}),
            )
    except Exception:
        logger.warning("Failed to publish timeline hold wake.", exc_info=True)


@event.listens_for(db.session, "after_transaction_create")
def _snapshot_pending_wakes_for_nested(session, transaction):
    """Remember pending wake keys so a SAVEPOINT rollback can restore them."""
    if not transaction.nested:
        return
    pending = session.info.get(_PENDING_WAKE_KEY) or {}
    session.info.setdefault(_NESTED_WAKE_SNAPSHOTS_KEY, []).append(set(pending))


@event.listens_for(db.session, "after_commit")
def _publish_timeline_hold_wakes(session):
    if session.in_nested_transaction():
        return
    pending = session.info.pop(_PENDING_WAKE_KEY, None) or {}
    if _wake_defer_depth.get():
        _stash_committed_wakes(pending)
        return
    _publish_wakes(list(pending.values()))


@event.listens_for(db.session, "after_rollback")
def _discard_timeline_hold_wakes(session):
    """Restore pre-savepoint wakes on nested rollback; drop pending on root rollback.

    Detect the SAVEPOINT via the snapshot stack. ``in_nested_transaction()``
    may already be false when this handler runs.
    """
    stack = session.info.get(_NESTED_WAKE_SNAPSHOTS_KEY) or []
    if stack:
        keys_before = stack[-1]
        pending = session.info.get(_PENDING_WAKE_KEY) or {}
        session.info[_PENDING_WAKE_KEY] = {
            key: wake for key, wake in pending.items() if key in keys_before
        }
        return
    session.info.pop(_PENDING_WAKE_KEY, None)


@event.listens_for(db.session, "after_transaction_end")
def _pop_nested_wake_snapshot(session, transaction):
    if not transaction.nested:
        return
    stack = session.info.get(_NESTED_WAKE_SNAPSHOTS_KEY)
    if stack:
        stack.pop()


@register_table
class TimelineHoldRecord(SQLBase, SQLMixin):
    """Store timing, compensation, and lifecycle data for one timeline hold."""

    __tablename__ = "timeline_hold"

    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    participant = relationship(
        "psynet.participant.Participant", backref="timeline_holds"
    )
    page_uuid = Column(String, unique=True, index=True)
    wake_token = Column(
        String, unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    hold_id = Column(String, index=True)
    started_at = Column(DateTime)
    deadline_at = Column(DateTime)
    released_at = Column(DateTime)
    resumed_at = Column(DateTime)
    expected_wait = Column(Float, default=0.0)
    max_wait_time = Column(Float)
    fix_time_credit = Column(Boolean, default=False)
    actual_wait_seconds = Column(Float, default=0.0)
    credited_wait_seconds = Column(Float, default=0.0)

    def _elapsed_at(self, timestamp):
        return max(0.0, (timestamp - self.started_at).total_seconds())

    def account_until(self, participant, timestamp):
        """Account newly elapsed visible waiting time through ``timestamp``."""
        if self.resumed_at is not None and timestamp > self.resumed_at:
            timestamp = self.resumed_at
        elapsed = self._elapsed_at(timestamp)
        previous_actual = self.actual_wait_seconds or 0.0
        if elapsed <= previous_actual:
            return

        participant.total_wait_page_time = (participant.total_wait_page_time or 0.0) + (
            elapsed - previous_actual
        )
        self.actual_wait_seconds = elapsed

        if not self.fix_time_credit:
            target_credit = elapsed
            if self.max_wait_time is not None:
                target_credit = min(target_credit, self.max_wait_time)
            previous_credit = self.credited_wait_seconds or 0.0
            if target_credit > previous_credit:
                participant.inc_time_credit(target_credit - previous_credit)
                self.credited_wait_seconds = target_credit

    def mark_released(self, participant, timestamp=None):
        """Record a durable release and account waiting through that point."""
        if timestamp is None:
            timestamp = timenow()
        if self.released_at is None:
            self.released_at = timestamp
        self.account_until(participant, timestamp)

    def settle(self, participant, timestamp=None):
        """Finalize this hold exactly once when the participant resumes."""
        if self.resumed_at is not None:
            return
        if timestamp is None:
            timestamp = timenow()
        if self.released_at is None:
            self.released_at = timestamp
        self.account_until(participant, timestamp)
        self.resumed_at = timestamp
        if self.fix_time_credit:
            previous_credit = self.credited_wait_seconds or 0.0
            target_credit = self.expected_wait or 0.0
            if target_credit > previous_credit:
                participant.inc_time_credit(target_credit - previous_credit)
            self.credited_wait_seconds = target_credit

    @classmethod
    def for_stale_hold_resume(cls, participant, submitted_page_uuid):
        """Return the submitted hold when it is still a catch-up from a wait page.

        One indexed lookup. Last-arrival can already have advanced this waiter
        onto a later hold or off the stack; the client's POST still sends the
        old uuid. A matching record is catch-up for both ordinary submits and
        hold-resume overlays.
        """
        return cls.query.filter_by(
            participant_id=participant.id,
            page_uuid=submitted_page_uuid,
        ).one_or_none()

    @property
    def deadline(self):
        """Return the authoritative timeout deadline, if configured."""
        return self.deadline_at


class _TimelineHoldPage(Page):
    """Internal page checkpoint that preserves the preceding browser page."""

    is_timeline_hold = True

    def __init__(
        self,
        *,
        hold_id,
        expected_wait,
        max_wait_time,
        fix_time_credit,
        check_interval,
        content=None,
        message_kind=None,
        fail_on_timeout=True,
        on_timeout=None,
    ):
        self.hold_id = hold_id
        self.expected_wait = expected_wait
        self.max_wait_time = max_wait_time
        self.fix_time_credit = fix_time_credit
        self.check_interval = check_interval
        self.content = content
        self.message_kind = message_kind
        self._fail_on_timeout = fail_on_timeout
        self.on_timeout = on_timeout
        super().__init__(
            label="wait",
            time_estimate=expected_wait,
            save_answer=False,
            template_str=get_template("timeline-hold-page.html"),
            template_arg={"content": content},
            framework_owned_template=True,
        )

    def consume(self, experiment, participant):
        super().consume(experiment, participant)
        now = timenow()
        deadline_at = (
            None
            if self.max_wait_time is None
            else now + timedelta(seconds=self.max_wait_time)
        )
        record = TimelineHoldRecord(
            participant=participant,
            page_uuid=participant.page_uuid,
            wake_token=str(uuid.uuid4()),
            hold_id=self.hold_id,
            started_at=now,
            deadline_at=deadline_at,
            expected_wait=self.expected_wait,
            max_wait_time=self.max_wait_time,
            fix_time_credit=self.fix_time_credit,
            actual_wait_seconds=0.0,
            credited_wait_seconds=0.0,
        )
        db.session.add(record)
        participant._timeline_hold_record = record
        self.on_hold_record_created(participant, record)

    def on_hold_record_created(self, participant, record):
        """Run subclass-specific linking after creating the hold record."""

    def get_hold_record(self, participant):
        """Return the record belonging to the participant's current hold page.

        Returns ``None`` when the cursor has already left this hold, so a
        stale GET ``/timeline`` page object cannot crash on ``.one()``.
        """
        cached = getattr(participant, "_timeline_hold_record", None)
        if cached is not None and cached.page_uuid == participant.page_uuid:
            return cached
        record = TimelineHoldRecord.query.filter_by(
            participant_id=participant.id,
            page_uuid=participant.page_uuid,
        ).one_or_none()
        if record is not None:
            participant._timeline_hold_record = record
        return record

    def participant_can_resume(self, experiment, participant):
        """Return whether the authoritative waiting condition has cleared."""
        raise NotImplementedError

    def participant_timed_out(self, participant):
        """Return whether the authoritative hold deadline has passed."""
        record = self.get_hold_record(participant)
        if record is None:
            return False
        deadline = record.deadline
        return deadline is not None and timenow() >= deadline

    def is_ready_to_resume(self, experiment, participant):
        """Return whether this hold can resume, without timeout side effects.

        ``GET /timeline`` uses this to decide whether to relock before
        ``prepare_resume_if_ready``. Applying timeout or fail before
        ``FOR UPDATE`` can stall a worker or fail a waiter a partner already
        advanced.
        """
        if participant.pending_redirect is not None or participant.failed:
            return True
        if getattr(participant, "page_uuid", None) is not None:
            if self.get_hold_record(participant) is None:
                return False
        if self.participant_timed_out(participant):
            return True
        return bool(self.participant_can_resume(experiment, participant))

    def prepare_resume_if_ready(self, experiment, participant):
        """Prepare a cleared or timed-out hold and return whether it can resume."""
        if participant.pending_redirect is not None or participant.failed:
            self.prepare_to_resume(participant)
            return True
        if getattr(participant, "page_uuid", None) is not None:
            if self.get_hold_record(participant) is None:
                return False
        if self.participant_timed_out(participant):
            self.prepare_to_resume(participant)
            self.apply_timeout(participant)
            return True
        if self.participant_can_resume(experiment, participant):
            self.prepare_to_resume(participant)
            return True
        return False

    def prepare_to_resume(self, participant):
        """Run subclass-specific cleanup immediately before settlement."""

    @property
    def fail_on_timeout(self):
        """Return whether exceeding the deadline should fail the participant."""
        return self._fail_on_timeout

    def apply_timeout(self, participant):
        """Run timeout side effects and optionally fail the participant."""
        if self.on_timeout is not None:
            call_function_with_context(self.on_timeout, participant=participant)
        if self.fail_on_timeout:
            participant.append_failure_tags(
                f"timeline_hold:{self.hold_id}",
                "fail_on_timeout",
            )
            participant.fail()

    def account_wait(self, participant, settle=False):
        """Update actual wait diagnostics and compensation."""
        record = self.get_hold_record(participant)
        if record is None:
            return
        if settle:
            record.settle(participant)
        else:
            record.account_until(participant, timenow())

    def translated_content(self):
        """Translate framework-provided hold messages for this participant."""
        _p = get_translator(context=True)
        if self.message_kind == "barrier":
            return _p("timeline_hold", "Waiting for other participants…")
        if self.message_kind == "generic":
            return _p(
                "timeline_hold",
                "Please wait, the experiment should continue shortly...",
            )
        return self.content

    def overlay_html(self, participant=None):
        """Return hold copy as HTML for both Jinja and the dynamic overlay.

        Trusted ``Markup`` is preserved; plain strings are escaped so a refresh
        and an in-place overlay show the same text.
        """
        content = self.translated_content()
        if content is None:
            title_html = ""
        elif isinstance(content, Markup):
            title_html = str(content)
        else:
            title_html = str(escape(content))
        return compose_hold_overlay_html(
            title_html, self.hold_progress_text(participant)
        )

    def hold_progress_text(self, participant):
        """Return optional live progress copy for this hold visit."""
        return None

    def timeline_hold_payload(self, participant):
        """Return browser configuration for this hold visit.

        Returns ``None`` when the hold record is already gone, so a stale
        page object cannot crash while building attributes.
        """
        record = self.get_hold_record(participant)
        if record is None:
            return None
        remaining_timeout_ms = None
        if record.deadline is not None:
            remaining_timeout_ms = max(
                0, round((record.deadline - timenow()).total_seconds() * 1000)
            )
        return {
            "channel": _timeline_hold_channel(participant.id),
            "hold_id": self.hold_id,
            "message": self.overlay_html(participant),
            "page_uuid": participant.page_uuid,
            "wake_token": record.wake_token,
            "safety_poll_ms": round(self.check_interval * 1000),
            "timeout_ms": remaining_timeout_ms,
        }

    def attributes(self, participant):
        attributes = super().attributes(participant)
        payload = self.timeline_hold_payload(participant)
        if payload is not None:
            attributes["timeline_hold"] = payload
        return attributes

    def get_bot_response(self, experiment, bot):
        return None


class _ConditionHoldPage(_TimelineHoldPage):
    """Timeline hold whose release is determined by an arbitrary condition."""

    def __init__(self, *, condition, **kwargs):
        self.condition = condition
        super().__init__(**kwargs)

    def participant_can_resume(self, experiment, participant):
        return not call_function_with_context(
            self.condition,
            experiment=experiment,
            participant=participant,
        )

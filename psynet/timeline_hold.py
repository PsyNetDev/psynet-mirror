"""Durable in-place waiting for server-side timeline conditions.

Timeline holds preserve the currently rendered participant page while the
server waits for a condition to clear. This module owns the durable accounting
record and the internal page protocol shared by barriers and ``wait_while``.
Hold-release websocket wakes publish after the next database commit. Last-arrival
finalize can defer those publishes until its stacked checks finish so waiting
partners are not woken while later checks still lock their rows.
``GET /timeline`` and ``POST /response`` skip ready holds under a participant
row lock, but they do not share that lock protocol. The page lifecycle
developer docs describe the resume protocol.
"""

import json
import uuid
from contextlib import contextmanager
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
_DEFERRED_WAKE_KEY = "psynet_deferred_timeline_hold_wakes"
_WAKE_DEFER_DEPTH_KEY = "psynet_timeline_hold_wake_defer_depth"
_NESTED_WAKE_SNAPSHOTS_KEY = "psynet_nested_timeline_hold_wake_keys"
logger = get_logger()


def _enqueue_timeline_hold_wake(
    participant_id, *, page_uuid=None, reason=None, hold=None
):
    """Queue a targeted hold wake for publication after the next commit.

    Pass ``hold`` when the caller already has the unresumed record so this
    path does not look it up again.
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
    db.session.info.setdefault(_PENDING_WAKE_KEY, {})[active_hold.wake_token] = wake


def _queue_timeline_hold_wake(
    participant_id, *, page_uuid=None, reason=None, hold=None
):
    """Queue a wake without allowing notification failure to break core work."""
    try:
        _enqueue_timeline_hold_wake(
            participant_id,
            page_uuid=page_uuid,
            reason=reason,
            hold=hold,
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
    has a response body. SAVEPOINT releases are not durable: nested
    ``after_commit`` does not publish or stash. Nested rollback restores pending
    wakes to the keys that existed when that savepoint began. Root rollback
    still discards uncommitted pending wakes; already committed wakes stay
    deferred and flush here even if a later check fails.
    """
    session = db.session
    depth = session.info.get(_WAKE_DEFER_DEPTH_KEY, 0)
    session.info[_WAKE_DEFER_DEPTH_KEY] = depth + 1
    try:
        yield
    finally:
        if depth == 0:
            session.info.pop(_WAKE_DEFER_DEPTH_KEY, None)
            _flush_deferred_timeline_hold_wakes(session)
        else:
            session.info[_WAKE_DEFER_DEPTH_KEY] = depth


def _stash_committed_wakes(session, pending):
    """Move committed wakes into the deferred stash instead of publishing."""
    if not pending:
        return
    deferred = session.info.setdefault(_DEFERRED_WAKE_KEY, {})
    deferred.update(_copy_pending_wakes(pending))


def _publish_wakes(wakes):
    """Publish copied wake payloads on their participant Redis channels."""
    if not wakes:
        return
    try:
        from collections import defaultdict

        by_channel = defaultdict(list)
        for wake in wakes:
            payload = dict(wake)
            participant_id = payload.pop("participant_id", None)
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


def _flush_deferred_timeline_hold_wakes(session):
    """Publish wakes that committed while publishes were deferred."""
    deferred = session.info.pop(_DEFERRED_WAKE_KEY, None)
    if deferred:
        _publish_wakes(list(deferred.values()))


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
    if session.info.get(_WAKE_DEFER_DEPTH_KEY, 0):
        _stash_committed_wakes(session, pending)
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
    def for_stale_hold_resume(
        cls,
        participant,
        submitted_page_uuid,
        current_page,
        *,
        leftover_overlay=False,
    ):
        """Return the submitted hold when it is still a catch-up from a wait page.

        One indexed lookup. A hold-resume leftover overlay (already on a later
        hold) stays rejected so the browser reloads. Ordinary submits catch up
        even onto a later hold: automated drivers do not send
        ``timeline_hold_resume`` and cannot reload an overlay.
        """
        if leftover_overlay and getattr(current_page, "is_timeline_hold", False):
            return None
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

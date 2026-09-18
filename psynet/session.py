"""Live sessions for real-time PsyNet interactions.

Authoritative session rows live on ``live_session``. Opt-in state-log snapshots
share one polymorphic ``live_session_state_log`` table, like trials on ``info``.
"""

from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from functools import wraps
from typing import ClassVar, get_type_hints

from dallinger import db
from dallinger.db import redis_conn
from dallinger.models import timenow
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship

from psynet.data import SQLBase, SQLMixin, register_table
from psynet.field import PythonDict, PythonList
from psynet.modular_page import Control, NoArgumentProvided
from psynet.page import WaitPage
from psynet.sync import GroupBarrier
from psynet.utils import get_logger, model_name_to_snake_case
from psynet.websocket import ClientWebSocketMessage, ServerWebSocketMessage

STATE_REQUEST_EVENT = "stateRequest"
STATE_SNAPSHOT_EVENT = "stateSnapshot"
READY_EVENT = "ready"
SESSION_START_EVENT = "sessionStart"
SESSION_END_EVENT = "sessionEnd"
LIVE_SESSION_STATE_LOG_QUEUE = "psynet:live-session-state-log"
LIVE_SESSION_STATE_LOG_BATCH_SIZE = 100
LIVE_SESSION_STATE_LOG_POLL_TIMEOUT = 1

_LIVE_SESSION_METADATA_COLUMNS = {
    "id",
    "type",
    "vars",
    "session_type",
    "group_type",
    "initializer_id",
    "participant_ids",
    "ready_participant_ids",
    "started",
    "ended",
    "start_time",
    "end_time",
    "sync_group_id",
    "node_id",
    "network_id",
}
_LIVE_SESSION_STATE_LOG_METADATA_COLUMNS = {
    "id",
    "type",
    "vars",
    "session_id",
    "participant_id",
    "trigger_event_type",
    "message_time",
    "log_time",
}
_LIVE_SESSION_STATE_LOG_MODELS: dict[type, type[SQLBase]] = {}
_LIVE_SESSION_STATE_LOG_MODELS_BY_IDENTITY: dict[tuple[str, str], type[SQLBase]] = {}
LIVE_SESSION_STATE_LOG_TABLE = "live_session_state_log"
_LIVE_SESSION_STATE_LOG_DRAINER_STARTED = False
_LIVE_SESSION_STATE_LOG_DRAINER_LOCK = threading.Lock()


def _reusable_live_session_column(name: str, column):
    """Return a declared live-session column that reuses existing table columns."""

    @declared_attr
    def _column(cls):
        return cls.__table__.c.get(name, column)

    return _column


logger = get_logger()


def _live_session_class_identity(session_class):
    return session_class.__module__, session_class.__qualname__


def _same_live_session_class_identity(first, second):
    return _live_session_class_identity(first) == _live_session_class_identity(second)


def _live_session_state_column_names(session_class):
    return tuple(getattr(session_class, "_live_session_state_column_names", ()))


def _is_generic_live_session(session_class):
    return (
        session_class.__name__ == "LiveSession" and session_class.__module__ == __name__
    )


def _live_session_state_column_type(session_class, name):
    column_types = getattr(session_class, "_live_session_state_column_types", {})
    if name in column_types:
        return column_types[name]
    table = getattr(session_class, "__table__", None)
    if table is not None and name in table.c:
        return table.c[name].type
    raise AttributeError(
        f"{session_class.__name__} has no live-session state column {name!r}."
    )


def _live_session_state_log_model_columns(session_class):
    state_column_names = _live_session_state_column_names(session_class)
    conflicting_fields = set(state_column_names).intersection(
        _LIVE_SESSION_STATE_LOG_METADATA_COLUMNS
    )
    if conflicting_fields:
        fields = ", ".join(sorted(conflicting_fields))
        raise ValueError(
            "Live-session state log field names cannot shadow metadata columns: "
            f"{fields}."
        )

    return {
        name: Column(
            _live_session_state_column_type(session_class, name), nullable=True
        )
        for name in state_column_names
    }


def _remember_live_session_state_log_model(session_class, log_model):
    identity = _live_session_class_identity(session_class)
    _LIVE_SESSION_STATE_LOG_MODELS[session_class] = log_model
    _LIVE_SESSION_STATE_LOG_MODELS_BY_IDENTITY[identity] = log_model
    return log_model


@register_table
class LiveSessionStateLog(SQLBase, SQLMixin):
    """Polymorphic persisted snapshot of authoritative live-session state."""

    __tablename__ = LIVE_SESSION_STATE_LOG_TABLE
    __live_session_class__ = None

    session_id = Column(
        Integer,
        ForeignKey("live_session.id"),
        index=True,
        nullable=False,
    )
    participant_id = Column(Integer, index=True, nullable=True)
    trigger_event_type = Column(String(128), index=True, nullable=True)
    message_time = Column(DateTime, nullable=False)
    log_time = Column(DateTime, nullable=False)
    state = Column(PythonDict, nullable=True)


def get_live_session_state_log_model(session_class):
    """Return the SQL model used to persist state logs for a live-session class."""

    if session_class in _LIVE_SESSION_STATE_LOG_MODELS:
        return _LIVE_SESSION_STATE_LOG_MODELS[session_class]

    identity = _live_session_class_identity(session_class)
    if identity in _LIVE_SESSION_STATE_LOG_MODELS_BY_IDENTITY:
        existing_model = _LIVE_SESSION_STATE_LOG_MODELS_BY_IDENTITY[identity]
        _LIVE_SESSION_STATE_LOG_MODELS[session_class] = existing_model
        return existing_model

    if _is_generic_live_session(session_class):
        LiveSessionStateLog.__live_session_class__ = session_class
        return _remember_live_session_state_log_model(
            session_class, LiveSessionStateLog
        )

    attrs = {
        "__module__": __name__,
        "__doc__": (
            "Persisted authoritative state log for "
            f"{session_class.__name__} live sessions."
        ),
        "__live_session_class__": session_class,
    }
    for name, column in _live_session_state_log_model_columns(session_class).items():
        attrs[name] = _reusable_live_session_column(name, column)

    log_model = type(f"{session_class.__name__}StateLog", (LiveSessionStateLog,), attrs)
    return _remember_live_session_state_log_model(session_class, log_model)


def _live_session_state_log_model_from_identity(identity):
    try:
        return _LIVE_SESSION_STATE_LOG_MODELS_BY_IDENTITY[tuple(identity)]
    except KeyError as exc:
        raise ValueError(f"Unknown live-session state log class: {identity}") from exc


def _live_session_state_log_values(live_session):
    session_class = type(live_session)
    if _is_generic_live_session(session_class):
        return {"state": deepcopy(live_session.vars or {})}

    return {
        name: deepcopy(getattr(live_session, name))
        for name in _live_session_state_column_names(session_class)
    }


def _coerce_log_time(value):
    return timenow() if value is None else value


def _make_live_session_state_log_record(
    *,
    live_session,
    participant,
    trigger_event_type: str | None,
    message_time,
):
    log_model = get_live_session_state_log_model(type(live_session))
    return {
        "table_name": log_model.__tablename__,
        "session_class": list(_live_session_class_identity(type(live_session))),
        "session_id": int(live_session.id),
        "participant_id": int(participant.id) if participant is not None else None,
        "trigger_event_type": trigger_event_type,
        "message_time": _coerce_log_time(message_time),
        "log_time": timenow(),
        "values": _live_session_state_log_values(live_session),
    }


def _encode_live_session_state_log_payload(record):
    from psynet.serialize import serialize

    return serialize(record)


def _decode_live_session_state_log_payload(payload):
    from psynet.serialize import unserialize

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return unserialize(payload)


def enqueue_live_session_state_log_record(record: dict):
    """Queue one authoritative live-session state log for batched persistence."""

    enqueue_live_session_state_log_records([record])


def enqueue_live_session_state_log_records(records):
    """Queue authoritative live-session state logs for batched persistence."""

    records = list(records)
    if not records:
        return

    try:
        redis_conn.rpush(
            LIVE_SESSION_STATE_LOG_QUEUE,
            *[_encode_live_session_state_log_payload(record) for record in records],
        )
    except Exception as exc:  # pragma: no cover - depends on Redis availability
        logger.warning("Failed to queue live-session state logs for saving: %s", exc)


def queue_live_session_state_log(
    *,
    live_session,
    participant,
    trigger_event_type: str | None,
    message_time=None,
):
    """Build and queue one authoritative live-session state log."""

    enqueue_live_session_state_log_record(
        _make_live_session_state_log_record(
            live_session=live_session,
            participant=participant,
            trigger_event_type=trigger_event_type,
            message_time=message_time,
        )
    )


def _pop_live_session_state_log_payloads(max_batch_size, *, block: bool):
    payloads = []
    if block:
        item = redis_conn.blpop(
            [LIVE_SESSION_STATE_LOG_QUEUE],
            timeout=LIVE_SESSION_STATE_LOG_POLL_TIMEOUT,
        )
        if item is None:
            return payloads
        payloads.append(item[1])

    while len(payloads) < max_batch_size:
        payload = redis_conn.lpop(LIVE_SESSION_STATE_LOG_QUEUE)
        if payload is None:
            break
        payloads.append(payload)
    return payloads


def _requeue_live_session_state_log_payloads(payloads):
    if not payloads:
        return
    try:
        redis_conn.lpush(LIVE_SESSION_STATE_LOG_QUEUE, *reversed(payloads))
    except Exception as exc:  # pragma: no cover - depends on Redis availability
        logger.warning("Failed to requeue live-session state logs after error: %s", exc)


def _live_session_state_log_from_record(record):
    identity = record.get("session_class")
    if identity is None:
        raise ValueError("Live-session state log record is missing session_class.")
    log_model = _live_session_state_log_model_from_identity(identity)
    return log_model(
        session_id=record["session_id"],
        participant_id=record.get("participant_id"),
        trigger_event_type=record.get("trigger_event_type"),
        message_time=record["message_time"],
        log_time=record["log_time"],
        **record.get("values", {}),
    )


def drain_live_session_state_log_queue_once(
    max_batch_size=LIVE_SESSION_STATE_LOG_BATCH_SIZE,
    *,
    block: bool = False,
):
    """Persist one batch of queued live-session state logs."""

    try:
        payloads = _pop_live_session_state_log_payloads(max_batch_size, block=block)
    except Exception as exc:  # pragma: no cover - depends on Redis availability
        logger.warning("Failed to read live-session state log queue: %s", exc)
        return 0

    events = []
    valid_payloads = []
    for payload in payloads:
        try:
            record = _decode_live_session_state_log_payload(payload)
            events.append(_live_session_state_log_from_record(record))
            valid_payloads.append(payload)
        except Exception as exc:
            logger.warning("Discarded invalid live-session state log payload: %s", exc)

    if not events:
        return 0

    try:
        db.session.add_all(events)
        db.session.commit()
    except Exception as exc:  # pragma: no cover - depends on database availability
        db.session.rollback()
        _requeue_live_session_state_log_payloads(valid_payloads)
        logger.warning("Failed to save live-session state log batch: %s", exc)
        return 0

    return len(events)


def _live_session_state_log_drainer_loop():  # pragma: no cover - live runtime path
    while True:
        drain_live_session_state_log_queue_once(block=True)
        time.sleep(0)


def start_live_session_state_log_drainer():
    """Start the per-process drainer for live-session state logs."""

    global _LIVE_SESSION_STATE_LOG_DRAINER_STARTED
    with _LIVE_SESSION_STATE_LOG_DRAINER_LOCK:
        if _LIVE_SESSION_STATE_LOG_DRAINER_STARTED:
            return
        thread = threading.Thread(
            target=_live_session_state_log_drainer_loop,
            name="psynet-live-session-state-log-drainer",
            daemon=True,
        )
        thread.start()
        _LIVE_SESSION_STATE_LOG_DRAINER_STARTED = True


def _resolve_session_argument_class(method, argument: str, explicit_session_class):
    if explicit_session_class is not None:
        return explicit_session_class

    try:
        session_class = get_type_hints(method).get(argument)
    except (NameError, TypeError) as exc:
        raise TypeError(
            "Could not resolve live-session handler annotation for "
            f"{method.__qualname__}.{argument}; pass the session class "
            "explicitly to @session(...)."
        ) from exc

    if session_class is None:
        raise TypeError(
            f"{method.__qualname__} must annotate its {argument!r} "
            "argument or pass a session class to @session(...)."
        )
    return session_class


def _get_message_session(message, participant, session_class, *, lock: bool):
    session_id = message.session_id
    if session_id is None:
        return None
    return session_class.get_current_for_participant(
        participant,
        session_id,
        for_update=lock,
    )


def session(
    session_class=None,
    *,
    mutate: bool = False,
    logging: bool = False,
    argument: str = "session",
):
    """Inject a participant-owned live session into a WebSocket message handler.

    Set ``mutate=True`` for handlers that mutate session state. This locks the
    row, commits on success, and rolls back if the handler raises. Set
    ``logging=True`` with ``mutate=True`` to queue an authoritative state log
    after a successful commit.
    """

    if not isinstance(mutate, bool):
        raise TypeError("session mutate must be a boolean.")
    if not isinstance(logging, bool):
        raise TypeError("session logging must be a boolean.")
    if logging and not mutate:
        raise TypeError("session logging requires mutate=True.")
    if not isinstance(argument, str) or not argument:
        raise ValueError("session argument must be a non-empty string.")

    def decorate(method):
        resolved_session_class = None

        @wraps(method)
        def wrapper(self, experiment, participant, receive_time=None):
            nonlocal resolved_session_class
            if resolved_session_class is None:
                resolved_session_class = _resolve_session_argument_class(
                    method,
                    argument,
                    session_class,
                )
            live_session = _get_message_session(
                self,
                participant,
                resolved_session_class,
                lock=mutate,
            )
            if live_session is None:
                logger.warning(
                    "Rejected live-session websocket event: invalid session "
                    "(participant_id=%s, session_id=%s, event_type=%s)",
                    participant.id,
                    self.session_id,
                    type(self).event_type,
                )
                return None

            state_log_record = None
            try:
                result = method(
                    self,
                    experiment=experiment,
                    participant=participant,
                    receive_time=receive_time,
                    **{argument: live_session},
                )
                if logging:
                    state_log_record = _make_live_session_state_log_record(
                        live_session=live_session,
                        participant=participant,
                        trigger_event_type=type(self).event_type,
                        message_time=receive_time,
                    )
            except Exception:
                if mutate:
                    db.session.rollback()
                raise

            if mutate:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    raise
            if state_log_record is not None:
                enqueue_live_session_state_log_record(state_log_record)
            return result

        return wrapper

    return decorate


class StateRequestMessage(ClientWebSocketMessage):
    """Request the latest authoritative state for a live session."""

    event_type: ClassVar[str] = STATE_REQUEST_EVENT
    fields: list[str] | None = None

    @session()
    def handle(self, experiment, participant, session: LiveSession, receive_time):
        session.send_snapshot(participants=participant, fields=self.fields)


class ReadyMessage(ClientWebSocketMessage):
    """Notify the server that a participant is ready for a live session to start."""

    event_type: ClassVar[str] = READY_EVENT

    @session(mutate=True)
    def handle(self, experiment, participant, session: LiveSession, receive_time):
        if session.mark_ready(participant):
            session.send_session_start()


class StateSnapshotMessage(ServerWebSocketMessage):
    """Authoritative live-session state sent to browser clients."""

    event_type: ClassVar[str] = STATE_SNAPSHOT_EVENT
    save: ClassVar[bool] = False
    session_id: int
    state: dict
    participant_ids: list[str]
    ready_participant_ids: list[str]
    started: bool
    ended: bool


class SessionStartMessage(StateSnapshotMessage):
    """Initial live-session state sent when all participants are ready."""

    event_type: ClassVar[str] = SESSION_START_EVENT


class SessionEndMessage(StateSnapshotMessage):
    """Final live-session state sent when a live session ends."""

    event_type: ClassVar[str] = SESSION_END_EVENT


class _LiveSessionMixin:
    """Shared columns and behavior for persisted live-session rows."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        state_column_names = set(getattr(cls, "_live_session_state_column_names", ()))
        column_types = dict(getattr(cls, "_live_session_state_column_types", {}))
        for name, value in list(cls.__dict__.items()):
            if name in _LIVE_SESSION_METADATA_COLUMNS:
                continue
            if isinstance(value, Column):
                state_column_names.add(name)
                column_types[name] = value.type
                setattr(cls, name, _reusable_live_session_column(name, value))
        cls._live_session_state_column_names = tuple(sorted(state_column_names))
        cls._live_session_state_column_types = column_types
        get_live_session_state_log_model(cls)

    session_type = Column(String, index=True)
    group_type = Column(String, index=True)
    initializer_id = Column(String, index=True)
    participant_ids = Column(PythonList, default=lambda: [])
    ready_participant_ids = Column(PythonList, default=lambda: [])
    started = Column(Boolean, default=False)
    ended = Column(Boolean, default=False)
    start_time = Column(DateTime)
    end_time = Column(DateTime)

    @declared_attr
    def sync_group_id(cls):
        return Column(Integer, ForeignKey("sync_group.id"), index=True)

    @declared_attr
    def node_id(cls):
        return Column(Integer, ForeignKey("node.id"), index=True, nullable=True)

    @declared_attr
    def network_id(cls):
        return Column(Integer, ForeignKey("network.id"), index=True, nullable=True)

    @declared_attr
    def sync_group(cls):
        return relationship("psynet.sync.SyncGroup", foreign_keys=[cls.sync_group_id])

    @classmethod
    def session_type_label(cls):
        """Return the persistent label for this live-session class."""

        return model_name_to_snake_case(cls.__name__)

    def initialize(self, participant_ids, group):
        """Initialize subclass-owned state columns for a new live session."""

        return None

    @classmethod
    def get(cls, session_id: int, *, for_update=False):
        """Return the live session for a browser-facing row ID, if it exists."""

        try:
            session_id = int(session_id)
        except (TypeError, ValueError):
            return None

        query = cls.query.filter_by(id=session_id)
        if for_update:
            query = query.with_for_update(of=cls).populate_existing()
        return query.one_or_none()

    @classmethod
    def _current_trial_details(cls, group):
        """Return optional node/network IDs from the group leader's trial."""

        leader = group.leader
        trial = leader.current_trial if leader is not None else None
        if trial is None:
            return None, None

        node = trial.node
        node_id = trial.node_id if trial.node_id is not None else node.id
        network_id = (
            trial.network_id if trial.network_id is not None else trial.network.id
        )

        return (
            int(node_id) if node_id is not None else None,
            int(network_id) if network_id is not None else None,
        )

    @classmethod
    def create_for_group(cls, *, group, initializer, participant=None):
        """Create a live session from a leader-owned initializer barrier release."""

        leader = group.leader
        if leader is None:
            raise ValueError(f"Group {group.id} has no leader.")

        if participant is not None and int(participant.id) != int(leader.id):
            raise ValueError("Only the group leader can initialize a live session.")

        participants = sorted(group.active_participants, key=lambda p: p.id)
        participant_ids = [int(participant.id) for participant in participants]
        node_id, network_id = cls._current_trial_details(group)
        live_session = cls(
            session_type=cls.session_type_label(),
            group_type=getattr(group, "group_type", None),
            sync_group_id=int(group.id),
            initializer_id=initializer.id,
            node_id=node_id,
            network_id=network_id,
            participant_ids=participant_ids,
            ready_participant_ids=[],
            started=False,
            ended=False,
            start_time=None,
            end_time=None,
        )
        live_session.initialize(participant_ids, group)
        db.session.add(live_session)
        db.session.flush()
        return live_session

    @classmethod
    def get_for_group(
        cls,
        *,
        group,
        initializer_id: str,
        node_id: int | None = None,
        network_id: int | None = None,
        for_update=False,
    ):
        """Return an existing live session for group/session metadata."""

        query = cls.query.filter_by(
            session_type=cls.session_type_label(),
            group_type=getattr(group, "group_type", None),
            sync_group_id=int(group.id),
            initializer_id=initializer_id,
        )
        query = query.filter(
            cls.node_id.is_(None) if node_id is None else cls.node_id == node_id
        )
        query = query.filter(
            cls.network_id.is_(None)
            if network_id is None
            else cls.network_id == network_id
        )
        if for_update:
            query = query.with_for_update(of=cls).populate_existing()
        matches = query.all()
        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple live sessions found for initializer {initializer_id!r} "
                f"in group {group.id}."
            )
        return matches[0] if matches else None

    def mark_ready(self, participant):
        """Mark a participant ready and return whether this started the session."""

        if not self.has_participant(participant):
            return False

        participant_id = int(participant.id)
        ready = {int(value) for value in (self.ready_participant_ids or [])}
        ready.add(participant_id)
        self.ready_participant_ids = sorted(ready)

        started_now = False
        expected = {int(value) for value in (self.participant_ids or [])}
        if expected and expected.issubset(ready) and not self.started:
            self.started = True
            self.start_time = timenow()
            started_now = True

        return started_now

    def has_participant(self, participant):
        """Return whether a participant belongs to this live session."""

        participant_id = int(participant.id)
        expected = {int(value) for value in (self.participant_ids or [])}
        return participant_id in expected

    @property
    def participants(self):
        """Return participant objects belonging to this live session."""

        if self.sync_group is not None:
            return sorted(self.sync_group.active_participants, key=lambda p: p.id)

        participant_ids = [int(value) for value in (self.participant_ids or [])]
        if not participant_ids:
            return []

        from psynet.participant import Participant

        participants = Participant.query.filter(
            Participant.id.in_(participant_ids)
        ).all()
        return sorted(participants, key=lambda participant: participant.id)

    @property
    def node(self):
        """Return the node context used to initialize this session, if any."""

        if self.node_id is None:
            return None
        from psynet.trial.main import TrialNode

        return TrialNode.query.get(int(self.node_id))

    @classmethod
    def get_current_for_participant(
        cls, participant, session_id: int, *, for_update=False
    ):
        """Return a participant's live session if they belong to the session."""

        live_session = cls.get(session_id, for_update=for_update)
        if live_session is None:
            return None

        if not live_session.has_participant(participant):
            return None
        return live_session

    def mark_ended(self):
        """Mark this live session ended if it has not already ended."""

        if self.ended:
            return False
        self.ended = True
        self.end_time = timenow()
        return True

    def end(self):
        """Mark this live session ended and emit the built-in sessionEnd event."""

        if self.mark_ended():
            self.send_session_end()
            return True
        return False

    def _lifecycle_payload(self) -> dict:
        """Return JSON-serializable live-session lifecycle fields."""

        return {
            "session_id": int(self.id),
            "participant_ids": [str(value) for value in (self.participant_ids or [])],
            "ready_participant_ids": [
                str(value) for value in (self.ready_participant_ids or [])
            ],
            "started": bool(self.started),
            "ended": bool(self.ended),
        }

    def snapshot_payload(
        self, fields: list[str] | None = None, participant=None
    ) -> dict:
        """Return a JSON-serializable state snapshot payload."""

        return {
            **self._lifecycle_payload(),
            "state": self.snapshot_state(fields=fields, participant=participant),
        }

    def snapshot_state(self, fields: list[str] | None = None, participant=None) -> dict:
        """Return browser-facing public state.

        Concrete subclasses are snapshotted from their SQL columns. Direct base
        ``LiveSession`` rows fall back to PsyNet's generic ``var``/``vars``
        store for compatibility, but explicit subclass columns are preferred.
        Subclasses can override this when state should be filtered, renamed, or
        tailored to a specific participant.
        """

        requested = set(fields) if fields is not None else None
        if self.__class__ is LiveSession:
            state = deepcopy(self.vars or {})
            if requested is not None:
                state = {field: state[field] for field in fields if field in state}
            return state

        state = {}
        for column_attr in self.__mapper__.column_attrs:
            key = column_attr.key
            if key in _LIVE_SESSION_METADATA_COLUMNS:
                continue
            if requested is not None and key not in requested:
                continue
            value = getattr(self, key)
            if value is not None:
                state[key] = deepcopy(value)
        return state

    def snapshot_message(
        self, fields: list[str] | None = None, participant=None
    ) -> StateSnapshotMessage:
        """Return the typed state snapshot WebSocket message."""

        return StateSnapshotMessage(
            **self.snapshot_payload(fields=fields, participant=participant)
        )

    def send_snapshot(self, participants=None, fields: list[str] | None = None):
        """Send the current snapshot to all live-session participants or a subset."""

        if participants is None:
            participants = self.participants
        if not isinstance(participants, (list, tuple, set)):
            participants = [participants]
        for participant in participants:
            self.snapshot_message(fields=fields, participant=participant).send(
                participant
            )

    def send_session_start(self):
        """Send the built-in session start event to live-session participants."""

        for participant in self.participants:
            SessionStartMessage(**self.snapshot_payload(participant=participant)).send(
                participant
            )

    def send_session_end(self):
        """Send the built-in session end event to live-session participants."""

        for participant in self.participants:
            SessionEndMessage(**self.snapshot_payload(participant=participant)).send(
                participant
            )

    @classmethod
    def trigger_end_event(cls, session_id):
        """Mark a live session ended and send its built-in sessionEnd event."""

        from psynet.db import transaction

        with transaction():
            live_session = cls.get(session_id, for_update=True)
            if live_session is None:
                return False
            return live_session.end()


@register_table
class LiveSession(_LiveSessionMixin, SQLBase, SQLMixin):
    """Generic persisted live session."""

    __tablename__ = "live_session"


class LiveSessionInitializer(GroupBarrier):
    """Timeline element that creates a group-owned live session."""

    @staticmethod
    def _create_live_session_on_release(group, participants, participant, barrier):
        """Create the live session owned by a released group barrier."""

        return barrier.session_class.create_for_group(
            group=group,
            initializer=barrier,
            participant=participant,
        )

    def __init__(
        self,
        id_: str,
        group_type: str,
        session_class=LiveSession,
        waiting_logic=NoArgumentProvided,
        waiting_logic_expected_repetitions=3,
        max_wait_time=20,
        fix_time_credit=False,
    ):
        self.session_class = session_class
        if waiting_logic is NoArgumentProvided:
            waiting_logic = WaitPage(wait_time=0.5, save_answer=False)

        super().__init__(
            id_=id_,
            group_type=group_type,
            waiting_logic=waiting_logic,
            waiting_logic_expected_repetitions=waiting_logic_expected_repetitions,
            max_wait_time=max_wait_time,
            on_release=LiveSessionInitializer._create_live_session_on_release,
            fix_time_credit=fix_time_credit,
        )


class LiveSessionControl(Control):
    """Control base class that configures a live session for browser code."""

    def __init__(
        self,
        *,
        participant,
        session_class,
        group_type: str,
        session_initializer_id: str,
        bot_response=NoArgumentProvided,
        buttons=None,
        show_next_button: bool | None = False,
    ):
        super().__init__(
            bot_response=bot_response,
            buttons=buttons,
            show_next_button=show_next_button,
        )
        self.participant = participant
        self.session_class = session_class
        self.group_type = group_type
        self.session_initializer_id = session_initializer_id
        self._session_id = None

    def _get_group(self):
        """Return the participant's active group for this live session."""

        try:
            group = self.participant.active_sync_groups[self.group_type]
        except KeyError as exc:
            raise ValueError(
                f"Participant {self.participant.id} has no active sync group "
                f"for group_type {self.group_type!r}."
            ) from exc
        if group is None:
            raise ValueError("LiveSessionControl requires an active sync group.")
        return group

    def _resolve_session_id(self):
        """Resolve the initialized live-session row ID for this control."""

        if self._session_id is not None:
            return self._session_id

        group = self._get_group()
        node_id, network_id = self.session_class._current_trial_details(group)
        live_session = self.session_class.get_for_group(
            group=group,
            initializer_id=self.session_initializer_id,
            node_id=node_id,
            network_id=network_id,
        )
        if live_session is None:
            raise RuntimeError(
                f"No live session prepared for initializer "
                f"{self.session_initializer_id!r} in group {int(group.id)}."
            )
        if live_session.id is None:
            raise RuntimeError("Live session must be flushed before rendering.")
        self._session_id = int(live_session.id)
        return self._session_id

    def pre_render(self):
        """Resolve the live-session ID before rendering the control template."""

        session_id = self._resolve_session_id()
        if self.page is not None:
            config = {
                "session_id": session_id,
                "participant_id": int(self.participant.id),
            }
            init_js = f"psynet.session.init({json.dumps(config)});"
            self.page.events["liveSessionInit"]["js"] = init_js

    def update_events(self, events):
        """Initialize the browser live-session helper via PsyNet events."""

        from psynet.timeline import Event

        super().update_events(events)
        events["liveSessionInit"] = Event(
            is_triggered_by="trialConstruct",
            once=True,
        )

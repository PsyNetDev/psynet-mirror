from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dallinger import db
from sqlalchemy import Column, Integer, String

from psynet.data import sql_base_classes
from psynet.field import PythonDict, PythonList
from psynet.session import (
    LIVE_SESSION_STATE_LOG_QUEUE,
    LIVE_SESSION_STATE_LOG_TABLE,
    LiveSession,
    LiveSessionControl,
    LiveSessionInitializer,
    LiveSessionStateLog,
    ReadyMessage,
    SessionEndMessage,
    SessionStartMessage,
    StateRequestMessage,
    _decode_live_session_state_log_payload,
    _make_live_session_state_log_record,
    drain_live_session_state_log_queue_once,
    enqueue_live_session_state_log_record,
    get_live_session_state_log_model,
)
from psynet.session import (
    session as session_context,
)
from psynet.websocket import ClientWebSocketMessage


class PolymorphicDemoLiveSession(LiveSession):
    """Demo custom live session that shares the generic live_session table."""

    custom_value = Column(String)
    score = Column(Integer)
    round_number = Column(Integer)
    initial_node_id = Column(Integer)
    initial_participant_ids = Column(PythonList)

    def initialize(self, participant_ids, group):
        """Initialize test-specific session state columns."""

        self.initial_participant_ids = participant_ids
        self.initial_node_id = self.node_id


class FilteredDemoLiveSession(LiveSession):
    """Demo custom live session that overrides public snapshot filtering."""

    public_value = Column(String)
    private_value = Column(String)

    def snapshot_state(self, fields=None, participant=None):
        """Expose only the public column by default."""

        state = {"public_value": self.public_value}
        if fields is not None:
            state = {field: state[field] for field in fields if field in state}
        return state


class ParticipantAwareDemoLiveSession(LiveSession):
    """Demo live session with participant-specific snapshot overrides."""

    participant_public_value = Column(String)
    participant_values = Column(PythonDict)

    def snapshot_state(self, fields=None, participant=None):
        """Expose public state plus participant-specific state when available."""

        state = super().snapshot_state(fields=None, participant=participant)
        participant_values = state.pop("participant_values", {}) or {}
        if participant is not None:
            participant_value = participant_values.get(str(participant.id))
            if participant_value is not None:
                state["participant_value"] = participant_value
        if fields is not None:
            state = {field: state[field] for field in fields if field in state}
        return state


class LoggedDemoLiveSession(LiveSession):
    """Demo live session whose state log should include private columns."""

    public_value = Column(String)
    private_value = Column(String)
    counter = Column(Integer)
    details = Column(PythonDict)

    def snapshot_state(self, fields=None, participant=None):
        """Expose only the public column to browser snapshots."""

        return {"public_value": self.public_value}


class EagerRegisteredLiveSession(LiveSession):
    """Live session whose state-log table is registered when the class is defined."""

    eager_registration_value = Column(String)


class EagerRegisteredMessage(ClientWebSocketMessage):
    event_type = "eagerRegistered"

    @session_context(
        EagerRegisteredLiveSession,
        mutate=True,
        logging=True,
    )
    def handle(self, experiment, participant, session, receive_time):
        return None


class ForwardRefLoggedMessage(ClientWebSocketMessage):
    event_type = "forwardRefLogged"

    @session_context(mutate=True, logging=True)
    def handle(
        self,
        experiment,
        participant,
        session: "ForwardRefLoggedLiveSession",
        receive_time,
    ):
        return None


class ForwardRefLoggedLiveSession(LiveSession):
    """Live session referenced by a forward annotation on a logged handler."""

    forward_ref_value = Column(String)


class ReusedColumnDemoLiveSessionA(LiveSession):
    """Demo live session that declares a reusable subclass column."""

    reusable_value = Column(String)


class ReusedColumnDemoLiveSessionB(LiveSession):
    """Demo live session that reuses an already-declared subclass column."""

    reusable_value = Column(String)


def _participants():
    return [
        SimpleNamespace(id=1, page_uuid="page-1", module_state=None),
        SimpleNamespace(id=2, page_uuid="page-2", module_state=None),
    ]


def _state(*, score=3, round_number=None):
    participants = _participants()
    state = PolymorphicDemoLiveSession(
        score=score,
        round_number=round_number,
        participant_ids=[1, 2],
        ready_participant_ids=[],
        started=False,
        ended=False,
    )
    state.id = 1
    state.__dict__["sync_group"] = SimpleNamespace(active_participants=participants)
    return state


def _capture_server_sends(monkeypatch):
    sent = []

    def send(self, participants):
        sent.append((participants, self))

    monkeypatch.setattr("psynet.websocket.ServerWebSocketMessage.send", send)
    return sent


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.on_rpush = None

    def rpush(self, key, *values):
        if self.on_rpush is not None:
            self.on_rpush()
        stored_values = self.lists.setdefault(key, [])
        stored_values.extend(values)
        return len(stored_values)

    def lpush(self, key, *values):
        stored_values = self.lists.setdefault(key, [])
        for value in values:
            stored_values.insert(0, value)
        return len(stored_values)

    def lpop(self, key):
        values = self.lists.get(key, [])
        if not values:
            return None
        return values.pop(0)

    def blpop(self, keys, timeout=0):
        key = keys[0] if isinstance(keys, (list, tuple)) else keys
        value = self.lpop(key)
        if value is None:
            return None
        return key, value


@pytest.fixture
def fake_state_log_redis(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr("psynet.session.redis_conn", fake_redis)
    return fake_redis


def _saved_state_log_records(fake_redis):
    return [
        _decode_live_session_state_log_payload(payload)
        for payload in fake_redis.lists.get(LIVE_SESSION_STATE_LOG_QUEUE, [])
    ]


class LoggedStateMessage(ClientWebSocketMessage):
    """Message used to exercise state logging after a mutating handler."""

    event_type = "loggedState"

    @session_context(mutate=True, logging=True)
    def handle(
        self,
        experiment,
        participant,
        session: LoggedDemoLiveSession,
        receive_time,
    ):
        session.counter = int(session.counter or 0) + 1
        session.public_value = "shown"
        session.private_value = "hidden"
        session.details = {"counter": session.counter}
        return session.id


class FailingLoggedStateMessage(ClientWebSocketMessage):
    """Message used to exercise logging rollback behavior."""

    event_type = "failingLoggedState"

    @session_context(mutate=True, logging=True)
    def handle(
        self,
        experiment,
        participant,
        session: LoggedDemoLiveSession,
        receive_time,
    ):
        session.counter = int(session.counter or 0) + 1
        raise RuntimeError("state update failed")


def _group(*, leader_trial=True):
    participants = _participants()
    node = SimpleNamespace(id=11, network_id=12, definition={"value": "node"})
    network = SimpleNamespace(id=12)
    trial = (
        SimpleNamespace(
            id=7,
            node_id=11,
            network_id=12,
            node=node,
            network=network,
            definition={"value": "trial"},
        )
        if leader_trial
        else None
    )
    participants[0].current_trial = trial
    participants[1].current_trial = SimpleNamespace(id=8, node_id=11, network_id=12)
    group = SimpleNamespace(
        id=9,
        group_type="demo_group",
        participants=participants,
        active_participants=participants,
        leader=participants[0],
    )
    for participant in participants:
        participant.active_sync_groups = {"demo_group": group}
    return group


def test_live_session_tracks_ready_participants_and_started(monkeypatch):
    """LiveSession starts once all expected participants are ready."""

    start_time = datetime(2026, 1, 1, 12, 0, 0)
    monkeypatch.setattr("psynet.session.timenow", lambda: start_time)
    state = _state()

    assert state.mark_ready(SimpleNamespace(id=1)) is False
    assert state.ready_participant_ids == [1]
    assert state.started is False
    assert state.start_time is None

    assert state.mark_ready(SimpleNamespace(id=2)) is True
    assert state.ready_participant_ids == [1, 2]
    assert state.started is True
    assert state.start_time == start_time


def test_live_session_rejects_unknown_ready_participant():
    """Readiness only accepts expected live-session participants."""

    state = _state()

    assert state.mark_ready(SimpleNamespace(id=3)) is False
    assert state.ready_participant_ids == []
    assert state.started is False


def test_live_session_snapshot_payload_is_json_ready():
    """Snapshots expose state, readiness, and participant IDs as browser data."""

    state = _state()
    state.mark_ready(SimpleNamespace(id=1))

    assert state.snapshot_payload() == {
        "session_id": 1,
        "state": {"score": 3},
        "participant_ids": ["1", "2"],
        "ready_participant_ids": ["1"],
        "started": False,
        "ended": False,
    }


def test_live_session_snapshot_payload_can_filter_state_fields():
    """Snapshots can include only selected public state fields."""

    state = _state(round_number=2)

    assert state.snapshot_payload(fields=["score", "missing"])["state"] == {"score": 3}


def test_live_session_snapshot_state_can_be_overridden():
    """Subclasses can hide SQL columns from public state snapshots."""

    state = FilteredDemoLiveSession(
        public_value="shown",
        private_value="hidden",
        participant_ids=[1],
        ready_participant_ids=[],
        started=False,
        ended=False,
    )
    state.id = 1

    assert state.snapshot_payload()["state"] == {"public_value": "shown"}


def test_live_session_snapshot_state_can_use_participant():
    """Snapshot overrides can tailor state to a specific participant."""

    state = ParticipantAwareDemoLiveSession(
        participant_public_value="shown",
        participant_values={"1": "one", "2": "two"},
        participant_ids=[1],
        ready_participant_ids=[],
        started=False,
        ended=False,
    )
    state.id = 1

    assert state.snapshot_payload()["state"] == {"participant_public_value": "shown"}
    assert state.snapshot_payload(participant=SimpleNamespace(id=2))["state"] == {
        "participant_public_value": "shown",
        "participant_value": "two",
    }


def test_live_session_start_message_is_json_ready():
    """Start messages expose readiness and participant-specific state."""

    state = _state()
    state.mark_ready(SimpleNamespace(id=1))
    state.mark_ready(SimpleNamespace(id=2))

    assert SessionStartMessage(**state.snapshot_payload()).model_dump(mode="json") == {
        "session_id": 1,
        "state": {"score": 3},
        "participant_ids": ["1", "2"],
        "ready_participant_ids": ["1", "2"],
        "started": True,
        "ended": False,
    }


def test_state_request_sends_snapshot_to_requesting_participant(monkeypatch):
    """StateRequest sends a snapshot through the experiment websocket helper."""

    state = _state()
    sent = _capture_server_sends(monkeypatch)
    experiment = SimpleNamespace()
    participant = SimpleNamespace(id=1)
    monkeypatch.setattr(LiveSession, "get", classmethod(lambda *args, **kwargs: state))

    StateRequestMessage(session_id=1).handle(
        experiment=experiment,
        participant=participant,
        receive_time=None,
    )
    assert sent == [(participant, state.snapshot_message())]


def test_state_request_can_send_partial_state(monkeypatch):
    """StateRequest forwards requested public state fields."""

    state = _state(round_number=2)
    sent = _capture_server_sends(monkeypatch)
    experiment = SimpleNamespace()
    participant = SimpleNamespace(id=1)
    monkeypatch.setattr(LiveSession, "get", classmethod(lambda *args, **kwargs: state))

    StateRequestMessage(session_id=1, fields=["round_number"]).handle(
        experiment=experiment,
        participant=participant,
        receive_time=None,
    )
    assert sent == [(participant, state.snapshot_message(fields=["round_number"]))]


def test_state_request_rejects_non_member(monkeypatch):
    """StateRequest does not disclose snapshots to non-members."""

    state = _state()
    sent = _capture_server_sends(monkeypatch)
    experiment = SimpleNamespace()
    participant = SimpleNamespace(id=3)
    monkeypatch.setattr(LiveSession, "get", classmethod(lambda *args, **kwargs: state))

    StateRequestMessage(session_id=1).handle(
        experiment=experiment,
        participant=participant,
        receive_time=None,
    )

    assert sent == []


def test_ready_event_sends_start_once_all_participants_are_ready(monkeypatch):
    """ReadyEvent sends start snapshots once the session starts."""

    state = _state()
    sent = _capture_server_sends(monkeypatch)
    experiment = SimpleNamespace()
    monkeypatch.setattr(LiveSession, "get", classmethod(lambda *args, **kwargs: state))
    monkeypatch.setattr("psynet.session.db.session.commit", MagicMock())

    ReadyMessage(session_id=1).handle(
        experiment=experiment,
        participant=SimpleNamespace(id=1),
        receive_time=None,
    )

    assert state.ready_participant_ids == [1]
    assert sent == []

    ReadyMessage(session_id=1).handle(
        experiment=experiment,
        participant=SimpleNamespace(id=2),
        receive_time=None,
    )

    assert state.ready_participant_ids == [1, 2]
    assert sent == [
        (
            participant,
            SessionStartMessage(**state.snapshot_payload(participant=participant)),
        )
        for participant in state.participants
    ]


def test_ready_event_rejects_non_member(monkeypatch):
    """ReadyEvent does not mutate sessions for non-members."""

    state = _state()
    sent = _capture_server_sends(monkeypatch)
    experiment = SimpleNamespace()
    participant = SimpleNamespace(id=3)
    commit = MagicMock()
    monkeypatch.setattr(LiveSession, "get", classmethod(lambda *args, **kwargs: state))
    monkeypatch.setattr("psynet.session.db.session.commit", commit)

    ReadyMessage(session_id=1).handle(
        experiment=experiment,
        participant=participant,
        receive_time=None,
    )

    assert state.ready_participant_ids == []
    assert sent == []
    commit.assert_not_called()


def test_live_session_end_marks_ended_and_notifies(monkeypatch):
    """Live sessions can explicitly emit the built-in sessionEnd event."""

    end_time = datetime(2026, 1, 1, 12, 5, 0)
    monkeypatch.setattr("psynet.session.timenow", lambda: end_time)
    state = _state()
    sent = _capture_server_sends(monkeypatch)

    assert state.end() is True
    assert state.ended is True
    assert state.end_time == end_time
    assert sent == [
        (
            participant,
            SessionEndMessage(**state.snapshot_payload(participant=participant)),
        )
        for participant in state.participants
    ]
    assert state.end() is False


def test_live_session_send_snapshot_renders_per_participant(monkeypatch):
    """Snapshot sends render recipient-specific state separately."""

    participants = _participants()
    state = ParticipantAwareDemoLiveSession(
        participant_public_value="shown",
        participant_values={"1": "one", "2": "two"},
        participant_ids=[1, 2],
        ready_participant_ids=[],
        started=False,
        ended=False,
    )
    state.id = 1
    sent = _capture_server_sends(monkeypatch)

    state.send_snapshot(participants)

    assert [recipient.id for recipient, _message in sent] == [1, 2]
    assert [message.state for _recipient, message in sent] == [
        {"participant_public_value": "shown", "participant_value": "one"},
        {"participant_public_value": "shown", "participant_value": "two"},
    ]


def test_session_logging_registers_state_log_table_eagerly():
    """Live-session subclasses share the registered live_session_state_log table."""

    assert EagerRegisteredMessage
    assert LIVE_SESSION_STATE_LOG_TABLE in db.Base.metadata.tables
    assert LIVE_SESSION_STATE_LOG_TABLE in sql_base_classes()
    assert sql_base_classes()[LIVE_SESSION_STATE_LOG_TABLE] is LiveSessionStateLog
    assert get_live_session_state_log_model(EagerRegisteredLiveSession).inherits_table


def test_session_logging_registers_state_log_table_when_session_class_is_defined():
    """Forward-ref handlers still share the live_session_state_log table."""

    assert ForwardRefLoggedMessage
    assert LIVE_SESSION_STATE_LOG_TABLE in db.Base.metadata.tables
    assert (
        get_live_session_state_log_model(ForwardRefLoggedLiveSession).__tablename__
        == LIVE_SESSION_STATE_LOG_TABLE
    )


def test_live_session_state_log_model_generates_structured_table():
    """State logs use one polymorphic table with per-class state columns."""

    log_model = get_live_session_state_log_model(LoggedDemoLiveSession)
    columns = set(log_model.__table__.columns.keys())

    assert log_model.__tablename__ == LIVE_SESSION_STATE_LOG_TABLE
    assert log_model.inherits_table
    assert issubclass(log_model, LiveSessionStateLog)
    assert {
        "session_id",
        "participant_id",
        "trigger_event_type",
        "message_time",
        "log_time",
        "public_value",
        "private_value",
        "counter",
        "details",
    }.issubset(columns)
    assert "session_type" not in columns
    assert "group_type" not in columns
    assert "sync_group_id" not in columns
    assert "node_id" not in columns
    assert "network_id" not in columns


def test_live_session_state_log_records_authoritative_columns():
    """State logs record raw session columns, not browser-facing snapshots."""

    message_time = datetime(2026, 1, 1, 12, 0, 0)
    live_session = LoggedDemoLiveSession(
        public_value="shown",
        private_value="hidden",
        counter=3,
        details={"secret": True},
    )
    live_session.id = 123
    participant = SimpleNamespace(id=7)

    record = _make_live_session_state_log_record(
        live_session=live_session,
        participant=participant,
        trigger_event_type="loggedState",
        message_time=message_time,
    )

    assert record["table_name"] == LIVE_SESSION_STATE_LOG_TABLE
    assert record["session_class"] == [
        LoggedDemoLiveSession.__module__,
        LoggedDemoLiveSession.__qualname__,
    ]
    assert record["session_id"] == 123
    assert record["participant_id"] == 7
    assert record["trigger_event_type"] == "loggedState"
    assert record["message_time"] == message_time
    assert record["values"] == {
        "counter": 3,
        "details": {"secret": True},
        "private_value": "hidden",
        "public_value": "shown",
    }
    assert live_session.snapshot_state() == {"public_value": "shown"}
    assert "group_type" not in record


def test_session_decorator_logging_queues_after_commit(
    fake_state_log_redis, monkeypatch
):
    """State logs are queued only after the write transaction commits."""

    order = []
    message_time = datetime(2026, 1, 1, 12, 0, 0)
    participant = SimpleNamespace(id=7)
    live_session = LoggedDemoLiveSession(counter=2)
    live_session.id = 123

    def get_current_for_participant(cls, participant_arg, session_id, *, for_update):
        assert participant_arg is participant
        assert session_id == 123
        assert for_update is True
        return live_session

    fake_state_log_redis.on_rpush = lambda: order.append("queue")
    monkeypatch.setattr(
        LoggedDemoLiveSession,
        "get_current_for_participant",
        classmethod(get_current_for_participant),
    )
    monkeypatch.setattr(
        "psynet.session.db.session.commit", lambda: order.append("commit")
    )

    result = LoggedStateMessage(session_id=123).handle(
        experiment=SimpleNamespace(),
        participant=participant,
        receive_time=message_time,
    )

    assert result == 123
    assert order == ["commit", "queue"]
    assert _saved_state_log_records(fake_state_log_redis) == [
        {
            "table_name": LIVE_SESSION_STATE_LOG_TABLE,
            "session_class": [
                LoggedDemoLiveSession.__module__,
                LoggedDemoLiveSession.__qualname__,
            ],
            "session_id": 123,
            "participant_id": 7,
            "trigger_event_type": "loggedState",
            "message_time": message_time,
            "log_time": _saved_state_log_records(fake_state_log_redis)[0]["log_time"],
            "values": {
                "counter": 3,
                "details": {"counter": 3},
                "private_value": "hidden",
                "public_value": "shown",
            },
        }
    ]


def test_session_decorator_logging_skips_missing_session(
    fake_state_log_redis, monkeypatch
):
    """Invalid live-session messages do not commit or queue logs."""

    commit = MagicMock()
    monkeypatch.setattr(
        LoggedDemoLiveSession,
        "get_current_for_participant",
        classmethod(lambda cls, *args, **kwargs: None),
    )
    monkeypatch.setattr("psynet.session.db.session.commit", commit)

    result = LoggedStateMessage(session_id=123).handle(
        experiment=SimpleNamespace(),
        participant=SimpleNamespace(id=7),
        receive_time=None,
    )

    assert result is None
    commit.assert_not_called()
    assert _saved_state_log_records(fake_state_log_redis) == []


def test_session_decorator_logging_skips_failed_handler(
    fake_state_log_redis, monkeypatch
):
    """Failed mutating handlers roll back and do not queue state logs."""

    live_session = LoggedDemoLiveSession(counter=2)
    live_session.id = 123
    rollbacks = []
    monkeypatch.setattr(
        LoggedDemoLiveSession,
        "get_current_for_participant",
        classmethod(lambda cls, *args, **kwargs: live_session),
    )
    monkeypatch.setattr(
        "psynet.session.db.session.rollback", lambda: rollbacks.append(True)
    )

    with pytest.raises(RuntimeError, match="state update failed"):
        FailingLoggedStateMessage(session_id=123).handle(
            experiment=SimpleNamespace(),
            participant=SimpleNamespace(id=7),
            receive_time=None,
        )

    assert rollbacks == [True]
    assert _saved_state_log_records(fake_state_log_redis) == []


def test_session_decorator_logging_skips_failed_commit(
    fake_state_log_redis, monkeypatch
):
    """State logs are not queued when the commit itself fails."""

    live_session = LoggedDemoLiveSession(counter=2)
    live_session.id = 123
    rollbacks = []
    monkeypatch.setattr(
        LoggedDemoLiveSession,
        "get_current_for_participant",
        classmethod(lambda cls, *args, **kwargs: live_session),
    )

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr("psynet.session.db.session.commit", fail_commit)
    monkeypatch.setattr(
        "psynet.session.db.session.rollback", lambda: rollbacks.append(True)
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        LoggedStateMessage(session_id=123).handle(
            experiment=SimpleNamespace(),
            participant=SimpleNamespace(id=7),
            receive_time=None,
        )

    assert rollbacks == [True]
    assert _saved_state_log_records(fake_state_log_redis) == []


def test_session_logging_requires_mutation():
    """State logging is only valid for mutating handlers."""

    with pytest.raises(TypeError, match="requires mutate=True"):
        session_context(logging=True)


def test_live_session_state_log_queue_drains_to_database(
    fake_state_log_redis, monkeypatch
):
    """Queued state log records are converted to ORM rows in batches."""

    live_session = LoggedDemoLiveSession(
        public_value="shown",
        private_value="hidden",
        counter=3,
        details={"secret": True},
    )
    live_session.id = 123
    enqueue_live_session_state_log_record(
        _make_live_session_state_log_record(
            live_session=live_session,
            participant=SimpleNamespace(id=7),
            trigger_event_type="loggedState",
            message_time=datetime(2026, 1, 1, 12, 0, 0),
        )
    )
    added_events = []
    commits = []

    monkeypatch.setattr("psynet.session.db.session.add_all", added_events.extend)
    monkeypatch.setattr(
        "psynet.session.db.session.commit", lambda: commits.append(True)
    )
    monkeypatch.setattr("psynet.session.db.session.rollback", lambda: None)

    assert drain_live_session_state_log_queue_once() == 1
    assert commits == [True]
    assert len(added_events) == 1
    event = added_events[0]
    assert isinstance(event, get_live_session_state_log_model(LoggedDemoLiveSession))
    assert event.session_id == 123
    assert event.participant_id == 7
    assert event.trigger_event_type == "loggedState"
    assert event.public_value == "shown"
    assert event.private_value == "hidden"
    assert event.counter == 3
    assert event.details == {"secret": True}


def test_live_session_state_log_queue_requeues_on_database_failure(
    fake_state_log_redis, monkeypatch
):
    """Valid state log payloads are requeued when batch persistence fails."""

    live_session = LoggedDemoLiveSession(public_value="shown")
    live_session.id = 123
    enqueue_live_session_state_log_record(
        _make_live_session_state_log_record(
            live_session=live_session,
            participant=SimpleNamespace(id=7),
            trigger_event_type="loggedState",
            message_time=None,
        )
    )
    rollbacks = []

    def fail_commit():
        raise RuntimeError("database down")

    monkeypatch.setattr("psynet.session.db.session.add_all", lambda events: None)
    monkeypatch.setattr("psynet.session.db.session.commit", fail_commit)
    monkeypatch.setattr(
        "psynet.session.db.session.rollback", lambda: rollbacks.append(True)
    )

    assert drain_live_session_state_log_queue_once() == 0
    assert rollbacks == [True]
    assert len(_saved_state_log_records(fake_state_log_redis)) == 1


def test_create_for_group_is_leader_owned(monkeypatch):
    """The initializer creates exactly one session from the group leader context."""

    added = MagicMock()
    monkeypatch.setattr("psynet.session.db.session.add", added)
    monkeypatch.setattr("psynet.session.db.session.flush", MagicMock())
    group = _group()
    initializer = SimpleNamespace(id="demo_session")

    live_session = PolymorphicDemoLiveSession.create_for_group(
        group=group,
        initializer=initializer,
        participant=group.leader,
    )

    assert live_session.session_type == "polymorphic_demo_live_session"
    assert live_session.group_type == "demo_group"
    assert live_session.sync_group_id == 9
    assert live_session.initializer_id == "demo_session"
    assert live_session.node_id == 11
    assert live_session.network_id == 12
    assert live_session.participant_ids == [1, 2]
    assert live_session.start_time is None
    assert live_session.end_time is None
    assert live_session.snapshot_state() == {
        "initial_participant_ids": [1, 2],
        "initial_node_id": 11,
    }
    added.assert_called_once_with(live_session)


def test_create_for_group_rejects_non_leader(monkeypatch):
    """Only the group leader may create the live session."""

    group = _group()
    initializer = SimpleNamespace(id="demo_session")

    with pytest.raises(ValueError, match="Only the group leader"):
        PolymorphicDemoLiveSession.create_for_group(
            group=group,
            initializer=initializer,
            participant=group.active_participants[1],
        )


def test_current_trial_details_are_optional():
    """Group-level sessions can initialize without node/network context."""

    group = _group(leader_trial=False)

    assert PolymorphicDemoLiveSession._current_trial_details(group) == (
        None,
        None,
    )


def test_live_session_initializer_delegates_creation_to_leader(monkeypatch):
    """The initializer's barrier callback delegates creation to the session class."""

    group = _group()
    created = MagicMock()
    monkeypatch.setattr(PolymorphicDemoLiveSession, "create_for_group", created)
    initializer = LiveSessionInitializer(
        id_="demo_session",
        group_type="demo_group",
        session_class=PolymorphicDemoLiveSession,
    )

    initializer.on_release(
        group=group,
        participants=group.active_participants,
        participant=group.leader,
        barrier=initializer,
    )

    created.assert_called_once_with(
        group=group,
        initializer=initializer,
        participant=group.leader,
    )


def test_live_session_control_derives_config(monkeypatch):
    """LiveSessionControl derives transport config from participant and group."""

    live_session = None
    get_for_group_calls = []

    def get_for_group(cls, **kwargs):
        get_for_group_calls.append(kwargs)
        return live_session

    monkeypatch.setattr(
        PolymorphicDemoLiveSession, "get_for_group", classmethod(get_for_group)
    )

    class DemoControl(LiveSessionControl):
        macro = "demo"

        def __init__(self, participant):
            self.custom_value = 10
            super().__init__(
                participant=participant,
                session_class=PolymorphicDemoLiveSession,
                group_type="demo_group",
                session_initializer_id="demo_session",
            )

    group = _group()
    participant = group.active_participants[0]

    control = DemoControl(participant)
    assert get_for_group_calls == []

    events = {}
    control.update_events(events)
    assert events["liveSessionInit"]["js"] is None
    control.page = SimpleNamespace(events=events)

    live_session = SimpleNamespace(
        id=5,
        sync_group_id=9,
        participant_ids=[1, 2],
        node_id=11,
        network_id=12,
    )
    control.pre_render()

    assert control.custom_value == 10
    assert not hasattr(control, "session")
    assert events["liveSessionInit"]["js"] == (
        'psynet.session.init({"session_id": 5, "participant_id": 1});'
    )
    assert get_for_group_calls == [
        {
            "group": group,
            "initializer_id": "demo_session",
            "node_id": 11,
            "network_id": 12,
        }
    ]


def test_live_session_control_requires_existing_session(monkeypatch):
    """Controls fail clearly at render time if no initializer row exists."""

    monkeypatch.setattr(
        PolymorphicDemoLiveSession,
        "get_for_group",
        classmethod(lambda cls, **kwargs: None),
    )

    class DemoControl(LiveSessionControl):
        def __init__(self, participant):
            super().__init__(
                participant=participant,
                session_class=PolymorphicDemoLiveSession,
                group_type="demo_group",
                session_initializer_id="missing_session",
            )

    control = DemoControl(participant=_group().active_participants[0])

    with pytest.raises(RuntimeError, match="No live session prepared"):
        control.pre_render()


def test_trigger_session_end_event_marks_ended_and_notifies(monkeypatch):
    """SessionEnd can be triggered from a session class and row ID."""

    state = _state()
    sent = _capture_server_sends(monkeypatch)

    monkeypatch.setattr("psynet.db.transaction", lambda: MagicMock())
    monkeypatch.setattr(LiveSession, "get", classmethod(lambda *args, **kwargs: state))

    LiveSession.trigger_end_event(1)

    assert state.ended is True
    assert sent == [
        (
            participant,
            SessionEndMessage(**state.snapshot_payload(participant=participant)),
        )
        for participant in state.participants
    ]


def test_live_session_uses_shared_polymorphic_table():
    """Custom live-session classes share the generic live_session table."""

    assert LiveSession.__tablename__ == "live_session"
    assert PolymorphicDemoLiveSession.__table__ is LiveSession.__table__
    assert "state" not in LiveSession.__table__.columns
    assert "vars" in LiveSession.__table__.columns
    assert "custom_value" in LiveSession.__table__.columns
    assert "score" in LiveSession.__table__.columns
    assert "session_id" not in LiveSession.__table__.columns
    assert "session_type" in LiveSession.__table__.columns
    assert "node_id" in LiveSession.__table__.columns
    assert "network_id" in LiveSession.__table__.columns


def test_live_session_column_reuses_existing_table_column():
    """Reusable live-session columns tolerate experiment module re-imports."""

    assert (
        ReusedColumnDemoLiveSessionA.__table__.c.reusable_value
        is ReusedColumnDemoLiveSessionB.__table__.c.reusable_value
    )


def test_base_live_session_can_snapshot_generic_var_store():
    """The base class remains usable via the generic PsyNet var store."""

    assert "state" not in LiveSession.__table__.columns

    state = LiveSession(
        vars={"score": 3, "round": 2},
        participant_ids=[1],
        ready_participant_ids=[],
        started=False,
        ended=False,
    )
    state.id = 1

    assert LiveSession().initialize([], None) is None
    assert state.snapshot_payload(fields=["score", "missing"])["state"] == {"score": 3}

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from dallinger import db

from psynet.chatroom import ChatMessage, ChatRoomMember, EnableChatrooms
from psynet.experiment import get_experiment
from psynet.participant import Participant
from psynet.pytest_psynet import path_to_test_experiment


def _random_id():
    return str(uuid.uuid4())


def _new_participant(experiment):
    participant = Participant(
        experiment=experiment,
        recruiter_id="hotair",
        worker_id=_random_id(),
        hit_id="XYZ",
        assignment_id=_random_id(),
        mode="debug",
    )
    db.session.add(participant)
    return participant


def _mock_experiment():
    """Return a minimal mock that records publish_to_subscribers calls."""
    exp = MagicMock()
    exp.publish_to_subscribers = MagicMock()
    return exp


def _published_payloads(mock_exp):
    """Return all JSON payloads passed to publish_to_subscribers."""
    return [
        json.loads(call_args[0][0])
        for call_args in mock_exp.publish_to_subscribers.call_args_list
    ]


class TestEnableChatroomsConfig:
    def test_consume_is_noop(self):
        """consume() must exist and return None (transparent timeline element)."""
        handler = EnableChatrooms()
        assert handler.consume(None, None) is None


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("consents")],
    indirect=True,
)
class TestHandleMessage:
    """
    Tests for EnableChatrooms.handle_message()
    """

    @staticmethod
    def _handler_and_exp():
        return EnableChatrooms(), _mock_experiment()

    @staticmethod
    def _send(handler, exp, participant, payload, node=None):
        time = datetime.now(UTC)
        handler.handle_message(
            json.dumps(payload),
            handler.channel,
            participant,
            node,
            time,
            exp,
        )
        return time

    # -- missing room_id --

    def test_message_without_room_id_is_ignored(
        self, in_experiment_directory, db_session
    ):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(handler, exp, participant, {"type": "join_room"})  # no room_id
        db.session.commit()

        exp.publish_to_subscribers.assert_not_called()

    # -- join_room --

    def test_join_room_creates_member_record(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()

        record = ChatRoomMember.query.filter_by(
            participant_id=participant.id, room_id="room_A"
        ).one()
        assert record.active is True
        assert record.join_time is not None

    def test_join_room_broadcasts_occupancy(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()

        exp.publish_to_subscribers.assert_called_once()
        payload = _published_payloads(exp)[0]
        assert payload["type"] == "occupancy_update"
        assert payload["room_id"] == "room_A"

    def test_rejoin_room_rebroadcasts(self, in_experiment_directory, db_session):
        """Joining a room a second time still broadcasts (so the participant list is refreshed)."""
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()
        exp.publish_to_subscribers.reset_mock()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()

        exp.publish_to_subscribers.assert_called_once()

    def test_rejoin_room_closes_prior_session(
        self, in_experiment_directory, db_session
    ):
        """Re-joining a room creates a new record and closes the previous one."""
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()

        records = (
            ChatRoomMember.query.filter_by(
                participant_id=participant.id, room_id="room_A"
            )
            .order_by(ChatRoomMember.id)
            .all()
        )
        assert len(records) == 2
        assert records[0].active is False
        assert records[0].leave_time is not None
        assert records[1].active is True

    def test_join_multiple_rooms_simultaneously(
        self, in_experiment_directory, db_session
    ):
        """A participant can be active in more than one room at the same time."""
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_B"}
        )
        db.session.commit()

        active = ChatRoomMember.query.filter_by(
            participant_id=participant.id, active=True
        ).all()
        active_rooms = {r.room_id for r in active}
        assert "room_A" in active_rooms
        assert "room_B" in active_rooms

    # -- leave_room --

    def test_leave_room_deactivates_member_record(
        self, in_experiment_directory, db_session
    ):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_B"}
        )
        db.session.commit()
        exp.publish_to_subscribers.reset_mock()

        self._send(
            handler, exp, participant, {"type": "leave_room", "room_id": "room_B"}
        )
        db.session.commit()

        record = ChatRoomMember.query.filter_by(
            participant_id=participant.id, room_id="room_B"
        ).one()
        assert record.active is False
        assert record.leave_time is not None

    def test_leave_room_broadcasts_occupancy(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_B"}
        )
        db.session.commit()
        exp.publish_to_subscribers.reset_mock()

        self._send(
            handler, exp, participant, {"type": "leave_room", "room_id": "room_B"}
        )
        db.session.commit()

        exp.publish_to_subscribers.assert_called_once()
        payload = _published_payloads(exp)[0]
        assert payload["type"] == "occupancy_update"
        assert payload["room_id"] == "room_B"

    def test_leave_room_does_not_affect_other_rooms(
        self, in_experiment_directory, db_session
    ):
        """Leaving one room leaves other room memberships intact."""
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_B"}
        )
        db.session.commit()

        self._send(
            handler, exp, participant, {"type": "leave_room", "room_id": "room_B"}
        )
        db.session.commit()

        record_a = ChatRoomMember.query.filter_by(
            participant_id=participant.id, room_id="room_A", active=True
        ).one_or_none()
        assert record_a is not None

    def test_join_room_null_participant_does_not_broadcast(
        self, in_experiment_directory, db_session
    ):
        """join_room with participant=None skips DB writes and broadcasts."""
        handler, exp = self._handler_and_exp()
        db.session.flush()

        handler.handle_message(
            json.dumps({"type": "join_room", "room_id": "room_G"}),
            handler.channel,
            None,
            None,
            datetime.now(UTC),
            exp,
        )
        db.session.commit()

        exp.publish_to_subscribers.assert_not_called()

    def test_leave_room_null_participant_does_not_broadcast(
        self, in_experiment_directory, db_session
    ):
        """leave_room with participant=None skips DB writes and broadcasts."""
        handler, exp = self._handler_and_exp()
        db.session.flush()

        handler.handle_message(
            json.dumps({"type": "leave_room", "room_id": "room_H"}),
            handler.channel,
            None,
            None,
            datetime.now(UTC),
            exp,
        )
        db.session.commit()

        exp.publish_to_subscribers.assert_not_called()

    # -- message --

    def test_message_persisted_to_db(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        send_time = self._send(
            handler,
            exp,
            participant,
            {"type": "message", "room_id": "room_C", "content": "hello"},
        )
        db.session.commit()

        records = ChatMessage.query.filter_by(room_id="room_C").all()
        assert len(records) == 1
        record = records[0]
        assert record.content == "hello"
        assert record.participant_id == participant.id
        assert record.receive_time == send_time

    def test_message_publishes_untargeted_history(
        self, in_experiment_directory, db_session
    ):
        """Persisting a line republishes the room log so late joiners catch up."""
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler,
            exp,
            participant,
            {"type": "message", "room_id": "room_C", "content": "hello"},
        )

        payloads = _published_payloads(exp)
        assert len(payloads) == 1
        history = payloads[0]
        assert history["type"] == "history"
        assert history["room_id"] == "room_C"
        assert "target_participant_id" not in history
        assert history["messages"] == [
            {"content": "hello", "sender": str(participant.id)}
        ]

    def test_request_state_sends_history(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        # Pre-seed a message
        db.session.add(
            ChatMessage(
                participant_id=participant.id,
                node_id=None,
                room_id="room_E",
                content="prior message",
                receive_time=datetime.now(UTC),
            )
        )
        db.session.commit()
        exp.publish_to_subscribers.reset_mock()

        self._send(
            handler, exp, participant, {"type": "request_state", "room_id": "room_E"}
        )

        payloads = _published_payloads(exp)
        types = {p["type"] for p in payloads}
        assert "occupancy_update" in types
        assert "history" in types

        history = next(p for p in payloads if p["type"] == "history")
        assert history["room_id"] == "room_E"
        assert history["target_participant_id"] == str(participant.id)
        assert len(history["messages"]) == 1
        assert history["messages"][0]["content"] == "prior message"

    def test_request_state_empty_history(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()

        self._send(
            handler, exp, participant, {"type": "request_state", "room_id": "room_F"}
        )

        history = next(p for p in _published_payloads(exp) if p["type"] == "history")
        assert history["messages"] == []


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("consents")],
    indirect=True,
)
class TestOccupantIds:
    def test_returns_subscribed_participants_for_room(
        self, in_experiment_directory, db_session
    ):
        handler = EnableChatrooms()
        experiment = get_experiment()

        p1 = _new_participant(experiment)
        p2 = _new_participant(experiment)
        p3 = _new_participant(experiment)
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add(
            ChatRoomMember(
                participant_id=p1.id, room_id="room_X", active=True, join_time=now
            )
        )
        db.session.add(
            ChatRoomMember(
                participant_id=p2.id, room_id="room_Y", active=True, join_time=now
            )
        )
        # p3 is not subscribed
        db.session.commit()

        ids_X = handler._occupant_ids("room_X")
        assert str(p1.id) in ids_X
        assert str(p2.id) not in ids_X
        assert str(p3.id) not in ids_X

        ids_Y = handler._occupant_ids("room_Y")
        assert str(p2.id) in ids_Y
        assert str(p1.id) not in ids_Y

    def test_excludes_inactive_participants(self, in_experiment_directory, db_session):
        """Participants with active=False are not returned."""
        handler = EnableChatrooms()
        experiment = get_experiment()
        p = _new_participant(experiment)
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add(
            ChatRoomMember(
                participant_id=p.id,
                room_id="room_Z",
                active=False,
                join_time=now,
                leave_time=now,
            )
        )
        db.session.commit()

        assert handler._occupant_ids("room_Z") == []

    def test_excludes_failed_participants(self, in_experiment_directory, db_session):
        """Participants marked failed are excluded even if their record is active."""
        handler = EnableChatrooms()
        experiment = get_experiment()
        p = _new_participant(experiment)
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add(
            ChatRoomMember(
                participant_id=p.id, room_id="room_Z2", active=True, join_time=now
            )
        )
        p.failed = True
        db.session.commit()

        assert handler._occupant_ids("room_Z2") == []

    def test_deduplicates_participant_with_multiple_active_records(
        self, in_experiment_directory, db_session
    ):
        """A participant appearing in two active records is returned only once."""
        handler = EnableChatrooms()
        experiment = get_experiment()
        p = _new_participant(experiment)
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add(
            ChatRoomMember(
                participant_id=p.id, room_id="room_Z3", active=True, join_time=now
            )
        )
        db.session.add(
            ChatRoomMember(
                participant_id=p.id, room_id="room_Z3", active=True, join_time=now
            )
        )
        db.session.commit()

        ids = handler._occupant_ids("room_Z3")
        assert ids.count(str(p.id)) == 1

    def test_returns_empty_when_no_subscribers(
        self, in_experiment_directory, db_session
    ):
        handler = EnableChatrooms()
        experiment = get_experiment()
        _new_participant(experiment)
        db.session.flush()
        db.session.commit()

        assert handler._occupant_ids("room_empty") == []

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from dallinger import db

from psynet.chatroom import ChatMessage, ChatRoom, ChatRoomMember, EnableChatrooms
from psynet.experiment import get_experiment
from psynet.modular_page import ModularPage
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
    participant.page_uuid = _random_id()
    db.session.add(participant)
    return participant


def _mock_experiment():
    """Return a minimal mock that records publish_to_participants calls."""
    return MagicMock()


def _published_payloads(mock_exp):
    """Return all payloads passed to publish_to_participants."""
    return [c.args[0] for c in mock_exp.publish_to_participants.call_args_list]


def _recipients(mock_exp):
    """Return the recipients of each publish_to_participants call, as sets of strings."""
    return [
        {str(i) for i in c.args[1]}
        for c in mock_exp.publish_to_participants.call_args_list
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
    def _send(
        handler, exp, participant, payload, node=None, page_room=None, names="shown"
    ):
        """Send ``payload``; a join comes from a page showing ``page_room``, by default the joined room."""
        if payload.get("type") == "join_room":
            room = page_room if page_room is not None else payload.get("room_id")
            exp.timeline.get_current_elt.return_value = SimpleNamespace(
                chatroom=ChatRoom(room_id=room, names=names)
            )
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

        exp.publish_to_participants.assert_not_called()

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
        room = _random_id()

        self._send(handler, exp, participant, {"type": "join_room", "room_id": room})
        db.session.commit()

        exp.publish_to_participants.assert_called_once()
        payload = _published_payloads(exp)[0]
        assert payload["type"] == "occupancy_update"
        assert payload["room_id"] == room
        assert payload["pseudonyms"] == {
            str(participant.id): participant.pseudonym.to_dict()
        }
        assert _recipients(exp) == [{str(participant.id)}]

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
        exp.publish_to_participants.reset_mock()

        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_A"}
        )
        db.session.commit()

        exp.publish_to_participants.assert_called_once()

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
        exp.publish_to_participants.reset_mock()

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
        exp.publish_to_participants.reset_mock()

        self._send(
            handler, exp, participant, {"type": "leave_room", "room_id": "room_B"}
        )
        db.session.commit()

        exp.publish_to_participants.assert_called_once()
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

        exp.publish_to_participants.assert_not_called()

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

        exp.publish_to_participants.assert_not_called()

    # -- message --

    def test_message_persisted_to_db(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()
        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_C"}
        )

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

    def test_message_is_sent_to_room_members_only(
        self, in_experiment_directory, db_session
    ):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        sender, member, outsider = (_new_participant(experiment) for _ in range(3))
        db.session.flush()
        room, other_room = _random_id(), _random_id()
        for participant, joined in [
            (sender, room),
            (member, room),
            (outsider, other_room),
        ]:
            self._send(
                handler, exp, participant, {"type": "join_room", "room_id": joined}
            )
        exp.publish_to_participants.reset_mock()

        self._send(
            handler, exp, sender, {"type": "message", "room_id": room, "content": "hi"}
        )

        assert _published_payloads(exp) == [
            {
                "type": "message",
                "room_id": room,
                "content": "hi",
                "sender": str(sender.id),
                "sender_pseudonym": sender.pseudonym.to_dict(),
            }
        ]
        assert _recipients(exp) == [{str(sender.id), str(member.id)}]

    def test_anonymous_pages_are_not_sent_pseudonyms(
        self, in_experiment_directory, db_session
    ):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        hidden, named = _new_participant(experiment), _new_participant(experiment)
        db.session.flush()
        room = _random_id()
        join = {"type": "join_room", "room_id": room}
        self._send(handler, exp, hidden, join, names="anonymous")
        self._send(handler, exp, named, join)
        exp.publish_to_participants.reset_mock()

        self._send(
            handler, exp, named, {"type": "message", "room_id": room, "content": "hi"}
        )
        self._send(handler, exp, hidden, {"type": "request_state", "room_id": room})

        to_named, to_hidden, history = _published_payloads(exp)
        assert _recipients(exp) == [{str(named.id)}, {str(hidden.id)}, {str(hidden.id)}]
        assert to_named["sender_pseudonym"] == named.pseudonym.to_dict()
        assert to_hidden["sender_pseudonym"] is None
        assert history["messages"][0]["sender_pseudonym"] is None
        # Nor their IDs: others appear under per-room aliases.
        assert to_named["sender"] == str(named.id)
        assert to_hidden["sender"] == history["messages"][0]["sender"] == "member-2"
        exp.publish_to_participants.reset_mock()
        self._send(handler, exp, hidden, join, names="anonymous")
        occupancy = {
            str(ids): payload["participants"]
            for payload, ids in zip(_published_payloads(exp), _recipients(exp))
        }
        assert set(occupancy[str({str(hidden.id)})]) == {str(hidden.id), "member-2"}
        assert set(occupancy[str({str(named.id)})]) == {str(hidden.id), str(named.id)}
        exp.publish_to_participants.reset_mock()
        self._send(
            handler, exp, hidden, {"type": "message", "room_id": room, "content": "yo"}
        )
        assert [p["sender"] for p in _published_payloads(exp)] == [str(hidden.id)] * 2
        with pytest.raises(RuntimeError, match="EnableChatrooms"):
            ModularPage("chat", "Hi", chatroom=ChatRoom(room_id=room)).render(
                experiment, hidden
            )
        config = ChatRoom(room_id=room, names="anonymous").get_js_vars()
        assert config["chatroom_config"]["names"] == "anonymous"
        assert config["chatroom_config"]["partner_label"] == "Your partner"
        assert config["chatroom_config"]["other_label"] == "Another player"
        with pytest.raises(ValueError, match="hover"):
            ChatRoom(room_id=room, names="on_hover")

    def test_a_room_the_page_does_not_show_cannot_be_joined(
        self, in_experiment_directory, db_session
    ):
        handler, exp = self._handler_and_exp()
        participant = _new_participant(get_experiment())
        db.session.flush()
        room = _random_id()

        self._send(
            handler,
            exp,
            participant,
            {"type": "join_room", "room_id": room},
            page_room="my-own-room",
        )

        exp.publish_to_participants.assert_not_called()
        assert ChatRoomMember.query.filter_by(room_id=room).count() == 0

    def test_a_participant_who_moved_to_another_page_has_left_the_room(
        self, in_experiment_directory, db_session
    ):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        mover, stayer = _new_participant(experiment), _new_participant(experiment)
        db.session.flush()
        room = _random_id()
        for p in (mover, stayer):
            self._send(handler, exp, p, {"type": "join_room", "room_id": room})
        mover.page_uuid = _random_id()
        exp.reset_mock()

        for msg_type in ("message", "request_state"):
            self._send(
                handler, exp, mover, {"type": msg_type, "room_id": room, "content": "x"}
            )
        exp.publish_to_participants.assert_not_called()

        self._send(
            handler, exp, stayer, {"type": "message", "room_id": room, "content": "y"}
        )
        assert _recipients(exp) == [{str(stayer.id)}]

    @pytest.mark.parametrize("msg_type", ["message", "request_state"])
    def test_a_non_member_is_ignored(
        self, in_experiment_directory, db_session, msg_type
    ):
        handler, exp = self._handler_and_exp()
        participant = _new_participant(get_experiment())
        db.session.flush()
        room = _random_id()

        self._send(
            handler,
            exp,
            participant,
            {"type": msg_type, "room_id": room, "content": "x"},
        )

        exp.publish_to_participants.assert_not_called()
        assert ChatMessage.query.filter_by(room_id=room).count() == 0

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
        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_E"}
        )
        db.session.commit()
        exp.publish_to_participants.reset_mock()

        self._send(
            handler, exp, participant, {"type": "request_state", "room_id": "room_E"}
        )

        (history,) = _published_payloads(exp)
        assert history["type"] == "history"
        assert history["room_id"] == "room_E"
        assert _recipients(exp) == [{str(participant.id)}]
        assert len(history["messages"]) == 1
        assert history["messages"][0]["content"] == "prior message"
        assert history["messages"][0]["sender_pseudonym"]["name"] == (
            participant.pseudonym.name
        )

    def test_request_state_empty_history(self, in_experiment_directory, db_session):
        handler, exp = self._handler_and_exp()
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.flush()
        self._send(
            handler, exp, participant, {"type": "join_room", "room_id": "room_F"}
        )

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
                participant_id=p1.id,
                page_uuid=p1.page_uuid,
                room_id="room_X",
                active=True,
                join_time=now,
            )
        )
        db.session.add(
            ChatRoomMember(
                participant_id=p2.id,
                page_uuid=p2.page_uuid,
                room_id="room_Y",
                active=True,
                join_time=now,
            )
        )
        # p3 is not subscribed
        db.session.commit()

        ids_X = list(handler._occupants("room_X"))
        assert str(p1.id) in ids_X
        assert str(p2.id) not in ids_X
        assert str(p3.id) not in ids_X

        ids_Y = list(handler._occupants("room_Y"))
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
                page_uuid=p.page_uuid,
                room_id="room_Z",
                active=False,
                join_time=now,
                leave_time=now,
            )
        )
        db.session.commit()

        assert list(handler._occupants("room_Z")) == []

    def test_excludes_failed_participants(self, in_experiment_directory, db_session):
        """Participants marked failed are excluded even if their record is active."""
        handler = EnableChatrooms()
        experiment = get_experiment()
        p = _new_participant(experiment)
        db.session.flush()

        now = datetime.now(UTC)
        db.session.add(
            ChatRoomMember(
                participant_id=p.id,
                page_uuid=p.page_uuid,
                room_id="room_Z2",
                active=True,
                join_time=now,
            )
        )
        p.failed = True
        db.session.commit()

        assert list(handler._occupants("room_Z2")) == []

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
                participant_id=p.id,
                page_uuid=p.page_uuid,
                room_id="room_Z3",
                active=True,
                join_time=now,
            )
        )
        db.session.add(
            ChatRoomMember(
                participant_id=p.id,
                page_uuid=p.page_uuid,
                room_id="room_Z3",
                active=True,
                join_time=now,
            )
        )
        db.session.commit()

        ids = list(handler._occupants("room_Z3"))
        assert ids.count(str(p.id)) == 1

    def test_returns_empty_when_no_subscribers(
        self, in_experiment_directory, db_session
    ):
        handler = EnableChatrooms()
        experiment = get_experiment()
        _new_participant(experiment)
        db.session.flush()
        db.session.commit()

        assert list(handler._occupants("room_empty")) == []


@pytest.mark.parametrize(
    "experiment_directory",
    [path_to_test_experiment("consents")],
    indirect=True,
)
class TestCheckedConnections:
    class Recorder(EnableChatrooms):
        def handle_message(self, message, **kwargs):
            self.senders.append(kwargs["participant"])

    def test_only_the_participants_own_token_is_accepted(
        self, in_experiment_directory, db_session
    ):
        experiment = get_experiment()
        participant, other = _new_participant(experiment), _new_participant(experiment)
        db.session.commit()
        accept = experiment.accept_websocket_connection

        assert accept(str(participant.id), participant.websocket_scope)
        assert not accept(str(participant.id), other.websocket_scope)
        assert not accept(str(participant.id), participant.unique_id)
        assert not accept(str(participant.id), None)
        assert not accept(str(participant.id), "é")

    def test_a_token_can_be_followed_by_a_name_for_the_connection(
        self, in_experiment_directory, db_session
    ):
        experiment = get_experiment()
        participant, other = _new_participant(experiment), _new_participant(experiment)
        db.session.commit()
        accept = experiment.accept_websocket_connection
        token = participant.websocket_scope

        assert accept(str(participant.id), token + ".k3x9load.2")
        assert accept(str(participant.id), token + "." + "a" * 64)
        for name in ("", "a" * 65, "tab-1", "tab 1", "é", "tab\n"):
            assert not accept(str(participant.id), token + "." + name), name
        assert not accept(str(participant.id), token + "tab1")
        assert not accept(str(participant.id), other.websocket_scope + ".tab1")

    def test_chat_handlers_only_take_checked_messages(
        self, in_experiment_directory, db_session, monkeypatch
    ):
        experiment = get_experiment()
        participant = _new_participant(experiment)
        db.session.commit()
        recorder = self.Recorder()
        recorder.senders = []
        monkeypatch.setattr(
            experiment,
            "_websocket_message_handlers",
            {recorder.channel: [recorder.handle_message]},
        )
        message = json.dumps({"type": "message", "room_id": "r"})

        experiment.receive_message(
            message, channel_name=recorder.channel, participant=participant
        )
        experiment.handle_websocket_message(
            message,
            channel_name=recorder.channel,
            participant_id=str(participant.id),
            receive_time=datetime.now(UTC),
        )

        assert recorder.senders == [participant]

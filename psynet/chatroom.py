import json

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from .data import SQLBase, SQLMixin, register_table
from .javascript_hooks import JavaScriptContributor
from .static_resources import package_static_url
from .timeline import NullElt, WebSocketElt


@register_table
class ChatMessage(SQLBase, SQLMixin):
    """Stores a single chat message sent during a :class:`ModularPage` chatroom."""

    __tablename__ = "chat_message"

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("node.id"), index=True)
    participant_id = Column(
        Integer, ForeignKey("participant.id"), index=True, nullable=True
    )
    room_id = Column(String(128), index=True)
    content = Column(Text)
    receive_time = Column(DateTime(timezone=True))


@register_table
class ChatRoomMember(SQLBase, SQLMixin):
    """Tracks room membership sessions for participants.

    A new record is created each time a participant joins a room, so there may
    be multiple records per (participant_id, room_id) pair.  ``active=True``
    indicates the participant is currently in the room; ``leave_time`` is set
    when they leave.
    """

    __tablename__ = "chat_room_member"

    id = Column(Integer, primary_key=True)
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    room_id = Column(String(128), index=True)
    active = Column(Boolean, default=True, index=True)
    join_time = Column(DateTime(timezone=True))
    leave_time = Column(DateTime(timezone=True), nullable=True)


class EnableChatrooms(NullElt, WebSocketElt):
    """
    Timeline element that activates the chatroom WebSocket channel.

    Place this directly in the experiment timeline whenever any
    :class:`~psynet.modular_page.ModularPage` in the experiment may use a
    :class:`ChatRoom` component::

        class MyExperiment(Experiment):
            timeline = Timeline(
                EnableChatrooms(),
                TrialMaker(id_="trials", trial_class=MyTrial, ...),
            )

    This is a NullElt, invisible to participants.

    """

    channel = "modular_page_chat"

    def handle_message(
        self, message, channel_name, participant, node, receive_time, experiment
    ):
        from dallinger import db

        data = json.loads(message)
        room_id = data.get("room_id")
        if room_id is None:
            return

        msg_type = data.get("type")

        if msg_type == "join_room":
            if participant is not None:
                # Close any active session for this participant in this room,
                # then open a new one.  This handles reconnects cleanly and
                # preserves a full join/leave history per room.
                ChatRoomMember.query.filter_by(
                    participant_id=participant.id,
                    room_id=room_id,
                    active=True,
                ).update({"active": False, "leave_time": receive_time})
                db.session.add(
                    ChatRoomMember(
                        participant_id=participant.id,
                        room_id=room_id,
                        active=True,
                        join_time=receive_time,
                    )
                )
                db.session.commit()
                self._broadcast_occupancy(experiment, room_id)

        elif msg_type == "request_state":
            # Sent once on initial connection; sends back history and
            # current room occupancy.
            self._broadcast_occupancy(experiment, room_id)
            if participant is not None:
                self._send_history(experiment, participant, room_id)

        elif msg_type == "leave_room":
            if participant is not None:
                ChatRoomMember.query.filter_by(
                    participant_id=participant.id,
                    room_id=room_id,
                    active=True,
                ).update({"active": False, "leave_time": receive_time})
                db.session.commit()
                self._broadcast_occupancy(experiment, room_id)

        elif msg_type == "message":
            current_node = participant.current_node if participant is not None else node
            db.session.add(
                ChatMessage(
                    node_id=current_node.id if current_node is not None else None,
                    participant_id=participant.id if participant is not None else None,
                    room_id=room_id,
                    content=data.get("content", ""),
                    receive_time=receive_time,
                )
            )
            db.session.commit()

    def _occupant_ids(self, room_id):
        """Return participant IDs currently subscribed to this room."""
        from psynet.participant import Participant

        return [
            str(pid)
            for (pid,) in ChatRoomMember.query.join(Participant)
            .with_entities(ChatRoomMember.participant_id)
            .distinct()
            .filter(
                ChatRoomMember.room_id == room_id,
                ChatRoomMember.active.is_(True),
                Participant.failed.is_(False),
            )
            .all()
        ]

    def _broadcast_occupancy(self, experiment, room_id):
        experiment.publish_to_subscribers(
            json.dumps(
                {
                    "type": "occupancy_update",
                    "room_id": room_id,
                    "participants": self._occupant_ids(room_id),
                }
            ),
            channel_name=self.channel,
        )

    def _send_history(self, experiment, participant, room_id):
        messages = [
            {"content": m.content, "sender": str(m.participant_id)}
            for m in (
                ChatMessage.query.filter_by(room_id=room_id)
                .order_by(ChatMessage.id)
                .all()
            )
        ]
        experiment.publish_to_subscribers(
            json.dumps(
                {
                    "type": "history",
                    "room_id": room_id,
                    "messages": messages,
                    "target_participant_id": str(participant.id),
                }
            ),
            channel_name=self.channel,
        )


class ChatRoom(JavaScriptContributor):
    """
    A chatroom component for use with :class:`~psynet.modular_page.ModularPage`.

    Configures the chatroom UI for a specific room. The server-side WebSocket
    handling is provided by :class:`EnableChatrooms`, which must be present
    in the experiment timeline.

    Parameters
    ----------
    room_id
        The unique identifier for this chatroom instance. Can be a dynamic
        value computed per trial (e.g. a group ID).
    show_participants
        Whether to display a sidebar listing current participants.
    show_history
        Whether to deliver prior messages to a participant when they join.
    """

    channel = EnableChatrooms.channel
    macro = "chatroom_widget"
    external_template = None

    show_participants = False
    show_history = False

    def __init__(self, room_id, show_participants=False, show_history=False):
        self.room_id = room_id
        self.show_participants = show_participants
        self.show_history = show_history

    def get_css(self):
        """Page-local CSS contributed to the hosting :class:`ModularPage`."""
        from importlib import resources

        return [
            resources.files("psynet")
            .joinpath("resources/css/chatroom-widget.css")
            .read_text(encoding="utf-8")
        ]

    def get_js_vars(self):
        """Page-local configuration contributed to the hosting page."""
        return {
            "chatroom_config": {
                "room_id": self.room_id,
                "channel": self.channel,
                "show_participants": bool(self.show_participants),
                "show_history": bool(self.show_history),
            }
        }

    def get_js_page_modules(self):
        """Lifecycle-managed JavaScript activated for the hosting page."""
        return [package_static_url("psynet", "scripts/chatroom-widget.js")]

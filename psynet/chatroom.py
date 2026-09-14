"""Modular-page chat rooms on a shared WebSocket channel.

This module exists so :class:`~psynet.modular_page.ModularPage` can embed a
chat UI without each experiment reimplementing occupancy, persistence, and
catch-up. Dallinger relays inbound frames to every current subscriber
immediately. :class:`EnableChatrooms` then persists ``message`` frames and
publishes an authoritative history snapshot for the room.

That snapshot can still be empty when ``request_state`` runs on another
worker before the persist commits. When ``show_history`` is true, the
widget waits for the first snapshot before enabling Send or painting
live lines. Frames that arrive during that wait are appended after the
snapshot. After that, live relays append as usual. An empty first
snapshot still completes the load. The server republishes history after
persist so a partner who missed both the wait window and the live relay
can still fill an empty feed.

Maintainers should treat the JSON ``type`` values (``join_room``,
``leave_room``, ``request_state``, ``message``, ``occupancy_update``,
``history``) as the public protocol between :class:`ChatRoom` and
:class:`EnableChatrooms`.
"""

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
                self._send_history(experiment, room_id, participant=participant)

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
            # Join-time request_state can race this commit on another worker.
            # Republish the room log so late subscribers still catch up.
            self._send_history(experiment, room_id)

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

    def _send_history(self, experiment, room_id, participant=None):
        """Publish the persisted message log for ``room_id``.

        When ``participant`` is set, only that participant's widget applies the
        snapshot. That is the join-time catch-up path. When omitted, every
        widget in the room applies it, which recovers partners whose
        ``request_state`` raced the persist of a just-sent line.
        """
        messages = [
            {"content": m.content, "sender": str(m.participant_id)}
            for m in (
                ChatMessage.query.filter_by(room_id=room_id)
                .order_by(ChatMessage.id)
                .all()
            )
        ]
        payload = {
            "type": "history",
            "room_id": room_id,
            "messages": messages,
        }
        if participant is not None:
            payload["target_participant_id"] = str(participant.id)
        experiment.publish_to_subscribers(
            json.dumps(payload),
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
        Whether to wait for the persisted room log before enabling the
        chatroom. Live messages that arrive during that wait are shown
        after the snapshot. The server also republishes the log after
        each new message so a partner whose first snapshot raced persist
        still catches up.
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

"""Multi-chatroom demo experiment.

Participants choose one of N configurable chatrooms and chat in real time.
Messages are persisted to the database as ChatroomDemoMessage records.
(The demo defines its own table rather than reusing ``psynet.chatroom`` so
it can illustrate a low-level, custom chatroom implementation.)

Configuration keys (config.txt):
    num_chatrooms (int, default 3):         Number of parallel chatrooms.
    chatroom_max_occupancy (int, optional): Max participants per room.
    chatroom_show_history (bool, default True): Load prior messages on join.
"""

import json
from datetime import datetime, timezone

from dallinger import db
from dallinger.config import get_config
from dallinger.experiment import experiment_route
from dallinger.experiment_server.utils import success_response
from sqlalchemy import Column, ForeignKey, Integer, String

import psynet.experiment
from psynet.data import SQLBase, SQLMixin, register_table
from psynet.page import InfoPage
from psynet.participant import Participant
from psynet.timeline import Page, PageMaker, Timeline

GLOBAL_CHANNEL = "chatrooms"


@register_table
class ChatroomDemoMessage(SQLBase, SQLMixin):
    # The table name is prefixed to avoid clashing with ``psynet.chatroom``,
    # which defines its own ``chat_message`` table for ``ModularPage`` chatrooms.
    __tablename__ = "chatroom_demo_message"

    room_id = Column(String, index=True)
    content = Column(String)
    sender_id = Column(Integer, ForeignKey("participant.id"), index=True)

    def __init__(self, room_id, content, sender_id):
        self.room_id = room_id
        self.content = content
        self.sender_id = sender_id


class ChatroomPage(Page):
    def __init__(
        self,
        room_id,
        global_channel="chatrooms",
        room_label=None,
        show_history=True,
        **kwargs,
    ):
        self.room_id = room_id
        self.global_channel = global_channel
        self.room_label = room_label or f"Room {room_id}"
        self.show_history = show_history

        super().__init__(
            label="chatroom",
            template_fragment_path="templates/chatroom-page.html",
            js_vars={
                "chatroom_room_id": room_id,
                "chatroom_global_channel": global_channel,
                "chatroom_room_label": self.room_label,
                "chatroom_show_history": show_history,
            },
            css_links=["/static/chatroom.css"],
            js_page_modules=["/static/chatroom.js"],
            save_answer=False,
            **kwargs,
        )

    def get_bot_response(self, experiment, bot):
        return None


class RoomSelectionPage(Page):
    def __init__(self):
        config = get_config()
        super().__init__(
            label="choose_chatroom",
            time_estimate=15,
            template_fragment_path="templates/room-selection.html",
            js_vars={
                "num_chatrooms": config.get("num_chatrooms", 3),
                "max_occupancy": config.get("chatroom_max_occupancy", None),
                "chatroom_global_channel": GLOBAL_CHANNEL,
            },
            js_page_modules=["/static/room-selection.js"],
            # save_answer="current_room" writes the chosen value to
            # participant.var.current_room, which the next PageMaker reads to
            # configure ChatroomPage.
            save_answer="current_room",
        )

    def get_bot_response(self, experiment, bot):
        return "0"


class Exp(psynet.experiment.Experiment):
    label = "Multi-chatroom demo"

    # Setting `channel` subscribes the experiment to this WebSocket channel so
    # that `receive_message` is called for incoming messages. It also subscribes
    # to `dallinger_control`, which carries infrastructure events such as
    # unexpected client disconnects. Without this, `receive_message` is never called.
    channel = GLOBAL_CHANNEL

    @classmethod
    def extra_parameters(cls):
        super().extra_parameters()
        config = get_config()
        config.register("num_chatrooms", int)
        config.register("chatroom_max_occupancy", int)
        config.register("chatroom_show_history", bool)

    timeline = Timeline(
        PageMaker(RoomSelectionPage, time_estimate=15),
        PageMaker(
            lambda experiment, participant: ChatroomPage(
                room_id=participant.var.current_room,
                global_channel=GLOBAL_CHANNEL,
                room_label=(
                    f"Room {int(participant.var.current_room) + 1}"
                    if participant.var.current_room
                    else None
                ),
                show_history=experiment.chatroom_show_history,
            ),
            time_estimate=10,
        ),
        InfoPage("Thanks for participating!", time_estimate=5),
    )

    @property
    def chatroom_show_history(self):
        return get_config().get("chatroom_show_history", True)

    @staticmethod
    def _compute_occupancy():
        """Return current room counts and participant IDs from participant.var state."""
        n = get_config().get("num_chatrooms", 3)
        rooms = {str(i): {"count": 0, "participants": []} for i in range(n)}
        for p in Participant.query.filter_by(failed=False).all():
            if p.var.get("subscribed", False):
                rid = str(p.var.get("current_room", ""))
                if rid in rooms:
                    rooms[rid]["count"] += 1
                    rooms[rid]["participants"].append(str(p.id))
        return rooms

    def _broadcast_occupancy(self):
        """Publish current room occupancy and participant lists to all subscribers.

        Called after every join/leave/disconnect so clients can update both
        room-selection counts and chatroom participant sidebars from a single
        authoritative snapshot. Uses publish_to_subscribers, which publishes
        to the experiment's channel via Redis — the same relay mechanism that
        delivers client messages, but initiated server-side.
        """
        self.publish_to_subscribers(
            json.dumps(
                {
                    "type": "occupancy_update",
                    "rooms": self._compute_occupancy(),
                    "max_occupancy": get_config().get("chatroom_max_occupancy", None),
                }
            )
        )

    def receive_message(
        self, message, channel_name=None, participant=None, node=None, receive_time=None
    ):
        """Record state changes, persist chat messages, and broadcast occupancy updates.

        Dallinger's WebSocket relay automatically forwards every incoming message
        to all other subscribers on the same channel, so chat messages reach other
        participants without any server re-broadcast. For join/leave/disconnect
        events, this method additionally calls _broadcast_occupancy() to push an
        authoritative occupancy snapshot to all clients (both the room-selection
        page and chatroom participant sidebars).
        """
        try:
            msg = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return

        if channel_name == GLOBAL_CHANNEL:
            msg_type = msg.get("type")

            # Ignore our own occupancy_update broadcasts to avoid re-processing.
            if msg_type == "occupancy_update":
                return

            # A client on the room-selection page requesting a fresh snapshot.
            # Respond by broadcasting the current counts to all subscribers.
            if msg_type == "request_occupancy":
                self._broadcast_occupancy()
                return

            room_id = str(msg.get("room_id", "")).strip()
            if not room_id or not participant:
                return

            if msg_type == "join_room":
                # ReconnectingWebSocket re-sends join_room on every reconnect;
                # guard against overwriting joined_at in that case.
                already_in_room = (
                    participant.var.get("subscribed", False)
                    and str(participant.var.get("current_room", "")) == room_id
                )
                if not already_in_room:
                    participant.var.subscribed = True
                    participant.var.joined_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()
                    self._broadcast_occupancy()

            elif msg_type == "leave_room":
                if participant.var.get("subscribed", False):
                    participant.var.subscribed = False
                    participant.var.left_at = datetime.now(timezone.utc).isoformat()
                    db.session.commit()
                    self._broadcast_occupancy()

            elif msg_type == "message":
                db.session.add(
                    ChatroomDemoMessage(
                        room_id=room_id,
                        content=msg.get("content", ""),
                        sender_id=participant.id,
                    )
                )
                db.session.commit()

        elif channel_name == "dallinger_control":
            # dallinger_control carries infrastructure events. We listen for
            # "unsubscribed" on our channel, which Dallinger fires when a client's
            # WebSocket drops unexpectedly (e.g. closed tab, network loss). This
            # serves as a fallback so participants who disconnect without sending
            # leave_room are still marked as absent.
            if not (
                msg.get("type") == "channel"
                and msg.get("channel") == GLOBAL_CHANNEL
                and msg.get("event") == "unsubscribed"
            ):
                return
            if participant and participant.var.get("subscribed", False):
                participant.var.subscribed = False
                participant.var.left_at = datetime.now(timezone.utc).isoformat()
                db.session.commit()
                self._broadcast_occupancy()

    @experiment_route("/chatroom_history", methods=["GET"])
    @classmethod
    def chatroom_history(cls):
        """Return the message history for a single room."""
        from flask import request

        room_id = request.args.get("room_id", "")
        participant_id = request.args.get("participant_id", "")
        unique_id = request.args.get("unique_id", "")
        participant = Participant.query.filter_by(id=participant_id).first()
        if (
            not participant
            or participant.unique_id != unique_id
            or participant.var.get("current_room") != room_id
        ):
            return success_response(messages=[])
        messages = [
            {
                "type": "message",
                "content": m.content,
                "sender": str(m.sender_id),
                "timestamp": m.creation_time.isoformat() if m.creation_time else None,
            }
            for m in (
                ChatroomDemoMessage.query.filter_by(failed=False, room_id=room_id)
                .order_by(ChatroomDemoMessage.creation_time)
                .all()
            )
        ]
        return success_response(messages=messages)

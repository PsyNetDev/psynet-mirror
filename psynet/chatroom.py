"""Modular-page chat rooms on a checked WebSocket connection.

This module exists so :class:`~psynet.modular_page.ModularPage` can embed a
chat UI without each experiment reimplementing occupancy, persistence, and
catch-up. The widget opens ``/experiment-socket`` with the participant's
:attr:`~psynet.participant.Participant.websocket_scope`, so
:meth:`~psynet.experiment.Experiment.accept_websocket_connection` has checked
who sends each frame. :class:`EnableChatrooms` persists ``message`` frames and
sends each one, and every occupancy update, as a directed message to the
room's active members only. Nothing is broadcast on the channel, which any
connection could subscribe to.

When ``show_history`` is true, the widget asks for the room log after
joining and waits for it before enabling Send or painting live lines.
Frames that arrive during that wait are appended after the snapshot,
consuming snapshot matches as a multiset so two identical lines are not
collapsed to one. An empty snapshot still completes the load.

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
from .utils import get_logger

logger = get_logger()


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
    when they leave. A membership counts only while the participant is still
    on the page they joined from (``page_uuid``), so moving on leaves the room
    even if the page never sent ``leave_room``.
    """

    __tablename__ = "chat_room_member"

    id = Column(Integer, primary_key=True)
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)
    room_id = Column(String(128), index=True)
    page_uuid = Column(String)
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
    requires_checked_connection = True

    def handle_message(
        self, message, channel_name, participant, node, receive_time, experiment
    ):
        from dallinger import db

        data = json.loads(message)
        room_id = data.get("room_id")
        if room_id is None or participant is None:
            return

        msg_type = data.get("type")

        if msg_type == "join_room":
            if not self._page_shows_room(experiment, participant, room_id):
                logger.warning(
                    "Refused to let participant %s join chat room %r, which "
                    "their current page doesn't show.",
                    participant.id,
                    room_id,
                )
                return
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
                    page_uuid=participant.page_uuid,
                    active=True,
                    join_time=receive_time,
                )
            )
            db.session.commit()
            self._send_occupancy(experiment, room_id)

        elif msg_type == "leave_room":
            ChatRoomMember.query.filter_by(
                participant_id=participant.id,
                room_id=room_id,
                active=True,
            ).update({"active": False, "leave_time": receive_time})
            db.session.commit()
            self._send_occupancy(experiment, room_id)

        elif not self._is_member(participant, room_id):
            return

        elif msg_type == "request_state":
            self._send_history(experiment, room_id, participant)

        elif msg_type == "message":
            current_node = participant.current_node
            content = data.get("content", "")
            db.session.add(
                ChatMessage(
                    node_id=current_node.id if current_node is not None else None,
                    participant_id=participant.id,
                    room_id=room_id,
                    content=content,
                    receive_time=receive_time,
                )
            )
            db.session.commit()
            # Members read after this commit, so one who joins later gets the
            # line from their history snapshot instead.
            experiment.publish_to_participants(
                {
                    "type": "message",
                    "room_id": room_id,
                    "content": content,
                    "sender": str(participant.id),
                },
                self._occupant_ids(room_id),
            )

    @staticmethod
    def _page_shows_room(experiment, participant, room_id):
        """Return whether the participant's current page has a chat room called ``room_id``."""
        try:
            page = experiment.timeline.get_current_elt(experiment, participant)
        except Exception:
            logger.warning(
                "Could not find the current page of participant %s.",
                participant.id,
                exc_info=True,
            )
            return False
        chatroom = getattr(page, "chatroom", None)
        return chatroom is not None and str(chatroom.room_id) == str(room_id)

    @staticmethod
    def _is_member(participant, room_id):
        return (
            ChatRoomMember.query.filter_by(
                participant_id=participant.id,
                room_id=room_id,
                page_uuid=participant.page_uuid,
                active=True,
            ).first()
            is not None
        )

    def _occupant_ids(self, room_id):
        """Return the IDs of participants in this room who are still on the page they joined from."""
        from psynet.participant import Participant

        return [
            str(pid)
            for (pid,) in ChatRoomMember.query.join(Participant)
            .with_entities(ChatRoomMember.participant_id)
            .distinct()
            .filter(
                ChatRoomMember.room_id == room_id,
                ChatRoomMember.active.is_(True),
                ChatRoomMember.page_uuid == Participant.page_uuid,
                Participant.failed.is_(False),
            )
            .all()
        ]

    def _send_occupancy(self, experiment, room_id):
        occupants = self._occupant_ids(room_id)
        experiment.publish_to_participants(
            {
                "type": "occupancy_update",
                "room_id": room_id,
                "participants": occupants,
            },
            occupants,
        )

    def _send_history(self, experiment, room_id, participant):
        """Send the persisted message log for ``room_id`` to ``participant``."""
        messages = [
            {"content": m.content, "sender": str(m.participant_id)}
            for m in (
                ChatMessage.query.filter_by(room_id=room_id)
                .order_by(ChatMessage.id)
                .all()
            )
        ]
        experiment.publish_to_participants(
            {"type": "history", "room_id": room_id, "messages": messages},
            [participant.id],
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
        value computed per trial (e.g. a group ID). A participant can only
        join the room that their current page shows.
    show_participants
        Whether to display a sidebar listing current participants.
    show_history
        Whether to wait for the persisted room log before enabling the
        chatroom. Live messages that arrive during that wait are shown
        after the snapshot.
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

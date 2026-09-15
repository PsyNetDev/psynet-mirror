.. _chatrooms:

===================
Multi-chatroom demo
===================

Source: ``demos/features/websocket_chatroom``

This demo shows how to build a real-time multi-room chat experiment using
PsyNet's WebSocket infrastructure. Participants first choose from N configurable
chatrooms on a room-selection page, then enter their chosen room and chat with
other participants in real time.

The demo illustrates four complementary patterns:

**Client WebSocket chat messaging**
    All chat traffic flows through a single ``chatrooms`` WebSocket channel
    shared by every participant. Dallinger's relay automatically forwards each
    message to all other subscribers, so the server never needs to re-broadcast
    chat messages. Clients filter incoming messages by ``room_id`` to display
    only those relevant to their room. New ``room_id`` values can be created on
    demand on the client side as needed using this pattern.

**Server-side recording of messages**
    The server's ``receive_message`` persists each ``message``-type event as a
    custom ``ChatMessage`` record. This keeps the server logic thin while
    ensuring all messages are available for downstream analysis.

**Server broadcast for occupancy updates**
    Join, leave, and unexpected-disconnect events change room occupancy.
    After each such event the server calls ``publish_to_subscribers`` to push
    an authoritative ``occupancy_update`` snapshot — containing per-room counts
    and participant IDs — to all connected clients. The room-selection page uses
    this to keep occupancy counts current; the chatroom page uses it to maintain
    the participant sidebar. Clients can also request a snapshot at any time by
    sending a ``request_occupancy`` message.

**Custom web route for chat history**
    The ``/chatroom_history`` endpoint returns the persisted message log for a
    room. The chatroom page fetches this once on first connect so participants
    who join late can read prior messages.

Presence state (whether a participant is currently in a room) is tracked via
``participant.var`` attributes.

The demo is configurable via ``config.txt``:

- ``num_chatrooms`` — number of parallel rooms (default 3).
- ``chatroom_max_occupancy`` — maximum participants per room; omit for no limit.
- ``chatroom_show_history`` — whether to load prior messages when a participant joins (default true).


.. literalinclude:: ../../demos/features/websocket_chatroom/experiment.py
   :language: python

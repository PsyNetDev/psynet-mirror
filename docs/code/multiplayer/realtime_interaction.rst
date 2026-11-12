.. _realtime_interaction:

=====================
Real-time interaction
=====================

Participants on the same page can interact live by exchanging WebSocket
messages through the server, for example to take turns in a game or to edit a
shared answer. The :doc:`chatroom <chatroom>` is built this way.

For a game whose rules run on the server while the players move, such as one
where everyone acts at once or the game goes on between their moves, use a
:doc:`live session <live_sessions>` instead. It runs on Dallinger's real-time
engine, which keeps the game's state, plays its bots and saves its record.

How messages travel
-------------------

WebSocket messaging comes from Dallinger. Each message belongs to a
**channel**, identified by a string name. A page can talk to the server in
two ways:

- **Checked connection.** The page opens
  ``dallinger.openExperimentSocket({scope: psynetTemplateData.websocketScope})``.
  PsyNet checks that the token belongs to the participant before accepting the
  connection, so the handler's ``participant`` is the one who sent the
  message. Messages go only to the server: no other browser sees them. The
  server answers individual participants with
  ``experiment.publish_to_participants(payload, participant_ids)``. Use this
  whenever it matters who sent a message or who reads the reply. The
  :doc:`chatroom <chatroom>` works this way.
- **Channel broadcast.** The page connects with
  ``PsyNetWebSocketChannel.connect()``. The server forwards each message at
  once to every browser connected to that channel, including the sender,
  before any experiment code runs. The handler's ``participant`` is looked up
  from the ``sender`` or ``participant_id`` field of the message, which the
  browser writes and nobody checks. Any browser can connect to any channel and
  read everything sent on it, including what the server publishes with
  ``publish_to_subscribers``. The socket itself is admitted with the
  participant's token, so it also receives the server's directed messages for
  this participant through ``onDirect``; only those are trusted, never the
  channel's own messages.

In both cases only browsers connected at that moment receive a message;
nothing is stored for later.

The server as the authority
---------------------------

Treat messages from browsers as requests and messages from the server as the
record of what happened. The following design keeps participants in sync:

- The server stores the shared state in the database, for example in a table
  registered with ``@register_table``, in ``trial.var``, or, for state the
  whole group shares, in ``group_round.var`` of the round that a group's cued trials
  share (see :ref:`rounds-one-trial-per-player`). Handlers run in
  several processes, so attributes on the handler object or on the
  experiment are not shared between messages.
- For each request, the handler checks it against the stored state, rejects
  it if it is out of turn, duplicated or late, and otherwise updates the
  state, commits, and publishes the new state.
- Browsers render only the state published by the server and ignore requests
  from other browsers. Timers, animations and "sending…" indicators are fine,
  but the browser does not decide what the state is.
- Keep as much of the experiment logic on the server as possible, so that page
  JavaScript stays small.

Channels and ``WebSocketElt``
-----------------------------

A :class:`~psynet.timeline.WebSocketElt` subscribes the experiment to one
channel and receives its messages in ``handle_message``. Subclass it together
with ``NullElt``, which makes it invisible to participants, and give it a
channel name that no other part of the experiment uses.
:class:`~psynet.chatroom.EnableChatrooms` is built this way:

.. literalinclude:: ../../../psynet/chatroom.py
   :start-at: class EnableChatrooms(NullElt, WebSocketElt):
   :end-at: channel = "modular_page_chat"

``NullElt`` and ``WebSocketElt`` are imported from ``psynet.timeline``. Place
the element in the experiment's ``Timeline``, not in ``show_trial``: PsyNet
registers handlers when it processes the timeline at launch. Several elements
with different channels can be used in one experiment.

PsyNet uses the channels ``modular_page_chat``, ``psynet_experiment`` and
names beginning with ``psynet_`` itself, and Dallinger uses
``dallinger_control``. Avoid these names.

Sending and receiving messages
------------------------------

Handling messages on the server
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``handle_message`` receives the message as a JSON string, the channel name,
the ``participant`` and ``node`` (or ``None``), the time the server received
it, and the experiment. Set ``requires_checked_connection = True`` on the
element to take messages only from checked connections. ``participant`` is
then the checked sender, the handler runs on the web process that holds the
socket, and frames sent to the channel any other way are ignored.

The chatroom's handler only lets a participant join the room their current
page shows:

.. literalinclude:: ../../../psynet/chatroom.py
   :start-at: def handle_message(
   :end-before: elif msg_type == "leave_room":
   :dedent: 4

It then sends the room's current members to those members only:

.. literalinclude:: ../../../psynet/chatroom.py
   :pyobject: EnableChatrooms._send_occupancy
   :dedent: 4

``publish_to_participants`` takes anything ``json.dumps`` accepts and a list
of participant IDs, and delivers the payload to every connection those
participants hold. PsyNet only accepts a connection that names a participant
if it carries their token.

.. warning::

   Never forward a participant's payload unchanged with
   ``publish_to_participants``: the recipients' pages would trust whatever
   ``type`` that participant chose. Wrap forwarded content in your own
   message with a fixed ``type``, for example
   ``{"type": "chat_message", "text": text}``. PsyNet raises ``ValueError``
   for the message types it reserves for its own directed messages, such as
   ``timeline_hold_wake``. Only ``self.publish_to_participants`` checks this;
   don't call Dallinger's ``publish_to_participants`` directly.

An element without ``requires_checked_connection`` gets every message on its
channel from a worker process. It can reply with
``experiment.publish_to_subscribers(json.dumps(payload), channel)``, which
reaches every browser on the channel and the experiment itself, so give the
server's own messages a ``type`` that the handler ignores. Never send such a
handler anything that only one participant should see.

Connecting from the page
~~~~~~~~~~~~~~~~~~~~~~~~

For a checked connection, open the socket in a page module's ``activate()``
function and close it in its cleanup function (see
:doc:`/code/pages/custom_front_ends`). ``send(channel, message)`` encodes the
message as JSON and queues it while the socket is reconnecting. ``onOpen`` runs
each time the socket connects, ``onDirect`` receives the server's directed messages
already decoded, and ``onRefused`` runs if PsyNet refuses the connection.
PsyNet sends its own directed messages to the same connections (for example
``{"type": "timeline_hold_wake", ...}``), so every ``onDirect`` handler, here
and on a channel broadcast below, should check ``message.type`` and ignore
types it doesn't handle. The chatroom widget connects like this:

.. literalinclude:: ../../../psynet/static/scripts/chatroom-widget.js
   :language: javascript
   :start-at: chatConnection = dallinger.openExperimentSocket({
   :end-before: window.addEventListener("beforeunload"
   :dedent: 8

For a channel broadcast, every timeline page provides
``PsyNetWebSocketChannel.connect()``. It takes the channel name and
``onOpen``, ``onMessage``, ``onDirect`` and ``onClose`` callbacks, and returns
a connection with ``send(message)``, ``isOpen()`` and ``close()``. ``send``
raises an error if the connection is not open. Include ``sender`` in every
message so that the handler receives a participant. ``onMessage`` receives
frames published on the channel, which any page can publish, so never trust
them. ``onDirect`` receives directed messages that the server sends with
``publish_to_participants``; these reach only this participant's checked
connections, and can arrive before ``onOpen`` runs. As above, check
``message.type`` because PsyNet's own directed messages arrive here too.

Keeping shared state consistent
-------------------------------

- **Concurrent handlers.** Several processes can handle messages at
  the same time, so two messages may be processed in a different order from
  the one in which they arrived. Lock the rows you read and update, for
  example with SQLAlchemy's ``with_for_update()``, and number turns or actions
  so that the handler can reject stale ones.
- **Publish after commit.** Publish the new state only after
  ``db.session.commit()``, so that a browser that asks for the state straight
  away gets the same version.
- **Catching up.** A browser misses anything published while it was
  disconnected or still loading the page. ``onOpen`` runs on the first
  connection and after every reconnection, so ask for the full state there.
  The chatroom sends a ``request_state`` message and the server replies with
  the stored messages, to that participant only:

  .. literalinclude:: ../../../psynet/chatroom.py
     :start-at: elif msg_type == "request_state":
     :end-before: elif msg_type == "message":
     :dedent: 8

  A page reload resumes the same way, because the page reconnects and asks
  again.
- **Recording the outcome.** Store the result of the interaction on the trial,
  for example in its answer or ``trial.var``, and include everything later
  analysis or node creation needs. In chain experiments,
  ``summarize_trials`` builds the next node from the trials, so it can only
  use what they contain.

Disconnects and timeouts
------------------------

Both kinds of connection reconnect automatically after they drop, and
``onOpen`` runs again when they come back. Disable controls in between:
``PsyNetWebSocketChannel``'s ``send`` fails while the connection is closed,
and a checked connection queues messages until it reopens, which may surprise
a participant who sees nothing happen.

When a browser connects, disconnects, or joins or leaves a channel, Dallinger
publishes an event on the ``dallinger_control`` channel, with the
participant ID the browser connected with in ``client.participant_id``. The
experiment is subscribed to ``dallinger_control`` whenever it has a
``WebSocketElt`` or sets ``channel``, but these events do not reach
``WebSocketElt`` handlers. To react to them, override the experiment's
``receive_message``, call ``super().receive_message(...)`` so that the
``WebSocketElt`` handlers still run, and check ``channel_name``. The
``websocket_chatroom`` demo sets ``channel`` directly and marks a participant
as absent when their browser leaves the chatroom channel:

.. literalinclude:: ../../../demos/features/websocket_chatroom/experiment.py
   :start-at: elif channel_name == "dallinger_control":
   :end-before: @experiment_route
   :dedent: 8

Do not give a ``WebSocketElt`` the channel ``dallinger_control``: the
experiment is already subscribed to it, so each event would be handled twice.

A dropped connection is often followed by a reconnection, so do not treat it
as the participant leaving the experiment. Use the group's barrier timeouts
(see :doc:`synchronization`) to remove members who stop responding. Turn time
limits need a deadline stored with the state: reject actions that arrive after
it, and have the page send a timeout request when its countdown ends.

Testing
-------

Bots in ``test_n_bots`` tests submit pages over HTTP and do not open
WebSockets. On a live page, a bot submits ``get_bot_response`` like any other
page. Test the server side by calling ``handle_message`` directly, as
``tests/isolated/test_chatroom.py`` does for the chatroom. Test the browser
side with a :doc:`Playwright test </test/frontend>` that opens one browser
context per participant, so that each has its own identity; the test for the
``websocket_chatroom`` demo, ``tests/playwright/demos/websocket_chatroom.spec.js``,
does this with two participants. Test out-of-turn and duplicate actions,
reloading the page mid-interaction, and what each participant can see, as
well as the normal flow.

.. seealso::

   The :doc:`/skills/realtime-synchronous-experiments` skill.

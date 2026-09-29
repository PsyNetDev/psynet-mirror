.. _realtime_interaction:

=====================
Real-time interaction
=====================

Participants on the same page can interact live by exchanging WebSocket
messages through the server, for example to take turns in a game or to edit a
shared answer. The :doc:`chatroom <chatroom>` is built this way.

How messages travel
-------------------

WebSocket messaging comes from Dallinger. Each message belongs to a
**channel**, identified by a string name:

- A browser connects to one channel and sends messages on it. The server
  forwards each message at once to every browser connected to that channel,
  including the sender, before any experiment code runs.
- If the experiment is subscribed to the channel, Dallinger also queues the
  message for a worker process, which calls the experiment's handler.
- The experiment sends messages with ``publish_to_subscribers``. Only browsers
  connected at that moment receive them; nothing is stored for later.
- The handler's ``participant`` is looked up from the ``sender`` or
  ``participant_id`` field of the message, which the browser writes. Dallinger
  does not check it.
- Any browser can connect to any channel.

The server as the authority
---------------------------

Because every browser on a channel sees every message sent on it, treat
messages from browsers as requests and messages from the server as the
record of what happened. The following design keeps participants in sync:

- The server stores the shared state in the database, for example in a table
  registered with ``@register_table`` or in ``trial.var``. Handlers run in
  separate worker processes, so attributes on the handler object or on the
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
the ``participant`` and ``node`` looked up from the message (or ``None``), the
time the server received it, and the experiment. The chatroom's handler
records when a participant joins a room:

.. literalinclude:: ../../../psynet/chatroom.py
   :start-at: def handle_message(
   :end-before: elif msg_type == "request_state":
   :dedent: 4

It then publishes the room's current members to every browser on the
channel:

.. literalinclude:: ../../../psynet/chatroom.py
   :pyobject: EnableChatrooms._broadcast_occupancy
   :dedent: 4

``publish_to_subscribers`` takes a string, so encode the payload with
``json.dumps``. The experiment is itself subscribed to the channel, so
``handle_message`` also receives the server's own messages. Give them a
``type`` that the handler ignores.

Every browser on the channel receives each published message. To address one
participant, include their ID in the payload and let the other browsers
ignore it, as the chatroom does with ``target_participant_id`` for history.
This does not hide the message, so send information that other participants
must not see over an HTTP route that checks the participant's ``unique_id``
(see :doc:`/code/pages/custom_routes`) instead of over the channel.

Connecting from the page
~~~~~~~~~~~~~~~~~~~~~~~~

Every timeline page provides ``PsyNetWebSocketChannel.connect()``. It takes the
channel name and ``onOpen``, ``onMessage`` and ``onClose`` callbacks, and
returns a connection with ``send(message)``, ``isOpen()`` and ``close()``.
``send`` encodes the message as JSON and raises an error if the connection is
not open. ``onMessage`` receives messages already decoded from JSON. Call
``connect`` in a page module's ``activate()`` function and close the
connection in its cleanup function (see :doc:`/code/pages/custom_front_ends`).
The chatroom widget connects like this:

.. literalinclude:: ../../../psynet/static/scripts/chatroom-widget.js
   :language: javascript
   :start-at: chatConnection = PsyNetWebSocketChannel.connect({
   :end-before: window.addEventListener("beforeunload"
   :dedent: 8

Include ``sender`` in every message so that the handler receives the
participant.

Keeping shared state consistent
-------------------------------

- **Concurrent handlers.** Several worker processes can handle messages at
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
  the current state:

  .. literalinclude:: ../../../psynet/chatroom.py
     :start-at: elif msg_type == "request_state":
     :end-before: elif msg_type == "leave_room":
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

``PsyNetWebSocketChannel`` reconnects automatically after the connection
drops. ``onClose`` runs when it drops and ``onOpen`` when it comes back;
disable controls in between, because ``send`` fails while the connection is
closed.

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

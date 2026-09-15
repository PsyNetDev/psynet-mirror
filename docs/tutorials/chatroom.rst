.. _Chatroom:

=========
Chatrooms
=========

PsyNet provides a chatroom component that lets participants send real-time text
messages to each other during an experiment. It is designed to be embedded
inside a :class:`~psynet.modular_page.ModularPage` and communicates over a
WebSocket channel.

Overview
--------

There are two pieces you need to wire together:

* :class:`~psynet.chatroom.EnableChatrooms` — a timeline element that opens
  the server-side WebSocket handler.  Place it **once** near the top of your
  experiment timeline, before any page that uses a chatroom.

* :class:`~psynet.chatroom.ChatRoom` — the per-page component that configures
  the chatroom UI for a specific room.  Pass it as the ``chatroom`` keyword
  argument to a :class:`~psynet.modular_page.ModularPage`.

Basic setup
-----------

1. Add :class:`~psynet.chatroom.EnableChatrooms` to your timeline::

    from psynet.chatroom import ChatRoom, EnableChatrooms
    from psynet.timeline import Timeline

    class MyExperiment(Experiment):
        timeline = Timeline(
            EnableChatrooms(),
            ...
        )

2. Pass a :class:`~psynet.chatroom.ChatRoom` instance to the ``chatroom``
   parameter of :class:`~psynet.modular_page.ModularPage`::

    from psynet.modular_page import ModularPage, NullControl

    ModularPage(
        "chat",
        "Chat with your partner.",
        NullControl(),
        chatroom=ChatRoom(room_id="my_room"),
        time_estimate=60,
    )

   The ``room_id`` string determines which participants share the same chat
   history and occupancy list.  Participants whose ``room_id`` values match
   will see each other's messages.

Room IDs
--------

The ``room_id`` can be any string.  Experiments often want each synchronised
group of participants to share a private room. Inside a trial, the most robust
way to obtain a per-group identifier is
:attr:`Trial.sync_group <psynet.trial.main.Trial.sync_group>`, which returns the
:class:`~psynet.sync.SyncGroup` matching the trial maker's ``sync_group_type``::

    chatroom=ChatRoom(
        room_id=f"group_{self.sync_group.id}",
        show_participants=True,
        show_history=True,
    )

Options
-------

:class:`~psynet.chatroom.ChatRoom` accepts two optional boolean flags:

``show_participants``
    Display a sidebar listing the participant IDs currently in the room.
    Defaults to ``False``.

``show_history``
    Deliver all prior messages for this room to a participant when they first
    join.  Useful when a participant might reconnect mid-session or when
    a group needs shared context from an earlier page.
    Defaults to ``False``.

Message storage
---------------

Every message sent through a chatroom is persisted in the
:class:`~psynet.chatroom.ChatMessage` database table, which records the
sender's participant and node IDs, the room ID, the message content, and the
server-side receive time.  This data is available in the exported dataset after
the experiment completes.

Room membership tracking
------------------------

Join and leave events are persisted in the
:class:`~psynet.chatroom.ChatRoomMember` table, with timestamps and an
``active`` flag.  This data is available in the exported dataset and can be
used to reconstruct each participant's room history.  Participants may be
active in more than one room at the same time.

Customising the chatroom
------------------------

The built-in chatroom widget is implemented in
``psynet/templates/macros/chatroom.html`` as a Jinja macro named
``chatroom_widget``.  To replace it with your own HTML/CSS/JS, subclass
:class:`~psynet.chatroom.ChatRoom` and point it at a custom template file
stored in your experiment's ``templates/`` directory:

.. code-block:: python

    class MyChatRoom(ChatRoom):
        macro = "my_chatroom"
        external_template = "my-chatroom.html"

Then create ``templates/my-chatroom.html`` in your experiment directory.
The macro receives the ``ChatRoom`` instance as its sole ``config`` argument,
so every attribute you set on the subclass is accessible inside the template:

.. code-block:: html

    {% macro my_chatroom(config) %}
    {# config.room_id, config.show_participants, config.show_history
       and any custom attributes you add are all available here. #}
    <div id="chatroom-widget">
        ...
    </div>
    {% endmacro %}

Keep the macro focused on markup: inline ``<script>`` and ``<style>`` blocks in
a custom template are rejected under in-place timeline transitions. Instead,
supply page-local CSS and JavaScript through the component's ``get_css()`` and
``get_js_page_modules()`` hooks, and supply configuration through
``get_js_vars()``.
``ModularPage`` collects these from the chatroom and applies them as managed,
per-page resources that are refreshed across fragment swaps:

.. code-block:: python

    class MyChatRoom(ChatRoom):
        macro = "my_chatroom"
        external_template = "my-chatroom.html"

        def get_css(self):
            return ["#chatroom-widget { height: 400px; }"]

        def get_js_vars(self):
            return {
                "my_chatroom_config": {
                    "room_id": self.room_id,
                    "channel": self.channel,
                }
            }

        def get_js_page_modules(self):
            return ["/static/my-chatroom.js"]

The standalone script should read its configuration from ``psynet.var`` (via
``vars`` in ``activate()``), not ad-hoc globals. Deprecated ``window`` access
to ``js_vars`` is controlled by ``legacy_js_var_globals``; see
:doc:`/tutorials/writing_custom_frontends` and
:doc:`/experiment_development/configuration`.

.. code-block:: javascript

    export async function activate({root, trial, vars}) {
        const config = vars["my_chatroom_config"];
        // ... open the websocket and wire up elements beneath root ...

        return async function cleanup() {
            // ... leave the room and close the socket ...
        };
    }

The built-in ``ChatRoom`` uses the same separation between managed resources
and configuration — see ``get_css``, ``get_js_vars``, and
``get_js_page_modules`` in ``psynet/chatroom.py``. PsyNet activates its widget
script for each page and calls the returned cleanup function before leaving. See
``psynet/static/scripts/chatroom-widget.js`` for the WebSocket protocol,
message rendering, occupancy updates, and cleanup pattern.

If you only need minor CSS changes (e.g. a different height or colour scheme)
you can override the built-in IDs (``#chatroom-widget``,
``#chatroom-messages``, ``#chatroom-input-row``, etc.) in your experiment's
custom stylesheet instead of replacing the template entirely.

Demo
----

The rock-paper-scissors demo illustrates a chatroom that opens after each trial
round, allowing the two players to discuss the outcome before continuing:

.. literalinclude:: ../../demos/experiments/rock_paper_scissors/experiment.py
   :language: python

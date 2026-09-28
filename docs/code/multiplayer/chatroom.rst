.. _Chatroom:

=========
Chatrooms
=========

A chatroom lets participants on the same page exchange text messages in real
time. It is part of a :class:`~psynet.modular_page.ModularPage` and
communicates over a WebSocket channel.

Basic setup
-----------

A chatroom needs two pieces:

1. :class:`~psynet.chatroom.EnableChatrooms` opens the server-side WebSocket
   handler. Place it once in the timeline, before any page with a chatroom.
2. :class:`~psynet.chatroom.ChatRoom` configures the chatroom on one page.
   Pass it to :class:`~psynet.modular_page.ModularPage` as ``chatroom``.

The ``chatroom_simple`` demo pairs participants with a
:class:`~psynet.sync.SimpleGrouper` and gives each pair a room of its own:

.. literalinclude:: ../../../demos/experiments/chatroom_simple/experiment.py
   :start-at: timeline = Timeline(
   :end-before: test_n_bots
   :dedent: 4

.. literalinclude:: ../../../demos/experiments/chatroom_simple/experiment.py
   :pyobject: ChatTrial

Room IDs
--------

Participants whose ``room_id`` values match share the same messages and
participant list. The ``room_id`` can be any string. To give each group a
private room, build it from
:attr:`Trial.sync_group <psynet.trial.main.Trial.sync_group>`, as the demo
does. ``self.sync_group`` returns the group matching the trial maker's
``sync_group_type``, so it works even when a participant is in several
groups (see :doc:`synchronization`).

Options
-------

:class:`~psynet.chatroom.ChatRoom` has two optional flags:

``show_participants`` (default ``False``)
    Show a sidebar with the IDs of the participants currently in the room.

``show_history`` (default ``False``)
    Show the messages sent in the room before the participant opened the
    page. The chatroom is enabled once the earlier messages have loaded.

Stored data
-----------

Every message is stored in the :class:`~psynet.chatroom.ChatMessage` table,
with the sender's participant and node IDs, the room ID, the text and the
time the server received it. Joining and leaving a room is stored in the
:class:`~psynet.chatroom.ChatRoomMember` table, with timestamps and an
``active`` flag; a participant can be active in several rooms at once. Both
tables appear in exports as ``database/chat_message.csv`` and
``database/chat_room_member.csv`` (see :doc:`/data/what_an_export_contains`).

Customizing the chatroom
------------------------

The built-in chatroom widget is the Jinja macro ``chatroom_widget`` in
``psynet/templates/macros/chatroom.html``. To replace it with your own
HTML, CSS and JavaScript, subclass :class:`~psynet.chatroom.ChatRoom` and point
it at a template in your experiment's ``templates/`` directory:

.. code-block:: python

    class MyChatRoom(ChatRoom):
        macro = "my_chatroom"
        external_template = "my-chatroom.html"

Then create ``templates/my-chatroom.html``. The macro receives the
``ChatRoom`` instance as its only argument, ``config``, so every attribute of
the subclass is available in the template:

.. code-block:: html

    {% macro my_chatroom(config) %}
    {# config.room_id, config.show_participants, config.show_history
       and any custom attributes you add are all available here. #}
    <div id="chatroom-widget">
        ...
    </div>
    {% endmacro %}

Keep the macro to markup: inline ``<script>`` and ``<style>`` blocks in a
custom template are rejected under in-place timeline transitions. Supply
page-local CSS and JavaScript through the component's ``get_css()`` and
``get_js_page_modules()`` methods, and configuration through
``get_js_vars()``. :class:`~psynet.modular_page.ModularPage` collects these
from the chatroom and refreshes them for each page:

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

The script reads its configuration from ``psynet.var`` (``vars`` in
``activate()``), not from global variables. Deprecated ``window`` access to
``js_vars`` is controlled by ``legacy_js_var_globals``; see
:doc:`/whats_new/upgrading_to_psynet_14` and :doc:`/reference/configuration`.

.. code-block:: javascript

    export async function activate({root, trial, vars}) {
        const config = vars["my_chatroom_config"];
        // ... open the websocket and wire up elements beneath root ...

        return async function cleanup() {
            // ... leave the room and close the socket ...
        };
    }

The built-in ``ChatRoom`` works the same way; see ``get_css``,
``get_js_vars`` and ``get_js_page_modules`` in ``psynet/chatroom.py``. PsyNet
activates the widget script for each page and calls the returned cleanup
function before leaving. ``psynet/static/scripts/chatroom-widget.js`` shows
the WebSocket protocol, message rendering, occupancy updates and cleanup.

For small style changes, such as a different height or color scheme,
override the built-in IDs (``#chatroom-widget``, ``#chatroom-messages``,
``#chatroom-input-row`` and so on) in your experiment's stylesheet instead of
replacing the template.

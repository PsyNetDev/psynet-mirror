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
    Show a sidebar with the participants currently in the room.

``show_history`` (default ``False``)
    Show the messages sent in the room before the participant opened the
    page. The chatroom is enabled once the earlier messages have loaded.

Pseudonyms
----------

Participants see each other by pseudonym, such as "Blue fox", with an icon
of the animal on a disc of that colour; their own messages are labelled
"You". A participant keeps the same pseudonym in every room, unless the
experiment sets a different one. Each deployment shuffles the colours and
animals differently and then assigns them in order of participant ID, so
participants who arrive one after another differ in both colour and animal,
and any 88 participants in a row all have different pseudonyms. Participants
whose IDs differ by a multiple of 88 share a pseudonym; when such a
participant joins their first :class:`~psynet.sync.SyncGroup` and an active
member there has the same pseudonym, PsyNet gives them a free one
(:meth:`~psynet.pseudonym.PseudonymScheme.replacement` chooses it). Later
groups never rename anyone, so names stay the same once others have seen
them; in a later group, two members can therefore share a pseudonym. The dashboard's
Participants page and the participant table on its Database page show each
participant's pseudonym. Exports keep the deployment ID, so after
loading an export with the same PsyNet version, pseudonym scheme and locale,
``participant.pseudonym`` gives the names that participants saw, for example
to read chat messages that mention them.

Use ``participant.pseudonym`` to show the same names elsewhere, for example
on a results page. It has a ``name``, a ``css_color``, an ``emoji`` and a
``sticker_html``, a picture of the animal in the participant's colour:

.. code-block:: python

    def show_partner(participant):
        pair = participant.active_sync_groups["pair"]
        (partner,) = [p for p in pair.participants if p != participant]
        return InfoPage(
            Markup("Your partner is {} {}.").format(
                partner.pseudonym.sticker_html, partner.pseudonym.name
            ),
        )

To give a participant a particular pseudonym, call
``participant.set_pseudonym("red", "whale")`` from a code block. To change
the colours, animals or how names are formed, subclass
:class:`~psynet.pseudonym.PseudonymScheme` and set it on the experiment:

.. code-block:: python

    from psynet.pseudonym import PseudonymScheme
    from psynet.utils import get_translator

    _ = get_translator()

    class TeamScheme(PseudonymScheme):
        def animals(self):
            return {"lion": (_("lion"), "🦁"), "bear": (_("bear"), "🐻")}

    class Exp(psynet.experiment.Experiment):
        pseudonym_scheme = TeamScheme()

Pseudonyms repeat after a number of participants equal to the least common
multiple of the two list lengths, so lengths with no common factor (the
default has 8 colours and 11 animals) give the most different pseudonyms. :meth:`~psynet.pseudonym.PseudonymScheme.assign`
chooses each participant's pseudonym,
:meth:`~psynet.pseudonym.PseudonymScheme.name` combines the colour and
animal (override it for languages where the colour must agree with the
animal), and :meth:`~psynet.pseudonym.PseudonymScheme.sticker_html` draws
the animal in the participant's colour, as shown in chat rooms and by
:class:`~psynet.group_prompt.GroupPrompt`; override them for full control. The built-in
animals use Microsoft Fluent Emoji pictures, and other animals their emoji;
override :meth:`~psynet.pseudonym.PseudonymScheme.artwork` to supply pictures. Messages, history and occupancy updates carry each
sender's pseudonym (``sender_pseudonym`` and ``pseudonyms``), so a custom
chatroom widget can show it too.

Stored data
-----------

Every message is stored in the :class:`~psynet.chatroom.ChatMessage` table,
with the sender's participant and node IDs, the room ID, the text and the
time the server received it. Joining and leaving a room is stored in the
:class:`~psynet.chatroom.ChatRoomMember` table, with timestamps and an
``active`` flag and the ``page_uuid`` of the page they joined from. A
membership counts only while the participant is still on that page. Both
tables appear in exports as ``database/chat_message.csv`` and
``database/chat_room_member.csv`` (see :doc:`/data/what_an_export_contains`).

Customizing the chatroom
------------------------

The built-in chatroom widget is the Jinja macro ``chatroom_widget`` in
``psynet/templates/macros/chatroom.html``; it talks to the server over
WebSockets as described in :doc:`realtime_interaction`. To replace it with your own
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

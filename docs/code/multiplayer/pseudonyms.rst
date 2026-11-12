.. _pseudonyms:

==========
Pseudonyms
==========

Participants in a group see each other by pseudonym, such as "Blue fox",
with a small picture of the animal in that colour, never by participant ID.
Chat rooms (:doc:`chatroom`) and :class:`~psynet.group_prompt.GroupPrompt`
(:doc:`synchronization`) label members this way, and a participant's own
messages and seat are labelled "You".

How pseudonyms are chosen
-------------------------

A participant keeps the same pseudonym, in every group and chat room, from
their first group on (see below). Each deployment shuffles the colours and animals
differently and then assigns them in order of participant ID, so
participants who arrive one after another differ in both colour and animal,
and any 88 (8 colours × 11 animals) participants in a row all have
different pseudonyms.
Participants whose IDs differ by a multiple of 88 share a pseudonym.

Derived pseudonyms are made unique in the participant's first
:class:`~psynet.sync.SyncGroup`; pseudonyms set with
:meth:`~psynet.participant.Participant.set_pseudonym` are kept. So when a
participant joins their first group and an active member there already has
their derived pseudonym, PsyNet gives them a free one
(:meth:`~psynet.pseudonym.PseudonymScheme.assign_distinct` chooses it).
Later groups never rename anyone, so names stay the same once others have
seen them; in a later group, two members can therefore share a pseudonym.

When partners must not recognise each other across groups, for example
because a player could build a reputation in a game, show them anonymously
instead: pass ``names="anonymous"`` to
:class:`~psynet.group_prompt.GroupPrompt` and to
:class:`~psynet.chatroom.ChatRoom`. Both then draw every other member as the
same grey figure, labelled "Your partner" in a pair and "Another player" in
a larger group. On a page whose group is a pair they agree; the chat
counts the members who have appeared in the room, so after someone leaves
the two can differ.

Showing pseudonyms on other pages
---------------------------------

Use ``participant.pseudonym`` to show the same names elsewhere, for example
on a results page. It has a ``name``, a ``css_color``, an ``emoji`` and a
``sticker_html``, a picture of the animal in the participant's colour, three
times the font size high:

.. code-block:: python

    from markupsafe import Markup

    from psynet.page import InfoPage

    def show_partner(participant):
        pair = participant.active_sync_groups.get("pair")
        others = [] if pair is None else [
            p for p in pair.active_participants if p != participant
        ]
        if not others:
            return InfoPage("Your partner has left.")
        partner = others[0]
        return InfoPage(
            Markup("{}<p>Your partner is {}.</p>").format(
                partner.pseudonym.sticker_html, partner.pseudonym.name
            ),
        )

Messages, history and occupancy updates of a chat room carry each sender's
pseudonym (``sender_pseudonym`` and ``pseudonyms``), so a custom chatroom
widget can show it too; in an anonymous room they are left out.

Customizing pseudonyms
----------------------

To give a participant a particular pseudonym, call
``participant.set_pseudonym("red", "whale")`` from a code block. To change
the colours, animals or how names are formed, subclass
:class:`~psynet.pseudonym.PseudonymScheme` and set it as the experiment's
:attr:`~psynet.experiment.Experiment.pseudonym_scheme`:

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
default has 8 colours and 11 animals) give the most different pseudonyms.
The class docstring of :class:`~psynet.pseudonym.PseudonymScheme` lists the
methods to override: :meth:`~psynet.pseudonym.PseudonymScheme.assign`
chooses each participant's pseudonym,
:meth:`~psynet.pseudonym.PseudonymScheme.format_name` names the pair, and
:meth:`~psynet.pseudonym.PseudonymScheme.render_sticker` draws the animal in
the participant's colour. The built-in animals use Microsoft Fluent Emoji
pictures, and other animals their emoji; override
:meth:`~psynet.pseudonym.PseudonymScheme.artwork` to supply pictures.

Each built-in name, such as "Blue fox", is translated as a whole, so that
languages can make the colour agree with the animal. A scheme's own colours
or animals get the two words joined instead, which can't agree; override
:meth:`~psynet.pseudonym.PseudonymScheme.format_name` to name such pairs in
full. Give new words new keys, since a built-in key keeps its built-in name.

Pseudonyms in the dashboard and exports
---------------------------------------

The dashboard's Participants page and the participant table on its Database
page show each participant's pseudonym. That column can't be searched or
sorted, because most pseudonyms are worked out when shown rather than
stored.
Exports keep the deployment ID, so after loading an export with the same
PsyNet version, pseudonym scheme and locale, ``participant.pseudonym`` gives
the names that participants saw, for example to read chat messages that
mention them. Launching the loaded experiment again writes a new deployment
ID, and so changes the names.

===============
Synchronization
===============

A :class:`~psynet.sync.Grouper` forms groups of participants, and a
:class:`~psynet.sync.GroupBarrier` makes the members of a group wait for each
other. The ``rock_paper_scissors`` demo pairs participants and plays three
synchronized rounds:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :start-at: timeline = Timeline(
   :end-before: test_n_bots
   :dedent: 4

Forming groups
--------------

:class:`~psynet.sync.SimpleGrouper` waits until enough participants are
waiting, then randomly splits them into groups. Participants stay on their
current page, under a waiting indicator, until their group is formed.

``group_type``
    A label for the groups. Barriers and trial makers refer to the groups by
    this label.

``initial_group_size``
    The size of each new group. Required.

``batch_size`` (default: ``initial_group_size``)
    How many participants must be waiting before groups are formed. A larger
    batch lets you form several groups at once from the same pool.

``min_group_size`` (default: ``initial_group_size``)
    A group with fewer active members is below quota and cannot pass a
    barrier; see `Waiting and dropouts`_.

``join_existing_groups`` (default: ``False``)
    If ``True``, an arriving participant first joins an existing group that
    is below ``max_group_size``, preferring the smallest and then the oldest
    group. Participants already waiting at the grouper join such a group on
    the next barrier check after one has room. Closed groups and groups with
    no active members are not joined. Groups formed with this option accept
    *top-ups*: when a member drops out, barriers wait for a replacement
    instead of dissolving the group.

``max_group_size`` (default: ``initial_group_size``)
    The largest size a group can reach through ``join_existing_groups``;
    ``None`` means no limit. Setting it to anything else requires
    ``join_existing_groups=True``. The limit holds when several participants
    try to join at once: joins to one group take turns, and a participant
    who finds a group busy tries the next suitable group, or waits at the
    grouper and tries again shortly.

``join_criterion``
    A function of ``group`` and ``participant`` that returns whether the
    participant may join that group. Only used with
    ``join_existing_groups=True``.

``start_short_after`` (default: ``None``)
    Seconds after which a smaller group may start. Once the longest-waiting
    participant has waited this long and at least ``min_group_size`` are
    waiting, those waiting form a group even if there are fewer than
    ``batch_size``. Needs ``min_group_size`` below ``initial_group_size``, and
    a ``max_wait_time`` (default 20 seconds) longer than ``start_short_after``.
    Combine it with ``join_existing_groups=True`` so that later arrivals can
    still fill the group up. A ``{SECONDS}`` placeholder in ``content`` counts
    down to that short start once ``min_group_size`` are waiting, and shows
    "…" until then; :ref:`a content function <sync-countdown-messages>` can
    show other text instead.

``content``
    The message on the waiting indicator. If omitted, participants see
    "Waiting for other participants…". For translated experiments, mark it as
    described in :doc:`/code/participants/internationalization`.

``id_`` (default: ``{group_type}_grouper_{initial_group_size}``)
    Groupers with the same ID share one pool of waiting participants.

The ``gibbs_within_sync`` demo tops up groups of three, but only while the
leader has more than one trial left:

.. literalinclude:: ../../../demos/experiments/gibbs_within_sync/experiment.py
   :start-at: SimpleGrouper(
   :end-before: trial_maker,
   :dedent: 8

.. literalinclude:: ../../../demos/experiments/gibbs_within_sync/experiment.py
   :pyobject: is_group_joinable

Groups are formed only from participants who are waiting at the same time,
so recruitment must bring them in close together. A participant who waits at
a grouper for longer than ``max_wait_time`` (default 20 seconds) is failed;
raise it if participants arrive slowly.

Accessing the group
~~~~~~~~~~~~~~~~~~~

Each group is a :class:`~psynet.sync.SyncGroup`. Inside a trial,
:attr:`Trial.sync_group <psynet.trial.main.Trial.sync_group>` returns the
group matching the trial maker's ``sync_group_type``. Elsewhere, use
``participant.sync_group`` if the participant is in one active group, or
``participant.active_sync_groups[group_type]`` if they are in several.

``sync_group.participants`` is a read-only list of the group's members; change
membership with ``sync_group.add_participant(participant)`` and
``sync_group.remove_participant(participant)``. The list has no guaranteed
order, so sort by participant ID when you need a stable one, for example to
assign roles. ``sync_group.leader`` is the group's leader.

Regrouping
~~~~~~~~~~

A participant can be in groups of different ``group_type`` at the same time,
but in only one group of each type. To regroup participants, close the group
with a :class:`~psynet.sync.GroupCloser` and place another grouper with the
same ``group_type``. The ``simple_sync_group`` demo forms groups of three,
then groups of two, and assigns roles at a barrier each time:

.. literalinclude:: ../../../demos/experiments/simple_sync_group/experiment.py
   :start-at: timeline = Timeline(
   :end-before: test_n_bots
   :dedent: 4

.. literalinclude:: ../../../demos/experiments/simple_sync_group/experiment.py
   :pyobject: assign_roles

Two groupers of the same type and size share a default ID, and so a waiting
pool. Give them different ``id_`` values if they should not.

Rounds with changing groups
~~~~~~~~~~~~~~~~~~~~~~~~~~~

In games played over many rounds, a participant who is slow in one round
should not hold up everyone else, and should not be failed either. A
:class:`~psynet.sync.Regrouper` placed at the start of each round handles
this. Each time a participant reaches it, they leave their previous group of
that type and wait for the next round. The regrouper then splits everyone
waiting into new groups:

- when every member of the participant's ``within`` group is waiting, or
- when ``deadline`` passes, without whoever isn't ready yet.

Whoever missed the round joins the next one. The groups it forms are never
dissolved when a member leaves, so members who are left continue the round
on their own.

``group_size`` and ``min_group_size`` (default 2)
    The largest and smallest group to form. Everyone waiting is split into
    balanced groups, for example rooms of 8, 8, 7 and 7 for 30 participants.

``deadline``
    Seconds since the first waiting participant arrived, or since the previous
    round started if that is later. ``Clock(45)`` instead starts rounds at fixed
    45-second ticks, whether or not everyone is ready earlier.

``within`` (default: ``None``)
    The ``group_type`` of a group to regroup within, such as a team formed
    earlier by a :class:`~psynet.sync.SimpleGrouper`. Participants are only
    grouped with members of their own team, and each team's rounds run on
    their own: a slow request from one team never delays another team's
    round. Without ``within``, everyone waiting is one pool, and a
    ``deadline`` is required.

``release_left_over`` (default: ``False``)
    If ``True``, participants who don't fit into a group, such as an odd one
    out when pairing, continue ungrouped so that they can see a sit-out page.
    If ``False``, they wait for the next round.

``form_groups``
    A function of ``members``, ``within_group`` and ``regrouper`` that returns
    the groups as lists of participants, for example to avoid repeat partners
    with :func:`~psynet.sync.pairs_avoiding_repeats`. Members not placed in a
    group are left over. You can also subclass
    :class:`~psynet.sync.Regrouper` and override
    :meth:`~psynet.sync.Regrouper.form_groups`.

``on_release``
    A function called after each split that forms at least one group, with
    ``within_group``, ``groups``, ``left_over`` and ``regrouper``, for example
    to assign roles. A late participant can be split on their own in the same
    round, so count rounds per participant, as the ``ultimatum_pairing`` demo
    does.

``content``
    The waiting message. A ``{SECONDS}`` placeholder shows a live countdown to
    the deadline, for example ``"The next round starts in {SECONDS} s."``.
    See :ref:`countdown messages <sync-countdown-messages>`.

``max_wait_time`` (default: 300 seconds)
    The longest a participant waits at the regrouper before being failed.

.. _sync-countdown-messages:

**Countdown messages.** Sometimes the barrier doesn't know yet when the
wait will end, for example while a participant waits alone for a partner,
and ``{SECONDS}`` shows "…". To show different text then, pass a
module-level function as ``content``. It receives ``seconds_left``, which
is ``None`` while the time is unknown and otherwise the whole seconds left
(0 once the time has passed), and can also take ``participant`` and
``barrier``. The message switches within a few seconds of the time
becoming known:

.. literalinclude:: ../../../demos/experiments/lowest_unique_number/experiment.py
   :pyobject: round_message

In the ``lowest_unique_number`` demo, rooms of up to eight players form every
10 seconds. A player who doesn't choose in time is removed from their room by
a :class:`~psynet.sync.GroupBarrier` with
``timeout_between_barriers_action="kick"``, so the rest of the room carries
on, and they join the next round:

.. literalinclude:: ../../../demos/experiments/lowest_unique_number/experiment.py
   :pyobject: play_round

The kicked player sees "Your group went on without you." on the progress bar
straight away (pass ``on_arrival_message`` to change it), and is no longer in
a room when they reach the barrier. A barrier that kicks lets participants
who are not in a group pass straight through (``skip_if_not_in_group``
defaults to ``True``), and ``show_result`` then tells them they sat the round
out. Pass ``skip_if_not_in_group=True`` to the round's other barriers too.
Without it, a participant who reaches a group barrier outside a group gets an
error.

In the ``ultimatum_pairing`` demo, teams form in a lobby and are re-paired
every round. The lobby starts a smaller team after a minute and lets
latecomers join while enough rounds are left:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: SimpleGrouper(
   :end-before: while_loop(
   :dedent: 8

Each round pairs the team's players, avoiding last round's partners, and
starts as soon as the whole team is ready:

.. literalinclude:: ../../../demos/experiments/ultimatum_pairing/experiment.py
   :start-at: Regrouper(
   :end-before: conditional(
   :dedent: 8

Keeping a group in step
-----------------------

Barriers
~~~~~~~~

A :class:`~psynet.sync.GroupBarrier` holds each member until every active
member of the group has reached it. When the last member arrives, the barrier
calls ``on_release`` for the whole group. In ``rock_paper_scissors`` the
barrier after each choice scores the round:

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.show_trial

.. literalinclude:: ../../../demos/experiments/rock_paper_scissors/experiment.py
   :pyobject: RockPaperScissorsTrial.score_trial

``on_release`` can take any of the arguments ``group``, ``participants``,
``participant`` (the leader) and ``barrier``. It must be a module-level
function, a static or class method, or a method bound to a trial maker or a
saved database object such as a trial. The ``barrier`` it receives is rebuilt
from saved settings, so read only scalar settings such as ``content`` and
``max_wait_time`` from it, and store custom barrier attributes as
JSON-compatible values.

The barrier ``id_`` identifies one waiting point. Barriers with the same ID
share a waiting pool, so give barriers with different ``on_release``
callbacks different IDs. Using one ID for barriers with different behavior
(class, ``on_release`` or release settings) raises an error when the
experiment is built.

Arrival notices
~~~~~~~~~~~~~~~

While a member waits at a barrier, members who have not reached it yet see a
notice on the progress bar ("Your partner is ready.", or
"{ARRIVED}/{TOTAL} of your group are ready."). In groups of three or more,
the waiting indicator also says how many members are not ready yet. Set
``notify_arrivals=False`` to turn both off, or pass ``on_arrival_message`` to
change the text. It receives ``kind`` (``"hold"`` for the waiting indicator,
``"notice"`` for the progress bar), ``waiting_count`` and ``group_size``, and
returns the text or ``None`` to hide it. For a notice it is called whenever
the browser fetches the current count, which can be several times per
arrival, so it should depend only on its arguments and have no side effects.
Notices must fit on one line:

.. code-block:: python

    def arrival_message(*, kind, waiting_count, group_size, **kwargs):
        remaining = group_size - waiting_count
        if kind == "hold":
            if group_size <= 2 or remaining <= 0:
                return None
            return f"{remaining} of {group_size} not ready yet"
        return "Your partner is ready."

    GroupBarrier(
        id_="finished_trial",
        group_type="rock_paper_scissors",
        content="Waiting for your partner",
        on_arrival_message=arrival_message,
    )

Pages with a :class:`~psynet.group_prompt.GroupPrompt` that ticks members
live don't show the notice, since the ticks say the same.

``content`` can also be a module-level function of the participant, so that
members waiting at the same barrier see different messages, for example by
role (it can also take ``seconds_left``; see :ref:`sync-countdown-messages`):

.. code-block:: python

    def waiting_text(participant):
        if participant.var.role == "proposer":
            return "Waiting for your partner to accept or reject your offer…"
        return "Your partner is deciding how much to offer you…"

    GroupBarrier(id_="decided", group_type="pair", content=waiting_text)

Showing the group
~~~~~~~~~~~~~~~~~

:class:`~psynet.group_prompt.GroupPrompt` shows the members of a small group
by their pseudonyms (see :doc:`chatroom`), with the participant viewing the
page labelled "You". Each member appears as their pseudonym animal, drawn
in their colour; the other members' names are read out by screen
readers and shown on hover, or below the animals with ``show_names=True``.
Members sit in a row for up to four people and in a zigzag across the
width of the page for more, so the display adapts to any screen. Joining
their first group gives a newcomer a different pseudonym if another active
member already has theirs; after that, pseudonyms never change, so someone
regrouped every round keeps the name their earlier partners saw.

When partners must not recognise each other across rounds, pass
``anonymous=True``: every member is then drawn as the same grey figure,
labelled "Your partner" in a pair and "Another player" in a larger group.

``subgroups`` clusters the members, for example pairs formed within a
room. Pass a sync group type, or a function returning a key per participant;
the viewer's cluster comes first:

.. code-block:: python

    GroupPrompt("Pick a number.", participant=participant, group_type="room", subgroups="pair")

On a decision page, members who have answered get a tick. A member has
answered once they wait at a barrier of the group, typically the barrier
after the decision page, and the ticks appear live as members arrive (this
uses the barrier's arrival updates, so it needs ``notify_arrivals``). Pass
``show_progress=False`` to hide the ticks, or ``answered`` to decide who has
answered when the page is drawn. Members who join the group appear live
too, and members who leave are faded (see below), on any page without
``answers`` or ``answered``, unless ``subgroups`` is a function:

.. code-block:: python

    from psynet.group_prompt import GroupPrompt

    def choose_number(participant):
        return ModularPage(
            "choose",
            GroupPrompt("Pick a number.", participant=participant),
            PushButtonControl(choices=[1, 2, 3, 4, 5]),
            save_answer="choice",
        )

After the barrier, pass ``answers`` to show each member's answer in a speech
bubble, as a dictionary from participant ID to answer. Participant variables
store dictionary keys as strings, so a dictionary read back from one can be
passed as it is; ``highlight`` takes string IDs too. Speech bubbles may
overlap a neighbour; hovering over or tapping a member brings their bubble to
the front. Answers are shown as text; pass :class:`~markupsafe.Markup` for
HTML such as an image. ``highlight`` marks members, with built-in styles for
``"winner"`` and ``"duplicate"``, and ``note`` adds a line of text:

.. code-block:: python

    room = participant.active_sync_groups["room"]
    GroupPrompt(
        "The winning number was 2.",
        participant=participant,
        group=room,
        answers={p.id: p.var.choice for p in room.participants},
        highlight={winner.id: "winner"},
    )

The ``lowest_unique_number`` demo uses both.

Without ``group``, the prompt shows the participant's group of type
``group_type``, or their only group. A participant who is no longer in it,
for example because a barrier removed them for being late, sees just the
text, so the prompt itself needs no special case on pages that a late
player may still reach; the page's other content, such as a round's
outcome, may still need one. The members who stay see the removed player
faded in their seat, labelled "(out of time)" if a barrier removed them for
being late, "(left)" if they failed or left the experiment, and "(dropped
out)" otherwise. Players who moved on to their next group, such as next
round's pair at a :class:`~psynet.sync.Regrouper`, are no longer shown, and
neither are leavers of groups that accept top-ups, such as a lobby.
Removing a member with :meth:`~psynet.sync.SyncGroup.remove_participant`
accepts a ``reason`` (``"moved_on"`` or ``"out_of_time"``) for these labels.

Trial makers
~~~~~~~~~~~~

A trial maker with ``sync_group_type`` gives the whole group the same trials.
Each group has a randomly chosen leader. PsyNet assigns the leader's next node
as if the leader were taking the trial maker alone, and the other members get
trials on the same node. The start of every trial is synchronized; add
:class:`~psynet.sync.GroupBarrier` elements inside the trial, as in
``show_trial`` above, to synchronize other points.

``sync_group_wait_content`` sets the waiting message for the trial maker's own
waits. Grouper and barrier waits use their own ``content``, so pass the same
text to each if the messages should match.

Custom barriers
~~~~~~~~~~~~~~~

To release participants by another rule, subclass
:class:`~psynet.sync.Barrier` and implement
:meth:`~psynet.sync.Barrier.choose_who_to_release`, which returns the waiting
participants to release. Override
:meth:`~psynet.sync.Barrier.would_release` to match, and use
:meth:`~psynet.sync.Barrier.check_waiting_participants` for any preparation
with side effects.

Waiting and dropouts
--------------------

Timeouts
~~~~~~~~

``max_wait_time``
    The longest a participant waits at one grouper or barrier: 20 seconds by
    default, or ``timeout_between_barriers_time`` plus 20 seconds at a
    :class:`~psynet.sync.GroupBarrier` that sets it. At a grouper, a participant who waits longer is failed. At a
    :class:`~psynet.sync.GroupBarrier`, ``max_wait_action`` decides:
    ``"fail"`` (default) fails the participant, and ``"kick"`` removes them
    from the group so that they continue alone. This also applies to a
    participant who closed the page while waiting, including on
    ``waiting_logic`` pages: the server applies the timeout shortly after
    the deadline.

    ``max_wait_time`` is a hard limit counted from arrival. With
    ``waiting_logic``, the server applies it even while the participant is
    partway through a filler page, not only between filler pages. Make it
    long enough to cover long filler pages, for example trials used as
    filler.

``timeout_between_barriers_time`` (default: ``None``)
    A :class:`~psynet.sync.GroupBarrier` limit on the time since the group
    passed its previous barrier, or since the member joined the group if that
    is later. A member who has not reached this barrier in time is handled by
    ``timeout_between_barriers_action``, ``"fail"`` (default) or ``"kick"``.
    Members who arrive promptly may wait this long for the others, so the
    barrier's ``max_wait_time`` must be longer; it defaults to 20 seconds plus
    this timeout. This guarantee assumes fixed membership: in a group that
    accepts top-ups, a newcomer is timed from when they joined, so members
    already waiting can reach ``max_wait_time`` first.

    At a group's first barrier the timeout counts from when the group formed.
    Size it to cover everything between the grouper and that barrier, such as
    instructions or a practice trial, or members who read slowly are timed
    out before they arrive.

Trial makers with ``sync_group_type`` take the same settings with a
``sync_group_`` prefix: ``sync_group_max_wait_time`` (default 45 seconds),
``sync_group_max_wait_action``, ``sync_group_timeout_between_barriers_time``
and ``sync_group_timeout_between_barriers_action``. As with a barrier,
``sync_group_max_wait_time`` must be longer than
``sync_group_timeout_between_barriers_time``, so raise it when you set a
between-barrier timeout of 45 seconds or more.

Choose ``max_wait_time`` at the grouper together with how quickly you
recruit, because a participant is failed if too few others arrive while
they wait. To lose fewer than 1 in 20, expect at least 1.3 times the group
size to arrive within one ``max_wait_time``. For groups of three, that is
about 12 participants a minute with the default 20 seconds, or 2 a minute
with ``max_wait_time=120``. In one test with groups of three and about 3
arrivals a minute, the grouper failed 45% of participants with a 20-second
wait and none with 120 seconds. When recruitment stops, up to one fewer than
the group size are left without a group and are failed.

At later barriers, ``max_wait_time`` needs to cover how much longer some
members take over the previous page than others. A member who times out
there can take the group below ``min_group_size``, with the consequences
described under *Groups below minimum size* below.

Groups below minimum size
~~~~~~~~~~~~~~~~~~~~~~~~~

When failed or departed members take a group below ``min_group_size``, what
happens depends on whether the group accepts top-ups:

- With ``join_existing_groups=True``, the group's next barrier waits for new
  members to join. If every member leaves, the group closes, and later
  arrivals form a new one.
- Otherwise the group is dissolved as soon as the member leaves, and its
  remaining members are failed. Set ``fail_participants_below_min_size=False``
  on the grouper to remove them from the group without failing them, so that
  they continue alone. A member who is in the middle of a request at that
  moment (for example submitting a page) is handled by the background
  barrier check within about a second instead, once that request finishes.

The ``sync_quorum`` demo lets participants into part of the timeline only
while at least three are present. Its grouper has no maximum size and accepts
top-ups:

.. literalinclude:: ../../../demos/experiments/sync_quorum/experiment.py
   :start-at: SimpleGrouper(
   :end-before: for_loop(
   :dedent: 12

Waiting pages
~~~~~~~~~~~~~

By default, a waiting participant stays on their current page, with input
disabled and a small waiting indicator showing ``content``. To show dedicated
pages instead, pass them as ``waiting_logic``; they repeat until the
participant is released. In ``sync_quorum``, waiting participants answer
trials from another trial maker:

.. literalinclude:: ../../../demos/experiments/sync_quorum/experiment.py
   :start-at: waiting_logic = PageMaker(
   :end-before: class Exp

When the barrier releases a participant who is on a waiting page, the page
ends ``release_grace`` seconds (default 3; see
:class:`~psynet.sync.Barrier`) after the browser notices the release, which
is usually within about 2 seconds, unless they submit it first. The page's
answer is then not saved: its response is stored with ``"interrupted": True``
in ``metadata``, its ``on_complete`` doesn't run, and ``participant.answer``
keeps its previous value (``participant.answer_is_fresh`` is ``False``).
Any other waiting pages left in the same pass of ``waiting_logic`` are
skipped, and so are all of them for the participant whose arrival completes
the group. Pass ``release_grace=None`` to :class:`~psynet.sync.Barrier`,
:class:`~psynet.sync.GroupBarrier` or a grouper to let every waiting page
run to its end. Pages inside a trial, as in ``sync_quorum``, always run to
their end, so that the trial is not left without an answer.

A waiting page's JavaScript can react to the release: ``window`` receives a
``psynetWaitingRelease`` event, with the grace period in ``detail.graceMs``,
and a ``psynetWaitingStatus`` event about every 2 seconds, with the time to
the expected release (or ``null``) in ``detail.releaseInMs``:

.. code-block:: javascript

   window.addEventListener("psynetWaitingRelease", (event) => {
     document.getElementById("note").textContent =
       "Your group is ready. Moving on in a moment…";
   });

Time credit
~~~~~~~~~~~

By default, participants are credited for the time they actually wait, up to
``max_wait_time``. Set ``fix_time_credit=True`` to credit every participant
``expected_wait`` seconds instead (1.5 seconds by default). With
``waiting_logic``, the waiting pages are credited by their own time
estimates.

.. seealso::

   The :doc:`/skills/synchronous-experiments` skill.

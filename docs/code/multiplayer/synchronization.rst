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
    group. Such groups accept *top-ups*: when a member drops out, barriers
    wait for a replacement instead of dissolving the group.

``max_group_size`` (default: ``initial_group_size``)
    The largest size a group can reach through ``join_existing_groups``;
    ``None`` means no limit. Setting it to anything else requires
    ``join_existing_groups=True``.

``join_criterion``
    A function of ``group`` and ``participant`` that returns whether the
    participant may join that group. Only used with
    ``join_existing_groups=True``.

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
returns the text or ``None`` to hide it. Notices must fit on one line:

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
    default. At a grouper, a participant who waits longer is failed. At a
    :class:`~psynet.sync.GroupBarrier`, ``max_wait_action`` decides:
    ``"fail"`` (default) fails the participant, and ``"kick"`` removes them
    from the group so that they continue alone.

``timeout_between_barriers_time`` (default: ``None``)
    A :class:`~psynet.sync.GroupBarrier` limit on the time since the group
    passed its previous barrier. A member who has not reached this barrier in
    time is handled by ``timeout_between_barriers_action``, ``"fail"``
    (default) or ``"kick"``. It has no effect at a group's first barrier.

Trial makers with ``sync_group_type`` take the same settings with a
``sync_group_`` prefix: ``sync_group_max_wait_time`` (default 45 seconds),
``sync_group_max_wait_action``, ``sync_group_timeout_between_barriers_time``
and ``sync_group_timeout_between_barriers_action``.

Groups below minimum size
~~~~~~~~~~~~~~~~~~~~~~~~~

When failed or departed members take a group below ``min_group_size``, what
happens depends on whether the group accepts top-ups:

- With ``join_existing_groups=True``, the group's next barrier waits for new
  members to join.
- Otherwise the group is dissolved as soon as the member leaves, and its
  remaining members are failed. Set ``fail_participants_below_min_size=False``
  on the grouper to remove them from the group without failing them, so that
  they continue alone.

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

Time credit
~~~~~~~~~~~

By default, participants are credited for the time they actually wait, up to
``max_wait_time``. Set ``fix_time_credit=True`` to credit every participant
``expected_wait`` seconds instead (1.5 seconds by default). With
``waiting_logic``, the waiting pages are credited by their own time
estimates.

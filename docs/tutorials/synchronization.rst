===============
Synchronization
===============

In some experiments we need to be able to synchronize certain groups of participants
to do the same things at the same time. For example, we might want to implement
a behavioral economics game where participants have to make certain kinds of decisions
and receive payouts depending on what the other participants in their group did.
PsyNet provides advanced synchronization utilities for supporting such experiments.

There are two main timeline constructs that are used to implement such synchronization.
The ``Grouper`` is responsible for creating groups of participants,
whereas the ``GroupBarrier`` is responsible for synchronizing participants within groups.

Grouper
-------

One straightforward type of ``Grouper`` is the ``SimpleGrouper``.
It may be included in the timeline as follows:

::

    SimpleGrouper(
        group_type="rock_paper_scissors",
        initial_group_size=2,
    ),

This ``SimpleGrouper`` organizes participants into groups of 2. By default it will create a new
group of 2 each time 2 participants are ready and waiting, but an optional ``batch_size``
parameter can be used to delay group formation until more participants are waiting.
Set ``fail_participants_below_min_size=False`` to release the remaining members without failing
them if a group that cannot accept top-ups drops below its minimum size.

The groups created by ``Groupers`` are represented by ``SyncGroup`` objects.
If a participant is a member of just one active SyncGroup, then it can be accessed with
code as follows:

::

    participant.sync_group

If the participant is a member of multiple active SyncGroups, then they can be accessed
via ``participant.active_sync_groups``, which takes the form of a dictionary keyed by ``group_type``.
Alternatively, within a trial one can use ``self.sync_group``
(:attr:`Trial.sync_group <psynet.trial.main.Trial.sync_group>`),
which resolves to the group matching that trial maker's ``sync_group_type``.

The read-only list of active participants within the SyncGroup can then be accessed
via ``sync_group.participants``. To update membership, use
``sync_group.add_participant(participant)`` or
``sync_group.remove_participant(participant)``.
The order of ``sync_group.participants`` is not guaranteed. If you need a stable ordering
(for example, to assign deterministic roles), sort by participant ID. A convenient pattern is to
assign roles at a ``GroupBarrier`` so all group members are present:

::

    import random

    def assign_roles(group, participants):
        roles = ["speaker", "listener", "observer"]
        random.shuffle(roles)
        assert len(roles) == len(participants)
        for participant, role in zip(participants, roles):
            participant.var.role = role

    GroupBarrier(
        id_="assign_roles",
        group_type="rock_paper_scissors",
        on_release=assign_roles,
    )


It is possible to put multiple ``Grouper`` constructs in a timeline.
If they have different ``group_type`` parameters then they will be used to create different grouping namespaces.
Groupers with the same ``group_type`` can be used to regroup the participants into different groupings
as they progress through the experiment.
However, it is not possible to be in multiple groups with the same ``group_type`` simultaneously;
one must place a ``GroupCloser`` in the timeline to close the group before assigning the participants
to a new one.


Group Barrier
-------------

A Group Barrier may be included in the timeline as follows:

::

    GroupBarrier(
        id_="finished_trial",
        group_type="rock_paper_scissors",
        on_release=self.score_trial,
    )


When participants reach this barrier, they will be told to wait until all participants in their group
are also waiting at that barrier. An optional ``on_release`` function can be provided to the barrier,
which will be executed on the group of participants at the point when they leave the barrier.


Synchronization in trial makers
-------------------------------

It is perfectly possible to use these synchronization constructs within trial makers.
In this case, it is usually wise to provide a ``sync_group_type`` argument to the trial maker,
for example:

::

    RockPaperScissorsTrialMaker(
        id_="rock_paper_scissors",
        trial_class=RockPaperScissorsTrial,
        nodes=[
            StaticNode(definition={"color": color})
            for color in ["red", "green", "blue"]
        ],
        expected_trials_per_participant=3,
        max_trials_per_participant=3,
        sync_group_type="rock_paper_scissors",
    )

This tells the trial maker to synchronize the logic of assigning participants to nodes according to their
SyncGroup. By default, each group has a randomly assigned leader; node allocation is determined
by standard PsyNet logic for that leader, as if that person were taking that trial maker by themselves;
the other participants in that group then 'follow' that leader, being assigned to the same nodes as the leader
on each trial.

Using a ``sync_group_type`` parameter means that the beginning of each trial is synchronized across all participants
within a given group. It is possible to synchronize other parts of the trial by including further
GroupBarriers within the trial, for example:

::

    def show_trial(self, experiment, participant):
        return join(
            GroupBarrier(
                id_="wait_for_trial",
                group_type="rock_paper_scissors",
            ),
            self.choose_action(color=self.definition["color"]),
            GroupBarrier(
                id_="finished_trial",
                group_type="rock_paper_scissors",
                on_release=self.score_trial,
            ),
        )

Timeouts
--------

PsyNet provides two mechanisms for letting participants advance when others in their group are unresponsive:

``max_wait_time`` (default: 20 seconds)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This ``GroupBarrier`` parameter specifies the maximum time period that a participant can wait at the barrier before
being released automatically. By default, participants who exceed this timeout are failed. Set
``max_wait_action="kick"`` to remove them from the group instead, allowing them to continue outside that group.

``timeout_between_barriers_time`` (default: ``None``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This ``GroupBarrier`` parameter handles participants who fall behind between successive group barriers. If set to a
number of seconds, PsyNet measures from the time the group collectively passed the previous barrier. Any active group
member who has not reached the current barrier within that interval is handled according to
``timeout_between_barriers_action``, which can be ``"fail"`` (default) or ``"kick"``.

Trial makers with ``sync_group_type`` expose the same behavior with prefixed parameters.
Their barrier wait controls are ``sync_group_max_wait_time`` (default: 45 seconds) and
``sync_group_max_wait_action``; their between-barrier controls are
``sync_group_timeout_between_barriers_time`` and ``sync_group_timeout_between_barriers_action``.


Demo
----

Several demos are available that illustrate these features, see below.

Rock, paper, scissors
^^^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../../demos/experiments/rock_paper_scissors/experiment.py
   :language: python

Synchronized GSP
^^^^^^^^^^^^^^^^

.. literalinclude:: ../../demos/experiments/gibbs_within_sync/experiment.py
   :language: python


Quorum
^^^^^^

.. literalinclude:: ../../demos/experiments/sync_quorum/experiment.py
   :language: python

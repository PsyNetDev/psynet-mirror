Synchronization internals
=========================

This page covers how :mod:`psynet.sync` evaluates barriers. Experiment
authors use the public interface described in
:doc:`/code/multiplayer/synchronization`.
:ref:`timeline-hold-traces` lists the concurrent interleavings that tests
must cover.

Releasing participants
----------------------

The browser receives a WebSocket notification when a barrier releases, and
makes occasional HTTP checks as a fallback.

When the last needed member arrives, PsyNet commits the arrival and then
evaluates the barrier in a short coordination transaction, before rendering
the response. A :class:`~psynet.sync.SimpleGrouper` can therefore form the
group immediately, and a :class:`~psynet.sync.GroupBarrier` releases the
partners without waiting for the poller. The last participant to arrive
skips the wait indicator and continues to the next page. If a partner's wait row, or the row
of a group that accepts top-ups, stays locked, the regular 0.5-second barrier check completes
the release instead.

.. _sync-barrier-poller:

The barrier poller
------------------

The clock process runs :func:`~psynet.sync.check_barriers` every
0.5 seconds. It splits the pools of a :class:`~psynet.sync.Regrouper` with
``every``: an arrival there cannot make the pool ready, so the arrival doesn't
queue a check of the pool. For arrivals submitted with Next, the poller makes a
due split at its next check, normally within a second. An arrival or reload in
``GET /timeline``, or a bot's poll, still checks the waiter's visit (see
`issue #1159 <https://gitlab.com/PsyNetDev/PsyNet/-/issues/1159>`__). A browser's safety poll on the
wait page (``timeline_hold_resume``) does not check the barrier for a hold
that isn't released yet. The poller is also a backstop: for a release whose
request-side check was deferred or lost, for barriers with explicit
``waiting_logic`` (whose wait pages don't check the barrier), and for waiters
who have left.

Each sweep first tries again to dissolve groups marked ``dissolving``. It
then applies ``max_wait_time`` to waiters whose deadline has
passed, since nobody else would: their own request normally does it. This
covers waiters at the default wait indicator and at explicit
``waiting_logic`` pages, whose link records its own deadline, even if they
are still partway through a filler page. It then checks waiting visits in
the order they became due, with a 5-second head start for visits that
are new or whose waiters, or sync group's activity, size or leader,
changed since this process last checked them. A visit whose group's other
members changed, for example by starting a timed page, whose group's
dissolving, top-up, quorum or last barrier pass state changed, or whose
clocks a bot helper such as :func:`~psynet.bot.make_late_now` moved back,
is due at once but without the head start: which of a group's visits is checked first can decide who
is released, for example when members are late. An unchanged visit whose last check released
nobody is due when its barrier says a release could next become due: the
next time a member becomes late, a ``top_up_wait`` or ``newcomer_max_wait``
runs out, a :class:`~psynet.sync.SimpleGrouper` can start short, or a
:class:`~psynet.sync.Regrouper` deadline or tick comes (see
``Barrier._next_check_due``). Until then it is checked again every 10
seconds, in case that time missed something the release depends on, but
only after the visits that are due, so that with many waiting visits these
re-checks don't delay due releases; while the poller is saturated they come
later than 10 seconds. If such a re-check releases anyone, the poller logs a
warning naming the barrier, because that release came late: its
``_next_check_due``, or what the poller fingerprints, missed something.
Other barriers, including subclasses that
override how a barrier releases without saying when, are due at every sweep,
and so are visits whose check was deferred or failed. A visit whose check is
deferred or fails is retried at most
once in the same sweep and then queued like a checked one, and a waiter
whose timeout fails goes behind the other overdue waiters, so a broken item
cannot hold up the rest. Each of
the two steps stops starting new work after 0.2 seconds, so with thousands
of waiters a sweep normally stays within its interval and later sweeps reach
the remaining visits. One timeout or check can still overrun while it waits
for a row lock.

.. _sync-group-lock-order:

Sync group lock order
---------------------

Barrier checks and participant requests take their locks in this order:

1. The barrier visit's advisory claim, held on a separate database
   connection for the length of the check.
2. Participant rows. A barrier check locks the waiters' barrier links and
   rows with ``NOWAIT``; a participant's own request locks their own row,
   waiting for it.
3. The sync group row, ``FOR NO KEY UPDATE``. Joins inside barrier checks,
   :func:`~psynet.sync.check_sync_groups`, the poller's retry of a
   dissolution and a :class:`~psynet.sync.Regrouper` closing a cohort
   (``stop_top_ups_after_rounds``) use ``SKIP LOCKED``. A :class:`~psynet.sync.GroupBarrier`
   check takes the row of each waiting group that accepts top-ups with
   ``NOWAIT``, so that a busy group defers the check. A newcomer's own
   request waits up to a second for an open group (see below). A member who leaves or fails changes the group
   with an ``UPDATE``, which waits up to ``timeline_lock_timeout_seconds``.
   A synchronized trial maker recording a run's choices in the group's
   ``trial_maker_runs`` also waits for the row, after locking any
   participant rows it needs.
4. The unique index on a group's rounds (``sync_group_round``), on which
   a cue that creates a round waits for another request creating the same
   round, so that members cueing at once share one round; the later insert
   does nothing and loads the earlier one's round. Neither the round nor
   the trial has a foreign key to the group row, so cues take no lock on
   it. Releases and dissolution don't need a round lock: a barrier waits
   for every admitted member, so none of them can still be about to cue the
   round it closes, and dissolution reads the rounds under the members' row
   locks.
5. Members' rows when dissolving the group, with ``SKIP LOCKED``, then the
   rows of links, trials and nodes, and of other groups. A between-barrier
   timeout locks late members' rows (also ``SKIP LOCKED``) earlier, in
   :meth:`~psynet.sync.GroupBarrier.check_waiting_participants`. This can't
   deadlock: late members' rows are skipped if busy.

So, in framework code, a request holding a sync group row takes other
participants' rows only with ``SKIP LOCKED`` or ``NOWAIT``:

- Group dissolution locks the members' rows with ``SKIP LOCKED``, and is
  all or nothing. If another member's request holds their row, nobody is
  removed: the group is marked ``dissolving`` and the barrier poller tries the whole
  dissolution again on each sweep, so every member leaves the group, and
  learns why, at the same time. A group back at its quorum by then is no
  longer dissolved. Its pending members are turned away as
  ``"not_admitted"``.
- A between-barrier timeout (``late_after``) also skips busy late members,
  all or nothing as in dissolution, with either ``late_action``: removing
  only the free ones could leave the group below quorum and dissolve it
  around a busy late member, who would then leave with the group instead
  of as late. The late members are reconsidered at the barrier's next
  check, which the poller makes on each sweep, and the group waits for
  them meanwhile. Lateness is decided before the rows are
  locked, so it is decided again for the members locked: one whose request
  brought them to the barrier, or started a timed page, in between is no
  longer late. Removal writes
  the member's links and trial outcome, so without the row lock a member's
  own request could act on stale group state, for example storing an
  answer after the rest of the group moved on without them.
- ``sync_group.leader_id``, like ``participant_link_barrier.sync_group_id``
  and ``trial.sync_group_id``, has no foreign key: PostgreSQL re-checks a
  foreign key when a row written earlier in the transaction is updated
  again, and that check would wait for a request holding the leader's row.

Two members failing at the same moment therefore do not deadlock: each
fails itself, and the second request to reach the group, or else the
poller, dissolves it. Author callbacks that run under these locks, such as
``on_release``, are not bound by the rule: if one locks other rows, it
can deadlock, and PostgreSQL then aborts one of the transactions. The rule
also does not order rows of *different* sync groups, so participants in
several groups at once, failing together, can deadlock in the same way.

Joining an open group (``join_existing_groups=True``) locks the group row
and re-counts its members under that lock, so two newcomers can't both take
its last place; a busy group is skipped for the next candidate. Each
candidate is locked in a savepoint, rolled back unless the newcomer joins
that group, so a joiner holds at most one group row. A
:class:`~psynet.sync.GroupBarrier` check holds the same lock, and reloads
the group's members under it, while it decides, so a newcomer joins either
before the check counts them or after it commits. If no free group has
room but one was busy, the newcomer's own request waits up to a second for
the best busy one, instead of waiting at the grouper for the barrier
poller. That lock is taken in a savepoint too, so a busy group found full
after the wait is released. The wait can't deadlock only because it holds
no other group's row: the newcomer has no link in the group yet, so whoever
holds the group's row has no reason to lock the newcomer's. Joins inside barrier
checks don't wait. The poller can still make a join that waits: after a
check, it moves the waiters it released on through their timelines, and a
waiter who reaches a grouper joins as their own request would. So it can
wait up to a second per waiter, outside its 0.2-second budget.

A barrier check that finds a waiter or a group busy is rolled back and
deferred: the last arrival retries it once, and the poller retries it in
the same sweep and again on later ones. PostgreSQL logs each such
``NOWAIT`` miss as an error (see :ref:`deploy_troubleshooting_lock_errors`),
and PsyNet logs at ``DEBUG`` that it deferred the check.

Barrier evaluation and participant locking belong to the framework and are
not extension points. Custom barriers override
:meth:`~psynet.sync.Barrier.check_waiting_participants`,
:meth:`~psynet.sync.Barrier.choose_who_to_release` and
:meth:`~psynet.sync.Barrier.would_release` only.

.. _sync-reconstructed-barriers:

Reconstructed barriers
----------------------

PsyNet persists the release behavior of each active waiting pool as a
versioned declarative specification
(:func:`~psynet.barrier_spec.barrier_from_spec_json`). Barrier checks,
``on_release`` and arrival-message lookups run on a barrier reconstructed
from that specification, not on the live timeline object. Custom attributes
read by the release hooks must therefore hold JSON-compatible values,
supported callables, classes, or persisted PsyNet ORM records.

The reconstructed barrier has ``id``, custom release state, scalar
presentation fields (``waiting_message`` and the timeouts) and notification
settings. Wait-page construction (``waiting_logic``, ``waiting_screen``,
``_uses_timeline_hold`` and the expected repetitions of ``waiting_logic``)
stays on the live timeline object, as
do :meth:`~psynet.sync.Barrier.receive_participant` and arrival
notification. :class:`~psynet.sync.Barrier` documents which methods are
live-only.

The overlay text may differ between participants in one pool, because it
doesn't affect release behavior. A barrier ID identifies one release
behavior, so PsyNet rejects a timeline that uses the same ID for two
different behaviors when the experiment is constructed.

Arrival notices
---------------

The browser opens the live-update WebSocket for arrival notices only while
the participant is in an active sync group, or has a removal notice for the
current page. Hold pages reuse the hold-channel socket instead.

Arrivals in concurrent requests don't see each other's uncommitted links, so
a count read in the arriving request can be too low. Arrival and departure
updates therefore carry no counts: they ask the browser to fetch
``/timeline/arrival_notice`` (:func:`psynet.sync.arrival_notice_payload`)
again. That request starts after the update's commit, so the response to the
last update counts every arrival. Responses can come back out of order, and
the browser drops any response to an earlier request than one it has shown.
The response also has the seats of the members waiting in each of the
participant's groups, for the ticks of :class:`~psynet.group_prompt.GroupPrompt`,
and of those among them whose latest timed page ran out of time
(``ParticipantLinkBarrier.ran_out_of_time``), who get a dash. Pages record
the time-out as it happens in ``Participant.timed_out_since_barrier``, which
the next barrier copies onto the visit and clears; waiting pages and a trial's
feedback pages leave it alone (``Page._time_limit_counts``; the feedback page
maker marks the pages it makes with ``_trial_feedback``).
Hold overlays for members who are already waiting are still sent with the
update, so their counts can lag until the next arrival.

Waiting pages
-------------

``Participant.waiting_barrier_id`` names the barrier whose
``waiting_logic`` the participant is in. The barrier sets it on arrival,
and a step after the waiting logic hands it back to the enclosing barrier,
if any. A page tests it, not where the page came from, to decide whether a
release may end it, and whether its time limit counts for the group's
dashes and between-barrier timeout. Page makers can show waiting pages
again outside the waiting logic, so the page itself can't tell.

Time credit
-----------

Default holds credit the visible waiting time, including the interval
between the server release and the browser resuming, up to
``max_wait_time``. Progress uses the estimated duration, so participants who
arrive early do not appear further through the experiment. When
``expected_wait`` is omitted, a default hold expects 1.5 seconds and
``waiting_logic`` three passes. A given ``expected_wait`` sets the expected
repetitions of ``waiting_logic`` to ``ceil(expected_wait / estimate_duration(waiting_logic))``
(at least one), so progress can slightly exceed ``expected_wait``.

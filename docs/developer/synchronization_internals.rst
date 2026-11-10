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
skips the wait indicator and continues to the next page. If a partner's wait row is locked,
the regular 0.5-second barrier check completes the release instead.

.. _sync-barrier-poller:

The barrier poller
------------------

The clock process runs :func:`~psynet.sync.check_barriers` every
0.5 seconds. It splits the pools of a :class:`~psynet.sync.Regrouper` with
``every``: an arrival there cannot make the pool ready, so it doesn't check
the pool. For real browsers the poller makes a due split at its next check,
normally within a second; a waiter's page reload (``GET /timeline``) or a
bot's poll also checks the waiter's visit. A browser's safety poll on the
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
are still partway through a filler page. It then checks waiting visits,
least recently checked first, with a 5-second head start for visits that
are new or whose waiters or sync group changed since this process last
checked them. A visit whose check is deferred or fails is retried at most
once in the same sweep and then queued like a checked one, and a waiter
whose timeout fails goes behind the other overdue waiters, so a broken item
cannot hold up the rest. Each of
the two steps stops starting new work after 0.2 seconds, so with thousands
of waiters a sweep normally stays within its interval and later sweeps reach
the remaining visits. One timeout or check can still overrun while it waits
for a row lock.

Sync group lock order
---------------------

Every participant request locks its own participant row first, and may then
change its sync group, for example when that participant fails or leaves. So
code holding a sync group row must never wait for *another* participant's
row:

- Group dissolution locks the members' rows with ``SKIP LOCKED`` and is all
  or nothing. If another member's request holds their row, nobody is removed
  (the rows that were free are unlocked again, by rolling back a savepoint):
  the group is marked ``dissolving`` and the barrier poller tries the whole
  dissolution again on each sweep, so ``on_dissolve`` runs once, with every
  member waiting at the barrier. A group back at its quorum by then is no
  longer dissolved.
- A between-barrier timeout with ``"fail"`` also skips busy late members;
  they are still late at the barrier's next check. ``"leave_group"`` only changes the
  group's links, so it does not lock the member's row.
- Re-electing a leader picks only a member whose row is free, because the
  foreign-key check on ``leader_id`` locks the new leader's row.
- Barrier checks lock waiters with ``NOWAIT`` and defer if one is busy.
  PostgreSQL logs each such miss as an error (see
  :ref:`deploy_troubleshooting_lock_errors`), and PsyNet logs at ``DEBUG``
  that it deferred the check.
- Joining an open group (``join_existing_groups=True``) locks the group row
  with ``SKIP LOCKED`` and re-counts its members under that lock; a busy
  group is skipped for the next candidate.

Two members failing at the same moment therefore do not deadlock: each
fails itself, and the second request to reach the group, or else the
poller, dissolves it.
The rule does not order rows of *different* sync groups, so participants in
several groups at once, failing together, can still deadlock, in which case
PostgreSQL aborts one of the transactions.

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
the next barrier copies onto the visit and clears; waiting pages leave it
alone.
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

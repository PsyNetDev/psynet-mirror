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
partners without waiting for the poller. The last arriver skips the wait
indicator and continues to the next page. If a partner's wait row is locked,
the regular 0.5-second barrier check completes the release instead.

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
presentation fields (``content`` and the timeouts) and notification
settings. Wait-page construction (``waiting_logic``, ``_uses_timeline_hold``,
``waiting_logic_expected_repetitions``) stays on the live timeline object, as
do :meth:`~psynet.sync.Barrier.receive_participant` and arrival
notification. :class:`~psynet.sync.Barrier` documents which methods are
live-only.

Overlay copy may vary between participants in one pool; it is not part of
the behavior identity. A barrier ID identifies one release behavior, so a
timeline that lists the same ID with two different behaviors is rejected
when the experiment is constructed.

Arrival notices
---------------

The browser opens the live-update WebSocket for arrival notices only while
the participant is in an active sync group. Hold pages reuse the hold-channel
socket instead.

Time credit
-----------

Default holds credit the visible waiting time, including the interval
between the server release and the browser resuming, up to
``max_wait_time``. Progress uses the estimated duration, so participants who
arrive early do not appear further through the experiment. When
``expected_wait`` is omitted, it is ``0.5 * waiting_logic_expected_repetitions``
seconds (1.5 seconds by default).

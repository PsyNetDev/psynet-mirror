.. _timeline-hold-traces:

Timeline-hold traces and invariants
===================================

This page is a checking tool, not a proof. Last-arrival skip, overlay
resume, Redis pins, and the 0.5 s poller are concurrent. These traces
name the interleavings tests must witness. If a test constructs a state
the server cannot reach (for example a “ready” barrier hold whose
``active_barriers`` link is still unreleased), it does not support the
trace.

The lock protocol itself is in :ref:`timeline-hold-resume-protocol`.
This page only lists **who may hold what, in which order**.

Resources
---------

Four resources matter. A request may hold more than one at once.

Waiter row
    PostgreSQL ``FOR UPDATE`` on ``participant``. Last-arrival skip and
    a ready hold-resume both take it with ``NOWAIT``. An unready overlay
    check must not take it.

Visit claim
    Extra-connection transaction lock on the barrier instance. Last-arrival
    holds it through skip. Unfilled waiter GETs may try it but must not wait.

Follow pin
    Redis. Parks wake **publish** while a GET follows a visit. Unfilled
    waiter GETs may take it. The 0.5 s poller may still process the barrier.

Render pin
    Redis. Parks poller **processing and publish** for visits this request
    actually released, until HTML/JSON render returns.

``Participant.active_barriers`` is only unreleased links. After the
release commit, the overlay’s ``is_ready_to_resume`` is true because the
link is gone. Pin lookup therefore uses ``barrier_links``, which still
include released rows.

Traces
------

T1 — Unready overlay during last-arrival skip
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The partner is still waiting. Last-arrival has not committed a release.

.. code-block:: text

   overlay POST                 last-arrival GET              locks / pins
   ------------                 ----------------              ------------
   skip_write, no row lock  ->  follow-pin, arrival commit
                                check, skip NOWAIT            waiter row free
                                first-paint action page

Witness:
``test_unready_hold_resume_does_not_lock_the_waiter_row``,
``test_last_arrival_releases_waiters_during_unready_hold_resume``,
``test_process_response_unready_hold_resume_does_not_lock_or_recheck``.

T2 — Ready overlay after release commit, before skip
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is the Playwright entry-skip failure: first HTML was
``_BarrierHoldPage``. Last-arrival has committed ``released=True``.
The overlay websocket ``onOpen`` POSTs hold-resume. The skip has not
yet taken waiter ``NOWAIT``.

.. code-block:: text

   overlay POST                 last-arrival GET              locks / pins
   ------------                 ----------------              ------------
                                follow-pin, arrival commit
                                check, release commit         render pin on
                                ---- pause here ----
   looks ready (link gone)
   skip_write if pinned     ->  skip NOWAIT succeeds
                                first-paint action page

If the overlay took ``FOR UPDATE`` here, skip would miss twice and
first-paint the live hold.

Witness:
``test_ready_hold_resume_skips_write_while_last_arrival_pin``
(follow and render),
``test_last_arrival_skips_while_ready_partner_hold_resume_overlaps``.

T3 — Stale hold uuid while a pin is still set
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Skip already rotated ``participant.page_uuid``. The overlay still
posts the old hold uuid. Last-arrival may be in a later stacked check
that still needs waiter ``NOWAIT``.

Witness:
``test_stale_hold_resume_skips_write_while_last_arrival_pin``.
Catch-up without a pin remains
``test_stale_hold_resume_approves_the_current_page_after_last_arrival``.

T4 — Timeout or fail under a live pin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Timed-out, failed, and redirected holds must still take
``FOR UPDATE NOWAIT`` and settle. A pin must not strand them on
``skip_write``.

Witness:
``test_timed_out_hold_resume_still_writes_under_last_arrival_pin``.
Ready resume without a pin:
``test_process_response_ready_hold_resume_locks_with_nowait``,
``test_ready_hold_resume_does_not_wait_when_participant_row_is_locked``.

T5 — Visit-claim wait times out
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Last-arrival would release, but waiting for the extra-connection claim
hits ``lock_timeout``. The GET returns HTTP 503, not a first-paint hold.

Witness:
``test_last_arrival_claim_timeout_returns_busy_503``,
``test_last_arrival_waits_for_a_busy_barrier_claim``.

T6 — Unfilled waiter GET
~~~~~~~~~~~~~~~~~~~~~~~~

A waiter GET that does not fill the group must not take the render pin.
It may follow-pin and try the claim without waiting.

Witness:
``test_waiter_claim_miss_does_not_render_pin``.

T7 — Waiter ``NOWAIT`` miss
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Skip misses a locked waiter row. Last-arrival retries once, still
``NOWAIT``. A second miss first-paints the live cursor; the 0.5 s
poller finishes the skip. That is not HTTP 503.

Witness:
``test_last_arrival_retries_an_unclaimed_barrier_check_once``,
``test_last_arrival_releases_waiters_when_nowait_retry_sees_unlocked_row``.

Invariants
----------

Each invariant is a test obligation. Adding a lock, pin, or resume path
without a witness here is a spec gap.

I1
    An unready hold-resume does not take the waiter row.
I2
    A ready hold-resume with no last-arrival pin takes
    ``FOR UPDATE NOWAIT`` and fails immediately if the row is busy.
I3
    After the release commit, a hold-resume whose participant has a
    follow or render pin on any ``barrier_links`` visit returns
    ``skip_write``. ``_hold_instance_id_for_page`` returning ``None``
    is expected in that state and is not a reason to lock.
I4
    I3 still holds when the submitted ``page_uuid`` is stale.
I5
    Timeout, fail, and ``pending_redirect`` ignore the pin and settle.
I6
    Last-arrival first-paints the action page when T1 or T2 overlaps
    skip, not ``_BarrierHoldPage``.
I7
    Last-arrival waits for the visit claim when ``would_release`` is
    true. ``lock_timeout`` on that wait is HTTP 503.
I8
    Unfilled waiter GETs never take the render pin.
I9
    A waiter-row ``NOWAIT`` miss is ``all_claimed=False`` plus one
    retry, not HTTP 503.

What this does not prove
------------------------

These traces do not model gunicorn listen-queue delay, Redis TTL
expiry of a crashed worker’s pin, browser reload destroying the
overlay, or author ``on_release`` raising. Playwright ``@both`` covers
in-place vs full-reload **delivery** of the same server protocol; it
is not a substitute for T2. A model checker (for example TLA+) would
be the next step if the lock and pin state machine needs a real proof.

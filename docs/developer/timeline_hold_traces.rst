.. _timeline-hold-traces:

Timeline-hold traces and invariants
===================================

This page is a checking tool, not a proof. Last-arrival skip, overlay
resume, Redis pins, and the 0.5 s poller are concurrent. These traces
name the interleavings tests must witness.

A protocol witness must establish its preconditions on a reachable
server path: live participants, real barrier links, and timeline GET or
``process_response`` against that state (not MagicMock pages). The
strongest traces pause a real GET at a transaction boundary. Sequential
``process_response`` checks still count when they use that reachable
state; they are not a substitute for a paused overlap. Going through
``route_response`` is not required. Monkeypatching ``is_ready_to_resume``,
overlaying a ready hold on an unreleased ``active_barriers`` link, or
inserting a Redis pin with ``SET`` instead of the last-arrival gate does
not support a protocol trace.

Witness lists below name the test, its file, and its kind:

* **Protocol** — live participants and barrier links, via timeline GET or
  ``process_response``. The strongest traces pause a real GET at a
  transaction boundary.
* **Pin-lookup** — may ``SET`` a Redis pin or rotate ``page_uuid`` by hand.
* **Retry-unit** — stubs a check/retry helper, or uses a dummy timeline.
* **Unit** — MagicMock or stubbed ``is_ready_to_resume`` on ``process_response``.
* **Lua** — drives Redis pins and ``_publish_wakes`` directly.

Pin-lookup, retry-unit, unit, and Lua tests may use those shortcuts.
They are not substitutes for a protocol witness.

Traces live in ``tests/isolated/test_timeline_hold_protocol.py`` (T7,
fail/redirect I5, T8 Lua), ``tests/isolated/test_sync.py``, and
``tests/isolated/test_timeline.py``. Shared request helpers live in
``tests/isolated/timeline_hold_helpers.py``.

The lock protocol itself is in :ref:`timeline-hold-resume-protocol`.
This page only lists **who may hold what, in which order**.

Resources
---------

Four resources matter. A request may hold more than one at once.

Waiter row
    PostgreSQL ``FOR UPDATE`` on ``participant``. Last-arrival skip takes
    **partner** rows with ``NOWAIT``. A ready hold-resume takes this
    waiter's row with ``NOWAIT``. Last-arrival's **own** row is a blocking
    ``FOR UPDATE`` under ``lock_timeout`` in ``_skip_ready_hold_on_get``
    and ``_run_finalized_barrier_arrivals``. An unready overlay check must
    not take it.

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

* Protocol (``tests/isolated/test_sync.py``):
  ``test_unready_hold_resume_does_not_lock_the_waiter_row``,
  ``test_last_arrival_releases_waiters_during_unready_hold_resume``.
* Unit (``tests/isolated/test_timeline.py``, stubbed ``is_ready_to_resume``):
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

* Protocol (``tests/isolated/test_sync.py``):
  ``test_last_arrival_skips_while_ready_partner_hold_resume_overlaps``.
* Pin-lookup (``tests/isolated/test_sync.py``, ``SET`` pin):
  ``test_ready_hold_resume_skips_write_while_last_arrival_pin``
  (follow and render).

T3 — Stale hold uuid while a pin is still set
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Skip already rotated ``participant.page_uuid``. The overlay still
posts the old hold uuid. Last-arrival may be in a later stacked check
that still needs waiter ``NOWAIT``.

T3 under a pin has no protocol witness.

Witness:

* Pin-lookup (``tests/isolated/test_sync.py``, ``SET`` pin and hand-rotated
  ``page_uuid``):
  ``test_stale_hold_resume_skips_write_while_last_arrival_pin``.
* Protocol without a pin (catch-up after skip):
  ``test_stale_hold_resume_approves_the_current_page_after_last_arrival``.

T4 — Timeout or fail under a live pin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On the submitted hold (matching ``page_uuid``, current element is a
hold), timed-out, failed, and redirected resumes must still take
``FOR UPDATE NOWAIT`` and settle. A pin must not strand them on
``skip_write``. Fail and ``pending_redirect`` become ready while the
barrier link is still unreleased, so ``_hold_instance_id_for_page``
still returns an id. A failed or redirected participant whose uuid is
already stale is not this trace; that POST can still take the pin
branch.

Witness:

* Protocol (``tests/isolated/test_timeline_hold_protocol.py``, matching
  uuid, live follow pin):
  ``test_fail_or_redirect_hold_resume_settles_under_live_follow_pin``.
* Pin-lookup (``tests/isolated/test_sync.py``, ``SET`` pin; timeout only):
  ``test_timed_out_hold_resume_still_writes_under_last_arrival_pin``.
* Unit (``tests/isolated/test_timeline.py``, stubbed ``is_ready_to_resume``):
  ``test_process_response_ready_hold_resume_locks_with_nowait``.
* Retry-unit (``tests/isolated/test_sync.py``, stubbed
  ``is_ready_to_resume``):
  ``test_ready_hold_resume_does_not_wait_when_participant_row_is_locked``.

T5 — Visit-claim wait times out
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Last-arrival would release, but waiting for the extra-connection claim
hits ``lock_timeout``. The GET returns HTTP 503, not a first-paint hold.

Witness:

* Protocol (``tests/isolated/test_sync.py``):
  ``test_last_arrival_claim_timeout_returns_busy_503``,
  ``test_last_arrival_waits_for_a_busy_barrier_claim``.

T6 — Unfilled waiter GET
~~~~~~~~~~~~~~~~~~~~~~~~

A waiter GET that does not fill the group must not take the render pin.
It may follow-pin and try the claim without waiting.

Witness:

* Protocol (``tests/isolated/test_sync.py``):
  ``test_waiter_claim_miss_does_not_render_pin``.

T7 — Waiter ``NOWAIT`` miss
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Skip misses a locked waiter row. Last-arrival retries once immediately,
still ``NOWAIT``, then pauses briefly and retries again. If the waiter is
still locked, it first-paints the live cursor; ``check_barriers()``
(the poller body) finishes the skip. That is not HTTP 503.

The tests below are different shapes:

* ``test_last_arrival_retries_an_unclaimed_barrier_check_once`` stubs
  ``_run_pending_barrier_checks`` so the first call returns ``False``.
  It never takes a waiter lock.
* ``test_last_arrival_releases_waiters_when_nowait_retry_sees_unlocked_row``
  rolls back a real blocker connection between the two immediate attempts.
* ``test_last_arrival_skips_when_waiter_unlocks_after_both_immediate_nowait_misses``
  keeps that lock through both immediate attempts, then drops it so a
  paused last-arrival retry can skip to the action page.
* ``test_both_nowait_misses_first_paint_live_hold_not_503`` keeps that
  lock through every attempt, then calls ``check_barriers()`` and
  asserts both participants are off the hold **before** any catch-up
  GET.

Witness:

* Protocol (``tests/isolated/test_timeline_hold_protocol.py``):
  ``test_both_nowait_misses_first_paint_live_hold_not_503``.
* Retry-unit (``tests/isolated/test_sync.py``, stubbed first check):
  ``test_last_arrival_retries_an_unclaimed_barrier_check_once``.
* Retry-unit (``tests/isolated/test_sync.py``, dummy timeline, real
  waiter lock dropped between attempts):
  ``test_last_arrival_releases_waiters_when_nowait_retry_sees_unlocked_row``.
* Retry-unit (``tests/isolated/test_sync.py``, stacked timeline, lock
  dropped after both immediate misses):
  ``test_last_arrival_skips_when_waiter_unlocks_after_both_immediate_nowait_misses``.

T8 — Overlapping pin owners
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Overlapping last-arrival requests add distinct owner tokens to the same
Redis set. One owner exiting must remove only its token, so a parked
wake stays unpublished until the last owner exits, then publishes
exactly once. A stale token after TTL expiry must not remove a later
generation.

The observable guarantee is no publication while another owner remains.
An intermediate Lua drain that sees the remaining pin and reparks is
the same outcome; deleting the shared key on first exit is the failure.

This has Lua witnesses only. Two server requests co-owning a pin on one
``BarrierInstance`` is not covered here.

Witness:

* Lua (``tests/isolated/test_timeline_hold_protocol.py``):
  ``test_overlapping_render_pin_owners_publish_wake_once``,
  ``test_stale_render_pin_owner_does_not_drop_newer_generation``.

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
    On the submitted hold, timeout, fail, and ``pending_redirect``
    ignore the pin and settle. Fail and ``pending_redirect`` have a
    protocol witness; timeout-under-pin is pin-lookup only.
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
    immediate retry, not HTTP 503. Last-arrival then pauses briefly and
    retries again. A waiter that stays locked still first-paints the live
    cursor; ``check_barriers()`` then finishes the skip without a catch-up
    GET.
I10
    Overlapping render-pin owners must not publish a parked wake while
    another owner still holds the visit.

What this does not prove
------------------------

These traces do not model gunicorn listen-queue delay, Redis TTL
expiry of a crashed worker’s pin with no later owner, browser reload
destroying the overlay, or author ``on_release`` raising. Playwright
``@both`` covers in-place vs full-reload **delivery** of the same server
protocol; it is not a substitute for T2. A model checker (for example
TLA+) would be the next step if the lock and pin state machine needs a
real proof.

T3 under a pin, timeout-under-pin, fail/redirect under a **render**
pin, and two requests co-owning a pin on one ``BarrierInstance`` have
no protocol witness. Pin lookup currently scans every
``barrier_links`` row.

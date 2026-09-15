.. _timeline-hold-traces:

Timeline-hold traces and invariants
===================================

This page is a checking tool, not a proof. Last-arrival barrier checks,
overlay resume, and the 0.5 s poller are concurrent. These traces name
the interleavings tests must witness.

A protocol witness must establish its preconditions on a reachable
server path: live participants, real barrier links, and timeline GET or
``process_response`` against that state (not MagicMock pages). The
strongest traces pause a real GET at a transaction boundary. Sequential
``process_response`` checks still count when they use that reachable
state; they are not a substitute for a paused overlap. Going through
``route_response`` is not required. Monkeypatching ``is_ready_to_resume``
or overlaying a ready hold on an unreleased ``active_barriers`` link
does not support a protocol trace.

Witness lists below name the test, its file, and its kind:

* **Protocol** — live participants and barrier links, via timeline GET or
  ``process_response``. The strongest traces pause a real GET at a
  transaction boundary.
* **Retry-unit** — stubs a check/retry helper, or uses a dummy timeline.
* **Unit** — MagicMock or stubbed ``is_ready_to_resume`` on ``process_response``.

Retry-unit and unit tests may use those shortcuts. They are not
substitutes for a protocol witness.

Traces live in ``tests/isolated/test_timeline_hold_protocol.py`` (T7,
fail/redirect I5), ``tests/isolated/test_sync.py``, and
``tests/isolated/test_timeline.py``. Shared request helpers live in
``tests/isolated/timeline_hold_helpers.py``.

The lock protocol itself is in :ref:`timeline-hold-resume-protocol`.
This page only lists **who may hold what, in which order**.

Resources
---------

Three resources matter. A request may hold more than one at once.

Waiter row
    PostgreSQL ``FOR UPDATE`` on ``participant``. Last-arrival checks take
    **partner** rows with ``NOWAIT``. A ready hold-resume takes this
    waiter's row with ``NOWAIT``. Last-arrival's **own** row is a blocking
    ``FOR UPDATE`` under ``lock_timeout`` in ``_skip_ready_hold_on_get``
    and ``_finalize_barrier_arrivals``. An unready overlay check must
    not take it. Last-arrival does not reacquire partner rows after the
    release commit.

Visit claim
    Extra-connection transaction lock on the barrier instance. Last-arrival
    holds it through the check. The poller holds it through skip-after-commit
    for waiters **it** released. Unfilled waiter GETs may try it but must
    not wait.

Hold record
    ``TimelineHoldRecord`` for the current ``page_uuid``. A hold consumed
    immediately after skipping a released wait is ``silent``, so overlay
    HTML and arrival-message replacement stay empty for that visit.

``Participant.active_barriers`` is only unreleased links. After the
release commit, the overlay’s ``is_ready_to_resume`` is true because the
link is gone. The partner's timeline cursor is still on that hold until
their own overlay POST or GET advances it.

Traces
------

T1 — Unready overlay during last-arrival check
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The partner is still waiting. Last-arrival has not committed a release.

.. code-block:: text

   overlay POST                 last-arrival GET              locks
   ------------                 ----------------              -----
   skip_write, no row lock  ->  arrival commit
                                check, waiter NOWAIT          waiter row free
                                first-paint next page or
                                silent catch-up hold
                                partner cursor unchanged

Witness:

* Protocol (``tests/isolated/test_sync.py``):
  ``test_unready_hold_resume_does_not_lock_the_waiter_row``,
  ``test_last_arrival_releases_waiters_during_unready_hold_resume``.
* Unit (``tests/isolated/test_timeline.py``, stubbed ``is_ready_to_resume``):
  ``test_process_response_unready_hold_resume_does_not_lock_or_recheck``.

T2 — Ready overlay after release commit
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Last-arrival has committed ``released=True``. It does **not** skip the
partner cursor. The overlay websocket ``onOpen`` POSTs hold-resume. That
POST looks ready because ``active_barriers`` no longer contains the
link, takes ``FOR UPDATE NOWAIT``, and catch-up-skips this waiter.

.. code-block:: text

   overlay POST                 last-arrival GET              locks
   ------------                 ----------------              -----
                                arrival commit
                                check, release commit         wakes published
                                ---- pause here ----
   looks ready (link gone)
   FOR UPDATE NOWAIT        ->  partner advances
                                last arriver self-skips

Witness:

* Protocol (``tests/isolated/test_sync.py``):
  ``test_ready_partner_overlay_advances_after_last_arrival_release``,
  ``test_last_arrival_get_publishes_wakes_before_render``,
  ``test_last_arrival_post_does_not_skip_partner_cursors``.

T3 — Stale hold uuid after the cursor moved
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This waiter (or a later skip) already rotated ``participant.page_uuid``.
The overlay still posts the old hold uuid. That POST is catch-up, not a
multi-tab reject.

Witness:

* Protocol (``tests/isolated/test_sync.py``):
  ``test_stale_hold_resume_approves_the_current_page_after_last_arrival``,
  ``test_stale_hold_uuid_catches_up_onto_a_later_hold``.

T4 — Timeout, fail, or redirect while last-arrival is in flight
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On the submitted hold (matching ``page_uuid``, current element is a
hold), timed-out, failed, and redirected resumes must still take
``FOR UPDATE NOWAIT`` and settle. Fail and ``pending_redirect`` become
ready while the barrier link is still unreleased, so
``_hold_instance_id_for_page`` still returns an id.

Witness:

* Protocol (``tests/isolated/test_timeline_hold_protocol.py``, matching
  uuid, last-arrival paused before the check):
  ``test_fail_or_redirect_hold_resume_settles_during_last_arrival``.
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

A waiter GET that does not fill the group must try the visit claim
without waiting. A held claim is a first-paint hold, not HTTP 503.

Witness:

* Protocol (``tests/isolated/test_sync.py``):
  ``test_waiter_unfilled_get_does_not_return_busy_503_for_held_claim``.

T7 — Waiter ``NOWAIT`` miss
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The check misses a locked waiter row. Last-arrival retries once
immediately, still ``NOWAIT``. If the waiter is still locked, it
first-paints the live cursor; ``check_barriers()`` (the poller body)
finishes the **poller's** skip. That is not HTTP 503. Last-arrival does
not skip partner cursors after a miss.

The tests below are different shapes:

* ``test_last_arrival_retries_an_unclaimed_barrier_check_once`` stubs
  ``_run_pending_barrier_checks`` so the first call returns ``False``.
  It never takes a waiter lock.
* ``test_last_arrival_releases_waiters_when_nowait_retry_sees_unlocked_row``
  rolls back a real blocker connection between the two immediate attempts.
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

Invariants
----------

Each invariant is a test obligation. Adding a lock or resume path
without a witness here is a spec gap.

I1
    An unready hold-resume does not take the waiter row.
I2
    A ready hold-resume takes ``FOR UPDATE NOWAIT`` and fails immediately
    if the row is busy.
I3
    After the release commit, last-arrival does not change a waiting
    partner's ``page_uuid``. A wake is published before finalize returns.
    The partner advances on overlay POST or their own GET.
I4
    I3 still holds for last-arrival ``POST /response``. A leftover hold
    uuid on a later request is catch-up, not a multi-tab reject.
I5
    On the submitted hold, timeout, fail, and ``pending_redirect`` take
    ``FOR UPDATE NOWAIT`` and settle. Fail and ``pending_redirect`` have
    a protocol witness.
I6
    Last-arrival first-paints the action page or a silent catch-up hold,
    not authored wait copy. Partners stay on the authored overlay until
    they resume.
I7
    Last-arrival waits for the visit claim when ``would_release`` is
    true. ``lock_timeout`` on that wait is HTTP 503.
I8
    Unfilled waiter GETs try the visit claim without waiting. A held
    claim first-paints the hold, not HTTP 503.
I9
    A waiter-row ``NOWAIT`` miss is ``all_claimed=False`` plus one
    immediate retry, not HTTP 503. A waiter that stays locked still
    first-paints the live cursor; ``check_barriers()`` then finishes the
    poller's skip without a catch-up GET.

What this does not prove
------------------------

These traces do not model gunicorn listen-queue delay, a missed Redis
pub/sub hint (the overlay's 2 s safety poll and websocket on-open are
the backups), browser reload destroying the overlay, or author
``on_release`` raising. Playwright ``@both`` covers in-place vs
full-reload **delivery** of the same server protocol; it is not a
substitute for T2. A model checker (for example TLA+) would be the next
step if the lock state machine needs a real proof.

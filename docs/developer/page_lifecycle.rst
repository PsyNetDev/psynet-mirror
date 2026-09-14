Page rendering and lifecycle
============================

This document describes how PsyNet renders timeline pages, moves between them,
and manages page-owned browser resources. It is intended for maintainers adding
or changing Page, Prompt, Control, and frontend lifecycle behavior.

Two navigation modes
--------------------

PsyNet supports two ways to move between timeline pages.

Full-page navigation
~~~~~~~~~~~~~~~~~~~~

The browser requests ``/timeline`` and receives a complete HTML document.
Classic ``js_dependencies`` are emitted as blocking ``<script src>`` tags in
the head so they finish loading before ``#main-body`` scripts run. After the
document loads, PsyNet still runs the guarded loader, which skips files already
present and fails loudly if a declared dependency did not load. It then
activates page code and modules.

This path is used for the first timeline page, explicit legacy reload mode, and
page types that require a document reload.

In-place navigation
~~~~~~~~~~~~~~~~~~~

With ``inplace_timeline_transitions = true``, an approved ``/response`` request
also contains the rendered next-page fragment. The existing document remains
open while PsyNet replaces the timeline header, hold region, main body, and page
bootstrap data. The footer and Leave modal are optional and are inserted,
removed, or replaced when present.

Keeping the document open avoids a full reload, but it also means that PsyNet
must explicitly reproduce the resource cleanup and initialization that a reload
would normally provide.

Server-side rendering
---------------------

``Page.render()`` has two output shapes:

* Full mode renders the complete timeline document.
* Partial mode renders the internal ``#psynet-timeline-fragment`` payload used
  by ``/response``. Child templates that extend ``timeline-page.html`` are
  rewritten to ``timeline-fragment.html`` so Jinja does not compile Dallinger's
  layout and then throw it away. Child ``stylesheets`` extras (wait-page CSS,
  consent stylesheet links) are emitted into ``#psynet-fragment-assets``.
  Complete templates that do not extend the timeline page still render the
  full document, then extract the fragment.

Jinja translation environments are cached per locale on the Flask app, and
compiled template strings are reused, so hold-resume HTML is not dominated by
rebuilding the document shell on every request.

BeautifulSoup is not the inplace bottleneck. PsyNet skips it for fragment
roots, for full pages without ``type="module"`` scripts, and for prompt markup
that has no ``<script>``, ``<style>``, or ``<link>`` tags. Executable script
rewrites skip bodies of ``script``, ``style``, and ``template`` so JSON
bootstrap data is not mutated. Soup remains the fallback when the fragment
root cannot be extracted, and when copying tagged head CSS from a full-document
partial render.

Before extracting a partial fragment, PsyNet:

* validates the page/template contract;
* makes executable embedded scripts inert;
* includes child stylesheet extras and page CSS in the fragment assets;
* includes a fresh ``#psynet-template-data`` JSON payload.

Full-page renders apply the same contract check. They also emit
``js_dependencies`` as blocking head scripts so first-page body markup can use
those libraries before managed page JavaScript activates.

Timeline requests separate state mutation from rendering:

1. A short write transaction locks the participant, advances or records the
   timeline state, and resolves the provisional page.
2. If that phase records barrier arrivals, PsyNet commits them and evaluates
   the affected barrier instances in short coordination transactions. Hold-wake
   publishes from those inner commits wait until this stacked finalize
   finishes, so waiting partners are not notified while later checks still
   lock their rows.
3. PsyNet resolves the final page, runs ``pre_render()``, and commits any
   preparation writes, releasing locks. Remaining queued hold wakes publish
   after that commit. How ``GET /timeline`` re-reads the live cursor, skips a
   ready hold, or recovers a dropped last-arrival check is described in
   :ref:`timeline-hold-resume-protocol`.
4. HTML, JSON, or an inplace fragment is rendered in a fresh PostgreSQL
   read-only transaction with SQLAlchemy autoflush disabled.
5. PsyNet verifies that rendering created no new, dirty, or deleted ORM
   objects, then rolls back the read transaction.

``pre_render()`` is therefore the supported hook for render preparation that
needs database writes. Calling ``commit()``, flushing ORM mutations, or issuing
SQL writes from ``render()`` or templates raises an error. If another request
advances the participant between the write commit and render, HTML requests
redirect to the current timeline page. ``GET /timeline?mode=json`` returns
HTTP 409 with ``{"status": "stale", ...}``; an already committed
``POST /response`` returns a synchronization rejection so the participant can
refresh without submitting the answer twice.

Custom response processing
~~~~~~~~~~~~~~~~~~~~~~~~~~

Overrides of :meth:`~psynet.experiment.Experiment.process_response` run in the
write phase and must return :class:`~psynet.experiment.ResponseResult`.
``ResponseResult.payload`` contains the response data, ``page`` retains the
resolved page for post-commit rendering, and ``flask_response`` can bypass the
normal payload path. The method takes a keyword-only
``timeline_hold_resume`` flag (default ``False``). Overrides should accept
``**kwargs`` (or that keyword) so ``POST /response`` can pass it. For
example::

    from psynet.experiment import ResponseResult

    def process_response(self, *args, **kwargs) -> ResponseResult:
        result = super().process_response(*args, **kwargs)
        result.payload["custom_status"] = "ready"
        return result

The former ``response_approved`` and ``render_partial_timeline_payload`` hooks
are no longer part of this pipeline. Put database preparation in
``pre_render()``, customize response data through ``ResponseResult``, and keep
``render()`` read-only.

Participant-facing write phases use a bounded PostgreSQL ``lock_timeout`` so
unexpected contention fails safely instead of occupying a web worker
indefinitely. ``GET /timeline?mode=json`` and ``POST /response`` return
HTTP 503 with a JSON ``busy`` payload so the browser and automated drivers can
retry. Browser HTML ``GET /timeline`` returns an HTML 503 page that refreshes
automatically. Hold-resume submissions retry a busy 503 once in the same
POST. If that retry is also busy, the browser schedules one delayed queued
hold wake. A further busy response reschedules the hold safety poll instead of
retrying immediately, so the browser cannot livelock on contention. Whole timeline requests are not retried
automatically on the server because author code blocks may contain
non-idempotent external side effects. Barrier definitions and per-group visit
instances are created in the arrival request's transaction. Each instance
stores a versioned JSON specification of its release behavior rather than an
opaque Python-object snapshot. The poller claims an instance with an advisory
transaction lock, rather than locking mutable metadata that another request
needs to update. When the last participant
arrives at a barrier, PsyNet commits the normal write phase and evaluates the
barrier in a short coordination transaction before rendering. This preserves
the fast route without holding partner rows through author code or
``pre_render()``. Released hold waiters are then skipped one at a time after
that check commits, so a partner ``GET /timeline`` can lock its own row.
The visit claim is held on a second connection's transaction lock until that
skip finishes, so last-arrival ``GET /timeline`` still waits for the same key
after waiter row locks drop. The ORM session does not take that key while the
extra transaction is open. A blocking wait for that claim that hits
``lock_timeout`` returns HTTP 503 rather than first-painting the live hold.
Websocket wakes from those coordination commits stay unpublished
until the last arriver finishes rendering the next page, so a waiting partner
is not told to resume while a later entry check still holds their row or while
that request is still building HTML. A GET follow-pins queued visits
before the arrival commit (publish park only) so the 0.5 s poller cannot
publish in the gap after that commit. After a request actually releases
waiters, it takes a Redis render pin until that response is ready so the
poller does not process or publish those visits during HTML render. Park
and unpin are atomic Redis scripts: a wake cannot be appended after the
last pin is gone with nobody left to drain it. Unfilled waiter GETs never
take the render pin, so the poller can still finish those barriers.
Last-arrival waits for the instance
advisory claim the poller uses, then locks waiters with ``NOWAIT``. If a waiter
row is still busy, the request retries that check once immediately (still
``NOWAIT``). It does not wait for the other request to commit; if the retry
still misses, the 0.5 s poller finishes the skip. SAVEPOINT releases inside a
check are not treated as durable commits for those wakes; a later root
rollback discards them. The barrier poller locks waiters with
``FOR UPDATE NOWAIT`` so a participant write cannot stall other groups; if any
waiter is busy, that barrier is skipped until the next tick. When a release
advances waiters onto the next stacked hold, the same poller sweep processes
that new visit before publishing wakes, so those partners do not hold-resume
onto each remaining barrier one tick at a time. The sync-group
recount job likewise skip-locks one group at a time.

The fragment must contain the elements the persistent document replaces:

* ``#timeline-header``
* ``#timeline-hold-region``
* ``#main-body``
* ``#psynet-template-data``

``#footer`` and ``#early-exit-modal`` are optional. Pages that hide the footer
or have nothing to put in it omit those nodes; the client inserts, removes, or
replaces them instead of requiring them.

Page bootstrap data
-------------------

``#psynet-template-data`` is the server-to-browser contract for the active
page. It includes page metadata, ``js_vars``, event definitions, media requests,
managed JavaScript resources, routes, feature flags, and localized strings.

On an in-place transition, ``psynet.refreshTemplateData()`` updates the
persistent JavaScript object from the newly inserted JSON element before any
new-page behavior is activated.

In-place transition sequence
----------------------------

The browser transition has three phases.

1. Deactivate the old page
~~~~~~~~~~~~~~~~~~~~~~~~~~

PsyNet:

* stops the current trial and its timers;
* runs cleanup returned by ``js_page_modules`` in reverse activation order;
* stops page media and invalidates outstanding media loads;
* clears Lucid termination state;
* runs registered page cleanup callbacks and event-listener cleanup;
* resets page-scoped response and JavaScript state.

2. Commit the new fragment
~~~~~~~~~~~~~~~~~~~~~~~~~~

PsyNet validates the fragment shape, preloads linked stylesheets, applies
page-local styles, and replaces the four persistent timeline elements.

3. Activate the new page
~~~~~~~~~~~~~~~~~~~~~~~~

PsyNet then:

1. refreshes template/bootstrap data;
2. constructs the new trial;
3. loads ``js_dependencies`` not already present in the document;
4. replays classic scripts embedded in rendered HTML;
5. executes deprecated ``js_links`` and ``scripts`` as classic scripts when
   present (these arguments also force a full page reload, so this path is
   mainly relevant on the resulting clean document load);
6. activates ``js_page_code``;
7. imports and activates ``js_page_modules``;
8. initializes trial progress, media, controls, and ``trialConstruct`` behavior;
9. marks the page ready and registers the ``pageReady`` trial event;
10. prepares and starts the trial, then enables response and submission.

Readiness and trial startup
---------------------------

``pageReady`` is both a browser navigation flag and a trial event. PsyNet sets
the flag before registering the event, so handlers triggered by ``pageReady``
may safely call ``nextPage()``.

Under the default event graph, automatic pages use:

.. code-block:: text

    trialConstruct → pageReady → trialPrepare → trialStart

Manual-start pages require both ``pageReady`` and ``trialManualRequest`` before
``trialPrepare``. This prevents trial-start, response-enable, submit-enable, and
auto-advance behavior from running while navigation is still blocked.

JavaScript resource categories
------------------------------

Dependencies
~~~~~~~~~~~~

``js_dependencies`` and ``get_js_dependencies()`` identify classic JavaScript
libraries loaded once per browser document. Their top-level code is not rerun
when a later page declares the same URL.

Built-in and third-party component packages can publish dependency files through
:doc:`package_static_resources` without requiring experiment-level file copies.

Page code
~~~~~~~~~

``js_page_code`` and ``get_js_page_code()`` provide short inline activation
bodies. PsyNet wraps each body in the same asynchronous activation context used
for page modules. Page code may return cleanup.

This is a convenience API for small snippets. Reusable or substantial behavior
should use a page module.

Page modules
~~~~~~~~~~~~

``js_page_modules`` and ``get_js_page_modules()`` identify ES modules with a
named ``activate(context)`` export. Modules are imported and cached normally,
while ``activate()`` runs for every hosting page.

The activation context contains ``root``, ``trial``, ``vars``, ``page``, and
``psynet``. ``activate()`` may return an asynchronous cleanup function.

Most page code and modules do not require cleanup because PsyNet already
removes page DOM, stops trial-owned resources, and resets response state.
Cleanup is needed for resources outside those boundaries, such as WebSockets,
raw timers, workers, observers, persistent global listeners, and in-flight
requests.

All ES modules must enter through ``js_page_modules``. Embedded
``<script type="module">`` tags are rejected. Page modules can use
standard ``import`` statements for further module dependencies.

Embedded HTML scripts
~~~~~~~~~~~~~~~~~~~~~

Framework templates and supported page content can contain classic ``<script>``
elements colocated with their markup.

On a full load, the browser executes them naturally, after blocking head
``js_dependencies``. For an in-place transition, PsyNet makes them inert during
rendering and replays them in DOM order after the guarded loader has fetched
any new ``js_dependencies``. Adjacent inline scripts are grouped in a
page-local function, while linked classic scripts are loaded once per document.

This mechanism is useful for short behavior tightly coupled to PsyNet-owned
Jinja macros. New Prompt and Control contributions should prefer
``get_js_page_code()`` for short snippets or ``get_js_page_modules()`` for
reusable behavior because their lifecycle and testing boundaries are explicit.
Author-owned external templates should remain markup-only.

Failure handling
----------------

Errors before fragment commit leave the old DOM visible but inactive and direct
the participant to refresh.

Errors after commit trigger a second deactivation pass so partially initialized
trial, module, media, and page state are unwound before the same refresh
boundary is shown. Transition failure UI is handled once at the response
boundary, and controls remain disabled because the browser and server may
already represent different pages.

Special transition paths
------------------------

Same-session pages
~~~~~~~~~~~~~~~~~~

Pages sharing a non-null ``session_id`` update ``psynet.page`` and dispatch
``pageUpdated`` without replacing the fragment. This supports persistent
sessions such as Unity integrations.

Document-owning pages
~~~~~~~~~~~~~~~~~~~~~

Pages can set ``requires_full_page_reload = True`` (constructor argument or
class attribute) when they own document-level state that should not
participate in fragment teardown, or as a temporary per-page opt-out while
migrating older custom frontends. PsyNet reloads when either the current or
next page sets this flag. Deprecated ``js_links`` and ``scripts`` also set
this flag automatically because classic global script semantics are not
emulated across in-place transitions.

UnityPage and JsPsychPage use this policy. Unity owns a persistent runtime;
jsPsych installs document-level interaction and hardware listeners whose
lifecycle varies across jsPsych versions. A clean document boundary is safer
than maintaining version-specific SPA cleanup.

When a transition uses a full reload, the client omits
``include_timeline_fragment`` for the leaving reload page and the server skips
rendering a fragment for the next reload page. Same-session handling takes
precedence, so Unity pages sharing a ``session_id`` can still update their
persistent session without reloading.

Timeline holds
~~~~~~~~~~~~~~

Timeline holds pause server-side advancement without replacing the visible
page. They are used by default barriers and by :func:`psynet.page.wait_while`.
Condition holds first evaluate their condition and are skipped entirely when
there is nothing to wait for.
The server advances to an internal hold checkpoint and returns hold
configuration on the page (``page.attributes.timeline_hold``) instead of a
timeline fragment. The browser updates only its
submission UUID, makes the visible controls inert, and renders a compact status
indicator in ``#timeline-hold-region``. That region is fixed-position, so the
indicator floats above the participant's content instead of reflowing it when a
hold starts or ends. It stacks below the Leave confirmation so an open Leave
dialog covers the wait chip.

The visible page retains its own ``window.pageUuid``, ``session_id``,
``requires_full_page_reload``, media, timers, and managed JavaScript until the
hold finishes. Consequently, release can still perform a same-session update
or honor the visible page's full-reload requirement. Refreshing during a hold
loads a neutral fallback page and reconnects to the same durable hold record.

Workers and barriers queue participant-targeted wake messages in the current
database transaction. PsyNet publishes the messages on that participant's hold
channel (``psynet_timeline_hold:<id>``) only after commit. Delivery is an
optimization rather than authority: the browser always submits an idempotent
resume check, and the server re-evaluates the condition. ``check_interval``
remains the bounded fallback for missed messages and arbitrary conditions
without a framework event.

When the last hold on a page ends, the browser closes the hold-channel
WebSocket. The next hold reconnects. Partner-ready notices use the same
channel; the extra arrival-update socket opens only while the participant
is in an active sync group and not already on a hold. If membership is not
already loaded, a cheap existence check decides whether to open that socket.
Redis delivery is an optimization: when that socket opens, the browser also
fetches ``GET /timeline/arrival_notice`` so a partner who arrived during
connect is still shown. Hold-resume POSTs set
``timeline_hold_resume`` so that if a partner already advanced this waiter
(rotating ``page_uuid``), the server still returns the current page for an
in-place update. A genuine reject, or a missing timeline fragment, still
reloads ``/timeline`` instead of leaving the overlay in place.

Holds emit ``timelineHoldStarted`` and ``timelineHoldEnded`` browser events.
Their ``detail.holdId`` identifies the wait. Authors that deliberately want a
separate waiting screen should use :class:`psynet.page.WaitPage` directly or
pass it explicitly as ``wait_page``/``waiting_logic``.

By default, holds credit actual participant-visible waiting time up to
``max_wait_time``. This may differ from the ``expected_wait`` used for progress,
advertised duration, and reward estimation. ``fix_time_credit=True`` restores
fixed expected credit when predictable per-participant payment is preferred.
This policy also applies to ``AsyncCodeBlock(wait=True)`` and framework
feedback/asset-processing waits because they use
:func:`psynet.page.wait_while`.
Timeout failures use ``timeline_hold:<hold_id>`` and ``fail_on_timeout`` failure
tags.

Timeline-hold resume checks use the durable hold record directly. They do not
create :class:`~psynet.timeline.Response` rows or call the internal hold page's
``process_response()``, validation, or ``on_complete()`` hooks. Analyze waiting
through ``TimelineHoldRecord`` and participant wait-time fields rather than by
counting response rows. If this waiter's later request already advanced the
cursor, the hold-resume POST still carries the hold page's uuid. The server
recognizes that uuid when it still matches this participant's hold record.
Ordinary submits and hold-resume overlays both catch up onto a later hold. An
unknown uuid is still a sync mismatch.

.. _timeline-hold-resume-protocol:

Resume protocol
^^^^^^^^^^^^^^^

Skipping a ready hold is one step, ``Experiment._advance_past_ready_holds``.
The caller must already hold the participant row. Last-arrival uses it after
the check commit so this request does not first-paint the hold it just
released; partners resume on their own hold-resume POST or ``GET /timeline``.
``POST /response`` uses it in the same write that processed the submit;
``GET /timeline`` uses it only after a dedicated relock.

Those routes do not share a lock protocol:

* Ordinary ``POST /response`` waits up to ``timeline_lock_timeout_seconds``.
  Hold-resume POSTs that still wait do not take the participant row, so
  last-arrival can lock waiters with ``NOWAIT``. Those overlay checks also
  skip ``account_wait``; wait credit is recorded when the hold actually
  resumes. A hold-resume that will advance takes the participant with
  ``NOWAIT`` so it cannot sit behind the last arriver's row lock.
  ``POST /response`` still reports ``Server-Timing`` phases
  (``process``, ``barriers``, ``render``, ``app``).
  ``GET /timeline`` reports ``lock``, ``page``, ``barriers``, ``render``, and
  ``app``. ``lock`` is the participant ``FOR UPDATE`` load; ``page`` is
  ``get_current_page`` through the first commit; ``barriers`` is hold skip
  plus last-arrival checks; ``render`` is the HTML (or JSON) body. A phase
  that never ran is omitted from the header, so a lock timeout is ``lock``
  plus ``app`` without a fake ``page;dur=0``. Browser wall time minus ``app``
  is queueing plus network. ``psynet debug local`` (Flask) is one process, so
  last-arrival and waiter POSTs cannot overlap. There is no worker-count flag
  for that Flask reloader; use ``psynet debug --legacy`` for gunicorn workers.
  ``psynet debug --legacy`` starts gunicorn; both Playwright CI jobs use that
  path. The default vs legacy *job* split is in-place vs full reload, not
  Flask vs gunicorn. Worker-pool ``queue~`` happens in both job modes: the
  last arriver's request (entry ``GET /timeline``, or a later last-arrival
  ``POST /response``) occupies one worker while each waiter POSTs hold-resume.
  Playwright hold tests set workers to the session count plus two spares.
  Remaining ``queue~``
  means the pool is still busy: two waiters leaving together can overlap
  next-page ``render``. Do not subtract that wait from overlay linger or waiter
  spread. Overlay linger is wake→end wallclock compared with
  ``max(2500ms, Server-Timing app + 800ms)``. Waiter-release spread is at most
  2200ms. ``GET /timeline`` and load-participant handler checks use 3000ms.
  A short HTTP 503 on hold-resume is ``NOWAIT``
  overlap, not a missed wake.
* After the arrival write commits, queued barrier checks run in short
  transactions.   Websocket wakes from those inner commits wait until the last
  arriver finishes rendering the next page. After that request actually
  releases waiters, it render-pins those visits in Redis for the rest of the
  request so the 0.5 s poller cannot process or publish the same wakes while
  HTML is still being built. A GET follow-pins queued visits before the
  arrival commit (publish park only) so poller publish cannot fire in that
  gap, and again before it tries the claim. Park and unpin are one Redis
  script each, so a publisher cannot leave a wake on the parked list after
  the last pin is gone. Pin INCR also sets TTL in that same script. A waiter
  GET that first-paints an unfilled hold never takes the
  render pin, so the poller can still finish that barrier. Last-arrival waits for the
  instance advisory claim (the lock the 0.5 s poller tries) so a GET does not
  first-paint a hold while the poller still owns that visit. A waiter arrival
  whose pending check would not release anyone tries that claim without
  waiting, so it does not occupy a worker in ``lock_timeout``. ``POST
  /response`` uses the same peek after the arrival write commits, as do
  checks queued after a ready-hold skip. A spec error during that peek
  leaves the group waiting instead of failing the arriver. That claim is a
  transaction lock on a dedicated connection, held until skip-after-commit
  finishes. If the last arriver's wait for that claim times out, ``GET /timeline`` returns
  HTTP 503 rather than rendering the live hold. Waiter rows stay
  ``NOWAIT``. If a partner row is still busy, that GET retries the check once
  immediately (still no lock wait). It does not wait for the other request to
  commit. If the retry still misses, the poller finishes the skip. If the
  poller already released the visit, the last arriver's claim can see zero
  waiters. The last arriver's GET expires its identity map, skips the hold it
  just cleared, and follows the live cursor. Released partners are skipped
  after the check commit, one row at a time. ``get_current_elt`` may return a new object
  for the same barrier hold when a trial page maker reconstructs the wait.
  That is still this wait, not a cursor move; comparing Python identity would
  loop until the hold times out.
* ``GET /timeline`` then re-reads the live cursor. If a partner already
  advanced this waiter, GET prepares that live page. If the hold is ready,
  GET takes blocking ``FOR UPDATE`` only after ``is_ready_to_resume`` (timeout
  and fail must not run yet), skips, commits, and re-reads again. If the hold
  is not ready, GET may recover a dropped last-arrival check without
  ``FOR UPDATE``, so the last arriver can still lock waiters with ``NOWAIT``.
  That recovery tries the visit claim and first-paints the hold on a miss; it
  does not wait for last-arrival to drop the claim. Bots POST
  ``timeline_hold_resume`` on hold overlays and pause briefly while still
  waiting, so parallel drivers do not take blocking ``FOR UPDATE`` on an
  unready hold.
  When that skip advances ``page_uuid`` during read-only render, GET returns
  302 to the same URL so the next document follows the live cursor. First-paint
  checks must wait for the following 200 HTML, not the empty redirect body.
* ``SET LOCAL lock_timeout`` expires at each of those commits, so GET
  reapplies it before the next lock or ``pre_render()``.

Leftover inactive visits are a separate path. Last-arrival keeps
``instance.active``, so it does not look up another waiting pool.
``Barrier._other_active_pool`` returns immediately in that case. An inactive
leftover with waiters migrates them onto the live visit and then evaluates
that visit's reconstructed barrier. Extra SQL belongs only on that inactive
path; see :ref:`barrier-arrival-sql-budgets`.

Bots
~~~~

Bot submissions do not request timeline fragments. Bots advance server state
and obtain the next page through the normal server-side page interface. Hold
overlays POST ``timeline_hold_resume`` so a still-waiting driver does not take
blocking ``FOR UPDATE`` on the participant row. If the overlay is still
waiting after that submit, the driver pauses briefly before the next page
instead of busy-looping ordinary Next. Timeline GETs use ``mode=json`` and
retry structured busy 503s and JSON 409 ``status: stale`` a few times so a
partner skip that briefly holds the row, or advances this waiter between
write and render, does not fail the bot. Bot POSTs retry those busy 503s
the same way. If this waiter already advanced, or
last-arrival skipped its own later hold, an ordinary POST of the previous hold
uuid is catch-up, not a multi-tab reject. Hold-resume overlays catch up the
same way so the browser can swap in place.

Adding new frontend components
------------------------------

For new Prompt and Control components:

* keep templates focused on markup;
* use ``get_js_vars()`` for serialized page configuration;
* use ``get_js_dependencies()`` for classic load-once libraries;
* use ``get_js_page_code()`` for short inline activation snippets;
* use ``get_js_page_modules()`` for per-page module behavior;
* return cleanup only for resources that survive normal PsyNet teardown;
* test initial and in-place activation when behavior depends on ordering.

Custom Page templates should use ``template_fragment_path`` or
``template_fragment_str`` and rely on the standard timeline shell.

Future direction
----------------

Embedded-script replay remains because many built-in framework macros colocate
small scripts with their Jinja markup. Removing it immediately would require a
large, breaking migration and would reduce useful locality for simple macros.

The expected long-term migration is:

1. use ``js_page_code`` or ``js_page_modules`` for all new components;
2. migrate existing built-in prompts and controls incrementally;
3. add browser coverage for each migrated component;
4. evaluate deprecating author-provided embedded classic scripts separately;
5. remove embedded-script replay only after no supported framework or author
   path depends on it.

When that condition is met, ``_make_embedded_scripts_inert()``,
``getEmbeddedScripts()``, and ``executeScriptSequence()`` can be removed.

Key implementation and test locations
-------------------------------------

* ``psynet/timeline.py`` — Page rendering and fragment extraction.
* ``psynet/templates/timeline-page.html`` — full and partial timeline shapes.
* ``psynet/resources/scripts/psynet.js`` — browser lifecycle orchestration.
* ``psynet/resources/scripts/websocket-channel.js`` — shared WebSocket channel
  framing and reconnect lifecycle.
* ``psynet/timeline_hold.py`` — durable hold state, accounting, and wake
  publication.
* ``psynet/experiment.py`` — GET hold resolution (``_resolve_get_timeline_hold``,
  ``_skip_ready_hold_on_get``) and the shared skip
  (``_advance_past_ready_holds``).
* ``psynet/sync.py`` — visit-claim waits gated by ``Barrier.would_release``.
* ``tests/isolated/test_timeline.py`` — render/fragment contracts.
* ``tests/playwright/inplace_timeline_transitions.spec.js`` — browser lifecycle
  and failure boundaries.
* ``tests/playwright/managed_page_javascript.spec.js`` — managed JavaScript in
  both transition modes.
* ``tests/playwright/legacy_page_javascript.spec.js`` — deprecated ``scripts``
  and ``js_links`` force full reloads with classic globals.
* ``tests/playwright/timeline_hold.spec.js`` — condition, timeout, refresh,
  feedback, reload, and same-session hold behavior.
* ``tests/playwright/stacked_group_holds.spec.js`` — concurrent last arrivals
  and stacked group-hold release.

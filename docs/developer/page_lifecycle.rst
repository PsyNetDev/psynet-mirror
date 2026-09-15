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
open while PsyNet replaces the timeline header, main body, footer, and page
bootstrap data.

Keeping the document open avoids a full reload, but it also means that PsyNet
must explicitly reproduce the resource cleanup and initialization that a reload
would normally provide.

Server-side rendering
---------------------

``Page.render()`` has two output shapes:

* Full mode renders the complete timeline document.
* Partial mode renders the internal ``#psynet-timeline-fragment`` payload used
  by ``/response``.

Before extracting a partial fragment, PsyNet:

* validates the page/template contract;
* makes executable embedded scripts inert;
* copies managed page CSS from the rendered head into the fragment;
* includes a fresh ``#psynet-template-data`` JSON payload.

Full-page renders apply the same contract check. They also emit
``js_dependencies`` as blocking head scripts so first-page body markup can use
those libraries before managed page JavaScript activates.

The fragment must contain the elements the persistent document replaces:

* ``#timeline-header``
* ``#main-body``
* ``#footer``
* ``#psynet-template-data``

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

Bots
~~~~

Bot submissions do not request timeline fragments. Bots advance server state
and obtain the next page through the normal server-side page interface.

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
* ``tests/isolated/test_timeline.py`` — render/fragment contracts.
* ``tests/playwright/inplace_timeline_transitions.spec.js`` — browser lifecycle
  and failure boundaries.
* ``tests/playwright/managed_page_javascript.spec.js`` — managed JavaScript in
  both transition modes.
* ``tests/playwright/legacy_page_javascript.spec.js`` — deprecated ``scripts``
  and ``js_links`` force full reloads with classic globals.

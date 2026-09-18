=====================
Upgrading to PsyNet 14
=====================

This checklist migrates an existing experiment onto PsyNet 14's default
in-place timeline transitions. It is the single source of truth for
**migration order and search targets**. Frontend patterns and full examples
live in :doc:`/tutorials/writing_custom_frontends`.

The Cursor skill ``/upgrade-to-psynet-14`` is a thin wrapper that points agents
here. When PsyNet is not available as a source checkout (typical experiment
venv), agents should fetch the published HTML version of this page rather than
looking for ``docs/*.rst`` on disk.

Also see: :doc:`/whats_new/psynet_14`,
:doc:`/experiment_development/configuration`.

0. Orient
---------

1. Run under the default ``inplace_timeline_transitions = true``.
2. If one page is temporarily blocked, pass
   ``requires_full_page_reload=True`` to that page's constructor.
3. If many pages are blocked, set ``inplace_timeline_transitions = false``
   only as a short-term experiment-wide opt-out, then keep migrating so you
   can remove it.
4. Work page by page.

To surface SPA contract errors, run ``psynet debug local`` /
``psynet test local`` and read the traceback. Incompatible pages raise one
short message that lists **error codes** in parentheses; use the glossary
below to map each code to a checklist step.

1. Find and migrate custom page templates
-----------------------------------------

Search for ``template_path=``, ``template_str=``, and
``{% extends "timeline-page.html" %}``.

Convert complete templates to fragments
(``template_fragment_path`` / ``template_fragment_str``) and supply assets via
page arguments. See :doc:`/tutorials/writing_custom_frontends`
(Custom page templates).

2. Migrate CSS
--------------

Search author-owned templates for ``<style>`` and
``<link rel="stylesheet">``.

* Stylesheet links → ``css_links`` / ``get_css_links()``
* Authored reusable styles → ``static/*.css`` + ``css_links``
* Tiny generated snippets → ``css`` / ``get_css()``

See the same tutorial section for details.

3. Find deprecated page JavaScript APIs
--------------------------------------

Search for ``js_links=``, ``scripts=``, and ``<script>`` tags in author-owned
templates or component ``external_template`` files. Classify each script
before moving it (load-once library vs per-page behavior vs short inline).

Converting the HTML template alone is not enough: leftover ``scripts=`` /
``js_links=`` still force a full-page reload and raise ``legacy_scripts`` /
``legacy_js_links`` unless you also pass ``requires_full_page_reload=True``.

4. Migrate load-once libraries
------------------------------

Move load-once classic libraries to ``js_dependencies`` /
``get_js_dependencies()``. Do not put per-page initialization there. See
:doc:`/tutorials/writing_custom_frontends` (Managing JavaScript lifecycles).

5. Migrate per-page behavior
----------------------------

Rewrite classic top-level scripts as ES modules that export ``activate``,
wired with ``js_page_modules`` / ``get_js_page_modules()``. Short snippets may
use ``js_page_code`` / ``get_js_page_code()`` instead.

See :doc:`/tutorials/writing_custom_frontends` for ``activate(context)``
examples and cleanup guidance.

6. Migrate page variables to ``psynet.var``
------------------------------------------

Replace legacy ``window`` reads of ``js_vars`` keys with ``psynet.var``.
Optionally set ``legacy_js_var_globals = error`` while testing.

PsyNet does **not** install a legacy ``window.<key>`` accessor when that
name already exists on ``window``. In the default ``warn`` mode a colliding
key (for example ``name``, ``status``, ``event``, ``history``) silently
keeps the browser's value; the page data is still available on
``psynet.var``. Page construction warns for these common collisions so they
show up in ``psynet test local`` / ``psynet debug local``. See
:doc:`/tutorials/writing_custom_frontends` and
:doc:`/experiment_development/configuration`.

7. Migrate JsPsych timelines
----------------------------

``JsPsychPage`` takes a JavaScript module URL exporting
``buildTimeline(context)``, not an HTML/Jinja template. See
``demos/experiments/jspsych``.

8. Fix timing that assumed document load
----------------------------------------

* Page setup → ``activate()`` / ``js_page_code`` (not ``DOMContentLoaded``)
* Timing gates → ``pageReady`` / ``trialConstruct``

Details: :doc:`/tutorials/writing_custom_frontends`.

9. Migrate trial-selection hooks
--------------------------------

Search custom trial makers for ``find_networks``, ``find_node``,
``prioritize_networks``, and ``custom_network_filter``.

* :class:`~psynet.trial.chain.ChainTrialMaker` subclasses now discover,
  filter, and select chains with ``find_chains``, ``custom_chain_filter``,
  and ``select_chain``. PsyNet resolves the selected chain to ``chain.head``.
* :class:`~psynet.trial.static.StaticTrialMaker` subclasses use the
  node-specific ``find_nodes``, ``custom_node_filter``, and ``select_node``
  hooks instead.
* ``custom_network_filter`` is still honoured, but construction emits a
  ``DeprecationWarning``. Replace it with ``custom_chain_filter`` on chain
  trial makers or ``custom_node_filter`` on static trial makers.
* Selection hooks may return their selected value directly or wrap it in
  :class:`~psynet.trial.main.Selection` to pass request-local context to
  ``on_trial_created``. Returning ``None`` from ``select_chain`` or
  ``select_node`` raises ``TypeError``. Return the selected object from the
  supplied ``chains`` or ``nodes`` list; a newly queried copy with the same
  id raises ``ValueError``. ``find_chains`` and ``find_nodes`` must return a
  list, ``"wait"``, or ``"exit"``; ``None`` raises ``TypeError``.
* ``select_chain`` and ``select_node`` replace ranking in
  ``prioritize_networks``. They receive a nonempty eligible list and cannot
  return ``None``, ``[]``, ``"wait"``, or ``"exit"``. Logic that emptied the
  candidate set or chose to wait belongs in ``find_chains`` or
  ``find_nodes``: call ``super()``, then filter or return ``"wait"`` /
  ``"exit"``.
* ``get_trial_class`` must return a concrete trial class. Remove unavailable
  chains or nodes in the corresponding custom filter instead of returning
  ``None``. Synchronized follower trials reuse the leader's concrete trial
  class without calling ``get_trial_class`` again.
* ``CreateAndRateTrialMakerMixin.get_non_failed_creations`` has been removed.
  Classify nodes with
  :meth:`~psynet.trial.create_and_rate.CreateAndRateTrialMakerMixin.get_creation_phases`
  and load finalized creations with
  :meth:`~psynet.trial.create_and_rate.CreateAndRateTrialMakerMixin.get_finished_creations`.
* Create-and-rate experiments with fixed creator and rater groups should
  override
  :meth:`~psynet.trial.create_and_rate.CreateAndRateTrialMakerMixin.get_participant_role`.
  The mixin then uses that role for both chain eligibility and the final phase
  check. Do not override ``get_trial_class`` from participant role alone.
  Creators only receive heads that still need creators. Raters receive heads
  that are ready for raters, and they wait or exit on heads whose creator
  slots are filled but not yet finalized. Heads that still need creators are
  not rater-eligible. A selected head that later becomes incompatible waits
  or exits instead of assigning the opposite role's trial class.
* :attr:`~psynet.trial.main.Trial.position` is now stored when the trial is
  created and counts across all concrete trial classes in a participant's trial
  maker. Previously it was calculated within each concrete trial class. Trials
  constructed outside a trial-maker state may have ``position=None``; code that
  performs arithmetic with ``position`` should handle that case explicitly.

PsyNet raises an actionable ``TypeError`` when a removed or wrong-paradigm
hook is still overridden.

10. Validate
------------

From a complete experiment directory. At minimum you typically need:

* ``experiment.py``, ``test.py``, ``constraints.txt``
* ``config.txt``, ``requirements.txt``
* ``.gitignore`` (must include ``source_code.zip``) and ``.python-version``

If you are scaffolding from scratch, see
:doc:`/tutorials/creating_a_new_experiment` or run ``psynet update-scripts``
to generate the standard support files.

.. code-block:: console

    psynet test local

``psynet test local`` checks static timeline pages for SPA contract problems
before bots run, so migration errors should appear directly in the pytest
failure. PageMaker-created pages are still checked when first rendered.

Confirm the default in-place mode works (opt-out removed if possible), page
modules activate without console errors, and cleanup runs for persistent
listeners.

PsyNet-repository Playwright coverage is optional and harness-specific.

Error codes
-----------

SPA incompatibility messages list codes such as
``(error codes: complete_template, style_tag)``. Use them to jump to the
relevant step:

* ``complete_template`` → step 1
* ``style_tag``, ``stylesheet_link`` → step 2
* ``embedded_script`` → steps 3–5
* ``legacy_js_links``, ``legacy_scripts`` → steps 3–5 (also force a reload;
  pass ``requires_full_page_reload=True`` to silence while migrating)
* ``embedded_module`` → step 5 (use ``js_page_modules``, not
  ``<script type="module">`` in HTML)
* ``dom_content_loaded``, ``window_listener_no_cleanup`` → steps 5 and 8.
  For ``window_listener_no_cleanup``, PsyNet only recognizes cleanup as
  ``return () => { ... }``, ``return function cleanup() { ... }``,
  ``psynet.addPageCleanupCallback(...)``, or ``psynet.addPageEventListener(...)``.
  Returning another function reference (for example ``return teardown``) is not
  detected.
* ``jspsych_html_timeline`` → step 7

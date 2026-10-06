======================
Upgrading to PsyNet 14
======================

This checklist migrates an existing experiment onto PsyNet 14: in-place
timeline transitions, recruiter and leave APIs, changed defaults, setup and
deployment files, participant failure, groups, assets and exports. Work
through the steps in order; each lists what to search for. Frontend patterns
and full examples are in :doc:`/code/pages/custom_front_ends`.

The Cursor skill ``/upgrade-to-psynet-14`` is a thin wrapper that points agents
here. Agents read this page with
``psynet docs show whats_new/upgrading_to_psynet_14``, which works without a
PsyNet source checkout.

Also see: :doc:`/whats_new/psynet_14`,
:doc:`/reference/configuration`.

0. Orient
---------

1. Run under the default ``inplace_timeline_transitions = true``.
2. If one page is temporarily blocked, pass
   ``requires_full_page_reload=True`` to that page's constructor.
3. If many pages are blocked, set ``inplace_timeline_transitions = false``
   only as a short-term experiment-wide opt-out, then keep migrating so you
   can remove it.
4. Work page by page.
5. Even with no custom frontend, continue through steps 10–20
   (recruiters, Leave and error pages, changed defaults, setup, deployment
   files, participant failure, responses, groups, assets, exports, and
   validation).

To find pages that can't load in place, run ``psynet debug local`` /
``psynet test local`` and read the traceback. Incompatible pages raise one
short message that lists **error codes** in parentheses; use the glossary
below to map each code to a checklist step.

1. Find and migrate custom page templates
-----------------------------------------

Search for ``template_path=``, ``template_str=``, and
``{% extends "timeline-page.html" %}``.

A complete template extends ``timeline-page.html`` and overrides blocks such
as ``main_body``:

.. code-block:: html

    {% extends "timeline-page.html" %}

    {% block main_body %}
        <p>Custom page content</p>
    {% endblock %}

This style works only with the legacy full-page reload path, where
``inplace_timeline_transitions = false`` is set explicitly.

Convert complete templates to fragments
(``template_fragment_path`` / ``template_fragment_str``) and supply assets via
page arguments. See :doc:`/code/pages/custom_front_ends`
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
---------------------------------------

Search for ``js_links=``, ``scripts=``, and ``<script>`` tags in author-owned
templates or component ``external_template`` files. Classify each script
before moving it (load-once library vs per-page behavior vs short inline).

Converting the HTML template alone is not enough: leftover ``scripts=`` /
``js_links=`` still force a full-page reload and raise ``legacy_scripts`` /
``legacy_js_links`` unless you also pass ``requires_full_page_reload=True``.
These deprecated arguments keep classic linked and inline script semantics,
which is why they cannot use in-place transitions.

Framework macros may still embed classic ``<script>`` tags, which PsyNet
replays across in-place transitions (see :doc:`/developer/page_lifecycle`).
Author-owned external templates should contain only markup. Embedded
``<script type="module">`` tags are not supported.

4. Migrate load-once libraries
------------------------------

Move load-once classic libraries to ``js_dependencies`` /
``get_js_dependencies()``. Do not put per-page initialization there. See
:doc:`/code/pages/custom_front_ends` (Managing JavaScript lifecycles).

5. Migrate per-page behavior
----------------------------

Rewrite classic top-level scripts as ES modules that export ``activate``,
wired with ``js_page_modules`` / ``get_js_page_modules()``. Short snippets may
use ``js_page_code`` / ``get_js_page_code()`` instead.

See :doc:`/code/pages/custom_front_ends` for ``activate(context)``
examples and cleanup guidance.

6. Migrate page variables to ``psynet.var``
-------------------------------------------

Replace legacy ``window`` reads of ``js_vars`` keys with ``psynet.var``.
Optionally set ``legacy_js_var_globals = error`` while testing.

Earlier versions copied each ``js_vars`` key onto ``window``. This global
access is deprecated because in-place timeline transitions reuse the same
browser window across pages. ``legacy_js_var_globals`` controls the
compatibility behavior:

* ``warn`` (default) keeps legacy access working and warns once for each key.
* ``error`` throws a ``ReferenceError`` that identifies the key and recommends
  the corresponding ``psynet.var`` expression.
* ``off`` does not install legacy global properties.

In ``error`` mode the compatibility property remains present so that reads and
writes can produce the informative error. Consequently, ``typeof legacy_name``
also throws and ``"legacy_name" in window`` remains true. Test availability
with ``"name" in psynet.var`` instead. In ``warn`` mode, assigning the legacy
global changes only the mirrored value; it does not update ``psynet.var``.

The compatibility accessors are installed only for keys on the active page,
and PsyNet removes them on the next page. If another script replaces and locks
a compatibility accessor, PsyNet leaves that property alone and continues the
page transition.

PsyNet does **not** install a legacy ``window.<key>`` accessor when that
name already exists on ``window``. In the default ``warn`` mode a colliding
key (for example ``name``, ``status``, ``event``, ``history``) silently
keeps the browser's value; the page data is still available on
``psynet.var``. Page construction warns for these common collisions so they
show up in ``psynet test local`` / ``psynet debug local``. See
:doc:`/code/pages/custom_front_ends` and
:doc:`/reference/configuration`.

7. Migrate JsPsych timelines
----------------------------

``JsPsychPage`` takes a JavaScript module URL exporting
``buildTimeline(context)``, not an HTML/Jinja template. See
``demos/experiments/jspsych``.

8. Fix timing that assumed document load
----------------------------------------

* Page setup → ``activate()`` / ``js_page_code`` (not ``DOMContentLoaded``)
* Timing gates → ``pageReady`` / ``trialConstruct``

Details: :doc:`/code/pages/custom_front_ends`.

9. Migrate trial-selection hooks
--------------------------------

Search custom trial makers for ``find_networks``, ``find_node``,
``prioritize_networks``, ``custom_network_filter``, ``balance_across_nodes``,
``balance_across_chains``, ``choose_block_order``, ``should_finish_block``,
``set_block_state`` and ``module_state.block``.

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
  that are ready for raters, and they wait or finish the block on heads whose
  creator slots are filled but not yet finalized. Heads that still need creators are
  not rater-eligible. A selected head that later becomes incompatible waits
  or exits instead of assigning the opposite role's trial class.
* :attr:`~psynet.trial.main.Trial.position` is now stored when the trial is
  created and counts across all concrete trial classes in a participant's trial
  maker. Previously it was calculated within each concrete trial class. Trials
  constructed outside a trial-maker state may have ``position=None``; code that
  performs arithmetic with ``position`` should handle that case explicitly.
* Blocks are now strict: a participant only receives nodes or chains from
  their current block, and stays in it until ``max_trials_per_block`` or
  ``should_finish_block`` ends it, or until it has nothing more to give them.
  Previously a participant whose block was busy could receive a trial from a
  later block. When every candidate in the block is busy,
  ``wait_for_networks=True`` waits; ``False`` finishes the block early. An
  empty list from ``find_chains`` or ``find_nodes`` now finishes the block;
  ``"exit"`` still leaves the trial maker.
* ``balance_across_nodes`` and ``balance_across_chains`` have been removed.
  Replace ``True`` with ``node_order="balanced"`` / ``chain_order="balanced"``
  and ``False`` with ``"random"``. ``node_order`` already defaults to
  ``"balanced"`` and ``chain_order`` to ``"random"``, as before. See
  :ref:`trial_order` for planned orders such as ``"listed"`` and functions,
  which replace hacks like a ``select_node`` that walks a fixed list.
* Replace a ``choose_block_order`` override with the ``block_order``
  argument: a list, ``"listed"``, or a function of ``participant``,
  ``experiment`` and ``blocks``. Passing ``block_order`` while also
  overriding ``choose_block_order`` raises ``TypeError``.
* ``should_finish_block`` now takes ``(participant, block)``. Read trial counts
  from ``participant.module_state.n_participant_trials_in_block`` and
  ``participant.module_state.n_participant_trials_in_trial_maker``.
* ``module_state.block`` is now derived from ``block_order`` and
  ``block_position`` and cannot be set; ``set_block_state`` has been removed.
  ``ChainTrialMakerState.remaining_blocks`` and ``go_to_next_block`` have also
  been removed: read ``block_order[block_position:]`` for the remaining
  blocks, and end a block with ``should_finish_block`` instead of advancing
  it yourself.
* ``ChainTrialMaker.check_participant_groups`` now receives the participant
  group names of the start nodes instead of a list of networks.
* To keep a participant on one chain until it is finished, pass
  ``interleave_chains=False`` instead of giving each chain its own block.
  :class:`~psynet.trial.staircase.GeometricStaircaseTrialMaker` now does this
  by default.
* ``target_trials_per_node`` (and the dense trial maker's
  ``target_trials_per_condition``) only drives ``recruit_mode="n_trials"``.
  Static nodes no longer stop being selected once they reach it, so a node
  can end up with a few more trials than its target. ``node_order="balanced"``
  still spreads trials evenly and, unless node selection runs in Python,
  gives participants who ask at the same moment different nodes where
  possible. To stop offering nodes once they have enough
  trials, filter them by trial count in ``filter_nodes_query``; simultaneous
  requests can still go slightly over. Chain
  ``trials_per_node`` is still a hard limit.
* Pass ``recruit_mode`` explicitly whenever you set a recruitment target.
  ``target_n_participants`` needs ``recruit_mode="n_participants"``, and
  ``target_trials_per_node`` / ``target_trials_per_condition`` need
  ``recruit_mode="n_trials"``. A target with ``None`` or the other built-in
  mode raises ``ValueError``, as does a misspelt mode. Chain-based trial
  makers, including staircase and graph trial makers, used to default to
  ``"n_participants"`` and now default to ``None`` like static trial makers.
  ``n_participants_completion="trial_maker"`` likewise needs
  ``recruit_mode="n_participants"``:

  .. code-block:: python

      StaticTrialMaker(
          ...,
          recruit_mode="n_participants",
          target_n_participants=30,
      )

PsyNet raises an actionable ``TypeError`` when a removed or wrong-paradigm
hook is still overridden.

10. Recruiter configuration
---------------------------

Search ``config.txt`` (and experiment ``config`` dicts) for
``recruiter = mturk``, ``recruiter = bots``, ``recruiter = multi``, and
Dallinger ``recruiters =``. PsyNet rejects those nicknames, including
subclasses. Deploy with ``prolific``, ``generic``, ``hotair``,
``lucid-recruiter``, or a lab recruiter instead. PsyNet's own bot-based
test commands still work; they are not a ``recruiter = bots`` deployment.

If the study currently runs on MTurk, move it to another platform before
upgrading. Amazon is closing MTurk on September 30, 2026. See
:doc:`/whats_new/psynet_14`.

For Prolific, search for ``prolific_enable_screen_out`` and
``prolific_screen_out_slots``:

* Prolific now pays participants who fail or hit an error a fixed amount
  (``prolific_unsuccessful_base_payment``, default 0.25) plus a bonus up to
  their accumulated reward. This is on by default
  (``prolific_pay_unsuccessful = true``).
* While it is on, set ``prolific_screen_out_slots``, which caps how many
  participants can be paid this way; deployment fails without it. See
  :doc:`/deploy/recruiters/prolific`.
* Set ``prolific_pay_unsuccessful = false`` to keep the old return-for-bonus
  behaviour, for example if the Prolific workspace rejects the screen-out
  completion code.
* Remove ``prolific_enable_screen_out``; it is no longer a valid key.

11. Leave, ads, and error recovery
----------------------------------

Search for ``show_abort_button``, ``show_termination_button``,
``ad_requirements``, ``ad_payment_information``, ``error_page_content``,
``error_page_content__prolific``, ``approve_assignment``,
``reject_assignment``, and ``ExecuteFrontEndJS(``.

* Config and page flags: ``show_early_exit_button`` and
  ``min_reward_for_paid_early_exit``. The old page arguments still work
  with a ``FutureWarning``.
* DOM and routes: ``#early-exit-button``, ``/execute_early_exit_plan/``.
* Participant field: ``Participant.early_exited``.
* Remove ``Experiment.ad_requirements`` and
  ``Experiment.ad_payment_information``. Customize ``templates/ad.html``
  instead; see :doc:`/deploy/reference/ad_page`.
* Replace ``error_page_content`` with recruiter
  ``error_page_presentation``. A custom recruiter that shows recovery UI
  must also override ``shows_error_recovery_page``; a button in the
  presentation is not enough. Handoff controls are armed only while the
  recovery plan is still prepared::

      from psynet.exit import ExitContext

      def shows_error_recovery_page(self, plan):
          return plan.context is ExitContext.ERROR_RECOVERY

  See :doc:`/reference/configuration`.
* Rename ``approve_assignment`` to ``submit_assignment`` and Prolific
  ``reject_assignment`` to ``request_return_for_bonus``.
* ``ExecuteFrontEndJS`` no longer takes ``message``. It shows a spinner::

      ExecuteFrontEndJS("psynet.finishAndGoToExit()")

Stale overrides fail a pre-deployment check or fail when used, with
migration instructions in the error.

12. Changed defaults and option markup
--------------------------------------

* Phones and tablets are allowed by default. Set
  ``allow_mobile_devices = false`` to keep a study desktop-only.
* Default ``min_browser_version`` is Chrome 105. Lower it in
  ``config.txt`` only if you must admit older browsers.
* Leaving ``show_reward`` unset means the recruiter decides: Prolific and
  lab show it, generic/local do not, Lucid hides it. Set
  ``show_reward = true`` to show it anyway where the recruiter allows.
* Radio and checkbox options are full-width ``label.psynet-option`` rows.
  Restyle ``.psynet-option`` / ``.psynet-option-label`` instead of bare
  ``label`` / ``input`` elements; see :doc:`/code/pages/theming`.
* The Next and Reset buttons sit in ``.psynet-actions``. Rules that selected
  them as direct children of ``#trial-stage`` should target
  ``.psynet-actions`` instead.

13. Set up the experiment environment
-------------------------------------

``pip install psynet`` now installs only a small command-line tool. In the
experiment directory, run:

.. code-block:: console

    psynet setup

It creates the experiment's ``.venv``, installs the full PsyNet runtime from
``constraints.txt``, adds the boilerplate files, and starts a Git repository
if the experiment lacks its own. PsyNet needs Python 3.11 or later.

* ``psynet setup --docker`` is removed; run ``psynet setup``, then
  ``psynet debug local --docker``.
* ``psynet services ensure`` starts PostgreSQL and Redis in Docker.

See :doc:`/install` and :doc:`/code/project/creating_an_experiment`.

14. Deployment files
--------------------

Look for ``.dockerignore`` and a ``docker/`` folder of helper scripts in the
experiment directory.

``deploy.toml`` now decides which files are deployed; ``.gitignore`` and
``.dockerignore`` no longer do, so Git-ignored files under ``static/`` are
deployed. PsyNet creates ``deploy.toml`` when it is missing. If your
``.gitignore`` ignores files that ``deploy.toml`` does not exclude, the next
debug, test or deploy command stops once and lists them.

* Move any custom ``.dockerignore`` entries into ``deploy.toml``'s
  ``[exclude]`` table, then delete ``.dockerignore``. PsyNet removes
  generated copies itself.
* Review the list with ``dallinger deployment-files list``.
* Commit your changes before a remote deployment; PsyNet records the commit
  instead of packaging the source code.

See :doc:`upgrading_deployment_file_selection`.

15. Failing participants and trial maker arguments
--------------------------------------------------

Search for ``def fail_participant``, ``data_check_failed``,
``attention_check_failed`` and positional arguments to ``TrialMaker(`` or
``NetworkTrialMaker(``.

* Overriding ``Experiment.fail_participant`` raises an error. Call
  ``participant.fail()``, or register a ``ParticipantFailRoutine`` for code
  that must run when a participant fails.
* Dallinger's ``data_check_failed`` and ``attention_check_failed`` only log
  a warning; they no longer fail the participant.
* ``TrialMaker`` and ``NetworkTrialMaker`` take keyword arguments only, like
  the other trial makers.
* The ``fail_trials_on_premature_exit`` argument is ignored: when a
  participant leaves or fails, their unfinished trials always fail and their
  submitted trials are kept.

See :doc:`/code/trials/participant_and_trial_failure`.

16. Response processing and rendering
-------------------------------------

Search for ``def process_response``, ``response_approved``,
``render_partial_timeline_payload``, ``session.commit(``,
``session.rollback(``, ``accumulate_answers``, and code in ``render()`` or
templates that changes the database.

* With ``accumulate_answers=True``, ``participant.answer`` is now a dict from
  the start of the page maker or trial, and each page adds its answer when it
  is submitted. Code that reads ``participant.answer`` during such a trial
  now gets the current trial's answers so far, not the previous trial's
  answer. Answers from nested accumulating page makers now go into the same
  dict instead of being lost.

* Experiment code that runs while a participant moves through the timeline
  must not call ``db.session.commit()`` or ``db.session.rollback()``; PsyNet
  now raises ``RuntimeError`` if it does. This covers code blocks, page
  makers, page methods (``format_answer``, ``validate``, ``on_complete``,
  ``pre_render``), trial methods and trial maker hooks. Delete these calls:
  PsyNet commits for you. Use ``db.session.flush()`` where you need a new
  object's ``id``. Custom POST routes still commit themselves. See
  :ref:`Saving changes <saving_changes>`.

* ``participant.answer``, ``save_answer`` variables and ``on_complete`` are
  now updated only after ``validate`` accepts the response. A custom
  ``format_answer``, ``validate`` or ``process_response`` that reads
  ``participant.answer`` now sees the previous answer; use the ``answer``
  argument instead.
* Pages now render in a read-only transaction. Move database writes from
  ``render()`` or templates to ``pre_render()``.
* An override of ``Experiment.process_response`` must return a
  ``ResponseResult`` (``from psynet.experiment import ResponseResult``) and
  accept ``**kwargs``.
* ``Experiment.response_approved`` is removed; customize approved responses
  through ``process_response`` or the page-rendering hooks.

17. Groups and barriers
-----------------------

Search for code that changes ``SyncGroup.participants``, custom ``Barrier``
subclasses, ``get_waiting_participants(`` and ``SimpleGrouper(``.

* Change group membership with ``SyncGroup.add_participant()`` and
  ``SyncGroup.remove_participant()``. ``SyncGroup.participants`` is
  read-only and lists only active members.
* Custom barriers implement ``check_waiting_participants()`` and
  ``choose_who_to_release()`` instead of overriding ``check()``. Barrier
  state is saved as data, so custom release state must be JSON-compatible
  values, importable classes or functions, or database objects.
* ``Barrier.get_waiting_participants()`` takes the participant as its first
  argument; pass ``for_update`` as a keyword.
  ``get_waiting_participants_from_barrier_id`` is removed.
* ``SimpleGrouper`` IDs now include the group size. Pass the same ``id_``
  to two groupers that should share a waiting pool.

See :doc:`/code/multiplayer/synchronization`.

18. Assets and stimuli
----------------------

Search for ``ExperimentAsset``, ``CachedAsset``, ``CachedFunctionAsset``,
``personal=``, ``cache=`` and ``compile_nodes_from_directory``.

* Rename ``ExperimentAsset`` and ``CachedAsset`` to ``FileAsset``, and
  ``CachedFunctionAsset`` to ``GeneratedAsset``. The old names still work
  but warn, and ``asset(..., cache=...)`` no longer has an effect.
* Remove ``personal=``; it now raises an error. Treat exported media as
  potentially identifying.
* ``compile_nodes_from_directory`` reads media from ``static/``: move the
  files there from ``data/``, replace ``asset_label`` with ``url_key``, and
  pass ``self.definition["url"]`` to prompts.
* Ready-made stimuli can live in ``static/`` and be referenced with
  ``psynet.media.static_url_for``; see :doc:`/code/using_stimuli`.

19. Exports and analysis scripts
--------------------------------

Search scripts and notes for ``--assets all``, ``--legacy``,
``--anonymize``, ``psynet.zip``, ``database.zip``, ``extra_var`` and
``export_classes_to_skip``.

* ``psynet export`` writes one archive to ``exports/latest/`` and keeps
  earlier exports under ``exports/history/``. Table CSVs are in a flat
  ``database/`` folder, with pseudonymous participant IDs; recruiter IDs are
  in ``participant_identifiers.csv``.
* ``--assets`` takes ``collected`` (the default: files created during the
  study) or ``none``. ``--assets all``, ``--legacy`` and ``--anonymize`` are
  removed, and stimuli declared in the timeline are not exported.
* Empty tables have no CSV; check ``table_row_counts`` in
  ``manifest.json`` before reading one.
* Yes/no columns contain ``True`` and ``False`` rather than ``t`` and
  ``f``, and the ``type`` column of ``assets/manifest.csv`` uses the new
  asset class names.
* ``extra_var`` is removed; read variables from the ``vars`` column with
  ``psynet.export.unpack_json_column``.
* Search experiment code for ``copy_expert``, ``copy_from``, ``copy_to`` and
  ``COPY``. In a web request or background job, PostgreSQL ``COPY`` must run
  inside :func:`psynet.db.blocking_psycopg`, or psycopg2 raises
  ``ProgrammingError``.

See :doc:`/data/what_an_export_contains`.

20. Validate
------------

From a complete experiment directory. At minimum you typically need:

* ``experiment.py``, ``test.py``, ``constraints.txt``
* ``config.txt``, ``requirements.txt``
* ``.gitignore``, ``deploy.toml``, and ``.python-version``

If you are scaffolding from scratch, see
:doc:`/code/project/creating_an_experiment` or run ``psynet scripts update``
to generate the standard support files.

.. code-block:: console

    psynet test local

Before the bots run, ``psynet test local`` checks static timeline pages
against the in-place page requirements, so migration errors appear directly
in the test failure. Pages created by a ``PageMaker`` are checked when they
are first rendered.

Confirm the default in-place mode works (opt-out removed if possible), page
modules activate without console errors, cleanup runs for persistent
listeners, and ``config.txt`` no longer uses ``mturk``, ``bots``, or
``multi``.

Error codes
-----------

With the default ``inplace_timeline_transitions = true``, PsyNet raises an
error if a custom page uses a complete template or if author-provided template
content includes patterns that are incompatible with the in-place lifecycle.
With ``inplace_timeline_transitions = false``, PsyNet keeps legacy templates
working but may warn about patterns that should be migrated. The check covers
only author-provided template content, not PsyNet's own timeline shell or
assets supplied through supported page arguments. A page that fails it may
still work in legacy reload mode.

The error message for a page that can't load in place lists codes such as
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

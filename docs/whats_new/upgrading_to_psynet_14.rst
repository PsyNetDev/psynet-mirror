======================
Upgrading to PsyNet 14
======================

This checklist migrates an existing experiment onto PsyNet 14: in-place
timeline transitions, recruiter and leave APIs, changed defaults, setup and
deployment files, participant failure, groups, assets, async jobs and exports. Work
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
5. Even with no custom frontend, continue through steps 9–21
   (trial selection, recruiters, Leave and error pages, changed defaults,
   setup, deployment files, participant failure, responses, groups, assets,
   async jobs, exports, and validation).

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

PsyNet now serves jQuery 4.0.0 and no longer bundles jQuery UI: a template
that loaded ``/static/scripts/jquery-ui.min.js`` or
``/static/css/jquery-ui.css`` must ship its own copy in the experiment's
``static/`` directory. Search your JavaScript
for jQuery utilities that jQuery 4 removed, such as ``$.trim``,
``$.isArray``, ``$.isFunction``, ``$.parseJSON``, ``$.type``,
``$.isNumeric`` and ``$.now``. Replace them with native JavaScript, for
example ``text.trim()``, ``Array.isArray(value)`` and ``JSON.parse(text)``.
``.css()`` also no longer adds ``px`` to bare numbers for most properties
(sizes, margins, padding, border widths and positions still get it), so pass
other values with units, for example ``"16px"``. Replace links to
``/static/scripts/jquery-3.7.1.min.js`` with ``jquery-4.0.0.min.js``; timeline
pages already load jQuery, so they don't need their own link. Upgrade bundled
jQuery plugins to versions that support jQuery 4. See the
`jQuery 4.0 upgrade guide <https://jquery.com/upgrade-guide/4.0/>`_.

4. Migrate load-once libraries
------------------------------

Move load-once classic libraries to ``js_dependencies`` /
``get_js_dependencies()``. Do not put per-page initialization there. See
:doc:`/code/pages/custom_front_ends` (Managing JavaScript lifecycles).

Timeline pages load SurveyJS only when they contain a ``SurveyJSControl``.
Pages that use ``SurveyJSControl``, ``MultiRatingControl`` or
``RatingControl`` need no change. If a custom page builds a survey with
``new Survey.Model(...)`` instead, add
``/static/scripts/survey-jquery/survey.jquery.min.js`` to its
``js_dependencies``.

5. Migrate per-page behavior
----------------------------

Rewrite classic top-level scripts as ES modules that export ``activate``,
wired with ``js_page_modules`` / ``get_js_page_modules()``. Short snippets may
use ``js_page_code`` / ``get_js_page_code()`` instead.

See :doc:`/code/pages/custom_front_ends` for ``activate(context)``
examples and cleanup guidance.

Page code that talks to the server also needs to identify the participant
in new ways. Search your JavaScript for ``WebSocket(``, ``/chat?``,
``/worker_complete``, ``/worker_failed``, ``participantId``,
``disableButton``, ``enableButton``, ``onNextButton``,
``next-button-spinner`` and ``next-button-text``:

* A websocket that names a participant must send their scope token, or
  PsyNet refuses the connection. For a socket that the page opens by hand,
  add it to the URL::

      "/chat?channel=" + channel
          + "&participant_id=" + dallinger.identity.participantId
          + "&scope=" + encodeURIComponent(psynetTemplateData.websocketScope)

  Dallinger's helpers take it as an option:
  ``dallinger.openExperimentSocket({scope: psynetTemplateData.websocketScope})``,
  and likewise ``openChatSocket``, ``joinRealtimeSession`` and
  ``waitForRealtimeSession``. See
  :doc:`/code/multiplayer/realtime_interaction`.
* Requests to ``/worker_complete`` and ``/worker_failed`` must send
  ``unique_id`` (``dallinger.identity.uniqueId``) as well as
  ``participant_id``; without it they get a 403.
* ``/timeline/progress_and_reward`` reads ``uniqueId`` instead of
  ``participantId``.
* The global functions ``disableButton()``, ``enableButton()`` and
  ``onNextButton()`` are gone. Use
  ``psynet.page.control.nextButton.disable()``, ``.enable()`` and
  ``.handleClick()``, which exist on a ``ModularPage`` that shows PsyNet's
  Next button (``show_next_button``). The
  ``#next-button-spinner`` and ``#next-button-text`` elements are gone too;
  target ``#next-button`` instead. Disabling the button no longer shows a
  spinner.
* A function exposed with ``expose_to_api`` that returns a string now sends
  it as plain text, so HTML in it is no longer rendered. Return a Flask
  ``Response`` for another content type.
* Browsers refuse scripts and stylesheets served with the wrong content
  type, so give your files standard extensions such as ``.js`` and
  ``.css``.

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
  still spreads trials evenly and, unless node selection runs in Python or
  ``node_priority`` is defined, gives participants who ask at the same moment different nodes where
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

Also search for ``n_all_trials``, ``n_alive_trials``, ``n_failed_trials``,
``n_completed_trials``, ``n_all_nodes``, ``Info.query`` and ``.infos(``:

* Networks no longer have the trial and node count attributes
  ``n_all_trials``, ``n_alive_trials``, ``n_failed_trials``,
  ``n_completed_trials`` and ``n_all_nodes``. Count with
  ``psynet.trial.chain.count_completed_trials_for_network(network.id)`` or
  ``count_viable_trials_for_node(node.id)``, or query ``Trial`` directly.
  ``participant.module_state.n_completed_trials`` is unchanged.
* Trials are no longer Dallinger ``Info`` objects, so ``Info.query`` and
  ``node.infos()`` don't return them. Query ``Trial`` instead, and store
  extra values in ``trial.var`` rather than ``property1`` to ``property5``
  or ``details``.

10. Recruiter configuration
---------------------------

Search ``config.txt`` (and experiment ``config`` dicts) for
``recruiter = mturk``, ``recruiter = bots``, ``recruiter = multi``, and
Dallinger ``recruiters =``. PsyNet rejects those nicknames, including
subclasses. Deploy with ``prolific``, ``generic``, ``hotair``,
``lucid-recruiter``, or a lab recruiter instead. PsyNet's own bot-based
test commands still work; they are not a ``recruiter = bots`` deployment.

Amazon closed MTurk on September 30, 2026, so a study configured for MTurk
needs another platform. See :doc:`/whats_new/psynet_14`.

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

Deploying with the Lab Recruiter now requires ``lab_recruiter_auth_token``
in ``~/.dallingerconfig``; see :ref:`lab-deployment-lab-recruiter`.

A custom subclass of the Lucid recruiter must follow two signature
changes: ``get_participant`` takes an ``assignment_id`` (the Lucid RID)
instead of the request, and PsyNet calls ``terminate_participant`` with a
new keyword-only argument, ``raise_on_error``, so an override must accept
it and pass it on to ``super().terminate_participant``.

11. Leave, ads, and error recovery
----------------------------------

Search for ``show_abort_button``, ``show_termination_button``,
``min_accumulated_reward_for_abort``, ``ad_requirements``,
``ad_payment_information``, ``error_page_content``,
``error_page_content__prolific``, ``approve_assignment``,
``reject_assignment``, ``check_unique_id``, ``error_page(`` and
``ExecuteFrontEndJS(``.

* Config and page flags: ``show_early_exit_button`` and
  ``min_reward_for_paid_early_exit``. The old page arguments still work
  with a ``FutureWarning``, but the old config keys ``show_abort_button``
  and ``min_accumulated_reward_for_abort`` stop the experiment from
  starting; rename them in ``config.txt``, and in ``Experiment.config`` if
  you set them there.
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
* ``Experiment.check_unique_id`` and ``Experiment.UniqueIdError`` are
  removed; look the participant up with
  ``Experiment.get_participant_from_unique_id``.
* ``Experiment.error_page`` no longer takes ``compensate``, ``error_type``
  or ``request_data``; omit them.

Stale overrides of the removed hooks fail a pre-deployment check or fail
when used, with migration instructions in the error. Calls to removed
methods or with removed arguments raise an ordinary ``AttributeError`` or
``TypeError``.

12. Changed defaults and option markup
--------------------------------------

Two changes affect code in almost any experiment, so check them first.
Search for ``var.get(`` and ``conditional(``.

* ``participant.var.get(name)`` (and ``var.get`` on ``experiment.var``,
  nodes, networks and trials) returns ``None`` for a missing variable, like
  ``dict.get``, instead of raising ``KeyError``. Where the error was wanted,
  for example inside ``try`` / ``except KeyError``, read
  ``participant.var.name`` instead, or check ``participant.var.has(name)``:

  .. code-block:: python

      # Before: relied on the KeyError
      try:
          score = participant.var.get("score")
      except KeyError:
          score = 0
      # After
      score = participant.var.score if participant.var.has("score") else 0
* :func:`~psynet.timeline.conditional` now converts its condition's result
  with ``bool()``, so a condition may return any value. Before, a value
  other than ``True``, ``False``, ``1`` or ``0``, such as ``None``, ``2`` or
  a list, raised an error; now ``None`` and an empty list choose
  ``logic_if_false``, and other values ``logic_if_true``. A condition that
  relied on the error to catch a bug should return a ``bool`` explicitly.

  .. code-block:: python

      # Before, this raised an error, because the condition returns a list;
      # now a non-empty list chooses the first branch
      conditional("has_answers", lambda participant: participant.var.answers, ...)

* Phones and tablets are allowed by default. Set
  ``allow_mobile_devices = false`` to keep a study desktop-only.
* ``force_google_chrome`` now defaults to ``false`` and is deprecated, so
  Chrome, Edge, Firefox and Safari are admitted. Every experiment rejects
  browsers without CSS ``:has()`` support (Chrome < 105, Firefox < 121,
  Safari < 15.4), and ``min_browser_version`` has been removed: delete it
  from ``config.txt`` and ``~/.dallingerconfig``, because PsyNet refuses to
  start with unknown config keys. Declare
  required features such as ``{"microphone"}`` in
  ``Experiment.browser_capabilities`` instead; see
  :doc:`/reference/configuration`.
* Leaving ``show_reward`` unset means the recruiter decides: Prolific and
  lab show it, generic/local do not, Lucid hides it. Set
  ``show_reward = true`` to show it anyway where the recruiter allows.
* Radio and checkbox options are full-width ``label.psynet-option`` rows.
  Restyle ``.psynet-option`` / ``.psynet-option-label`` instead of bare
  ``label`` / ``input`` elements; see :doc:`/code/pages/theming`.
* The Next and Reset buttons sit in ``.psynet-actions``. Rules that selected
  them as direct children of ``#trial-stage`` should target
  ``.psynet-actions`` instead.
* ``psynet translate`` uses ChatGPT only. Remove
  ``default_translator = google_translate``, which raises an error;
  ``google_translate_json_path`` and ``google_translate_project_id`` are
  ignored. See :doc:`/code/participants/internationalization`.
* The default translation model is ``gpt-6-luna`` instead of ``gpt-4o``, and
  ``openai_default_temperature`` is no longer set. ``gpt-6-luna`` ignores
  ``openai_default_temperature``; set it only together with a model that
  accepts it, for example ``openai_default_model = gpt-4o``.
* Participant pages escape HTML in plain strings. Search for ``labels=``,
  ``choices=``, ``Button(``, ``WaitPage(``, ``KeyboardPage(`` and
  ``template_arg=`` with HTML tags in the text, and wrap HTML that you wrote
  in ``markupsafe.Markup``, for example
  ``labels=[Markup("Yes <kbd>Y</kbd>")]``. Never wrap participant-provided
  text in ``Markup``; to mix it into HTML, write
  ``Markup("<b>{}</b>").format(answer)``, which escapes ``answer``. In custom
  templates, write values inside ``<script>`` with ``{{ value | tojson }}``.
  See :doc:`/code/writing_pages`.
* ``AudioPrompt`` ``controls`` labels are escaped too, so wrap HTML labels in
  ``Markup``.
* Custom dashboard tabs that render ``dashboard_custom.html`` or the card
  macros in ``macros/dashboard.html``, and pages that render
  ``custom_html.html``, escape plain strings. Pass ``html``, card bodies and
  list items as ``Markup``; for a ``dominate`` tag, ``Markup(tag.render())``.
* PsyNet now requires dominate 3.1, which renders ``a``, ``span`` and ``sup``
  inline: it no longer starts a new line before them, so the space that used
  to appear before each of these tags is gone. This affects a tag that
  follows text as well as tags placed side by side. Search for dominate
  ``span``, ``a`` and ``sup`` tags, and add the space where you want one:

  .. code-block:: python

      tags.p("Click", tags.a("here", href=url))  # now shows "Clickhere"
      tags.p("Click ", tags.a("here", href=url))  # shows "Click here"
      tags.div(tags.span("A"), tags.span("B"))  # now shows "AB"
      tags.div(tags.span("A"), " ", tags.span("B"))  # shows "A B"

  Attributes set to ``0``, such as ``value=0``, are now rendered instead of
  dropped.
* ``KeyboardPage`` now requires ``prompt``.
* A ``REPPVolumeCalibration`` subclass whose ``what_are_we_playing`` returns
  HTML must return ``Markup``.
* Custom templates that call ``AudioMeterControl.to_json`` must write
  ``{{ params.to_json() | tojson }}``.

13. Set up the experiment environment
-------------------------------------

``uv pip install psynet`` now installs only a small command-line tool. In the
experiment directory, create and activate a virtual environment, install
PsyNet into it, and run ``psynet setup``:

.. code-block:: console

    uv venv --python 3.14
    source .venv/bin/activate
    uv pip install psynet
    psynet setup

``psynet setup`` installs the full PsyNet runtime from ``constraints.txt``,
adds the boilerplate files, and starts a Git repository if the experiment
lacks its own. PsyNet needs Python 3.11 or later and recommends 3.14.

Before running ``psynet setup``, update the PsyNet pin in
``requirements.txt``. Setup fills in only a bare ``psynet`` line, so a pin
such as ``psynet==13.3.0`` stays in force. Pin PsyNet 14 with the
``[experiment]`` extra, which deploying requires, for example
``psynet[experiment]==14.0.0``; see :ref:`dependencies_updating_psynet`.
Remote deployments stop while ``constraints.txt`` is out of date with
``requirements.txt``, so rerun ``psynet setup`` after changing either.

* The experiment directory is no longer added to ``sys.path``. Import
  sibling modules with ``from . import my_module``, as in ``experiment.py``;
  a bare ``import my_module`` fails. See
  :ref:`experiment_python_modules`.

* ``psynet setup --docker`` is removed; run ``psynet setup``, then
  ``psynet debug local --docker``.
* ``psynet services ensure`` starts PostgreSQL and Redis in Docker. It runs
  PostgreSQL 18, which can't open the data of the PostgreSQL 12
  ``dallinger_postgres`` container that earlier versions started. It, and
  ``psynet debug local`` and ``psynet test local``, offer to replace that
  container (``psynet services ensure --yes`` replaces it without asking), and
  your local database then starts empty. The old data stays in the
  ``dallinger_postgres`` volume.
* The PsyNet runtime no longer installs ``pytest-mock``, ``pytest-timeout``,
  ``pytest-dependency``, ``progress`` or ``python-gettext``. If the
  experiment's tests use ``mocker``, ``@pytest.mark.timeout`` or
  ``@pytest.mark.dependency``, or its code imports ``progress`` or
  ``pythongettext``, add that package to ``requirements.txt``.
* The ``psynet[slack]`` extra is removed, because the runtime already
  includes ``slack-sdk``. Drop ``slack`` from ``requirements.txt`` and from
  install commands.
* ``Notifier.python_dependencies`` and
  ``Experiment.check_python_dependencies()`` are removed. If a custom
  notifier listed packages in ``python_dependencies``, add them to
  ``requirements.txt`` instead; deploys no longer check for them.

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
* On SSH deployments, the experiment runs as the SSH account instead of
  root, and the files deployed with it stay owned by root. Experiment code
  can still create new files, but it can't edit deployed files in place, for
  example to overwrite a file in ``static/``. Write files that change while
  the experiment runs to a temporary directory (Python's ``tempfile``) or
  store them as assets.
* Responses send ``X-Frame-Options: SAMEORIGIN``, so other sites can't show
  the experiment in a frame. An experiment that must be framed can remove
  the header; see :ref:`deployment_security_headers`.
* The experiment Dockerfile template is based on Debian 13 instead of
  Debian 12. Run ``psynet scripts update`` to rewrite it, and check that the
  Debian packages ``prepare_docker_image.sh`` installs still exist.

See :doc:`upgrading_deployment_file_selection`.

A docker-ssh server set up by Dallinger 13.0 or earlier keeps PostgreSQL 12
until ``dallinger docker-ssh servers upgrade`` moves it to PostgreSQL 18. That
upgrade stops every classic app on the server while it copies the databases,
and afterwards no one may deploy to the server with PsyNet 13 or earlier or
with PsyNet 14.0.0rc1 to rc3.
A Cloudflare-ingress app deployed with Dallinger 13.0 or earlier keeps
PostgreSQL 12 when you update it with ``--update``. Read
:ref:`Moving to PostgreSQL 18 <upgrading_to_postgresql_18>` before you
upgrade a server.

15. Failing participants and trial maker arguments
--------------------------------------------------

Search for ``def fail_participant``, ``def data_check``,
``def attention_check``, ``data_check_failed``, ``attention_check_failed``,
``def bonus``, ``def check_bonus`` and positional arguments to
``TrialMaker(`` or ``NetworkTrialMaker(``.

* Overriding ``Experiment.fail_participant`` raises an error. Call
  ``participant.fail()``, or register a ``ParticipantFailRoutine`` for code
  that must run when a participant fails.
* Overriding Dallinger's ``data_check``, ``attention_check``,
  ``data_check_failed`` or ``attention_check_failed`` stops the experiment
  from launching, because PsyNet doesn't use them. Fail participants during
  the timeline instead, with ``participant.fail()`` or an
  ``UnsuccessfulEndPage``. Calls to ``data_check_failed`` and
  ``attention_check_failed`` only log a warning.
* Overriding ``Experiment.bonus`` or ``Experiment.check_bonus`` also stops
  the launch. The recruiter decides payments: customize
  ``decide_payment``, ``platform_base_for`` or ``total_owed`` on a recruiter
  subclass; see :doc:`/code/participants/payment`.
* ``TrialMaker`` and ``NetworkTrialMaker`` take keyword arguments only, like
  the other trial makers.
* The ``fail_trials_on_premature_exit`` argument is ignored: when a
  participant leaves or fails, their unfinished trials always fail and their
  submitted trials are kept.

See :doc:`/code/trials/participant_and_trial_failure`.

16. Response processing and rendering
-------------------------------------

Search for ``def process_response``, ``response_approved``,
``session.commit(``, ``session.rollback(``, ``reward_bonus``,
``terminate_participant``, ``complete_participant``, ``accumulate_answers``,
and code in ``render()`` or templates that changes the database.

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

* For the same reason, payment and recruitment-platform calls such as
  ``experiment.pay_decided_bonus``, ``recruiter.reward_bonus`` and the
  Lucid recruiter's ``terminate_participant`` and ``complete_participant``
  raise ``RuntimeError`` in that code. Make them from an
  ``AsyncCodeBlock``, which runs after the participant's changes are
  saved. The Lab and Lucid recruiters' ``reward_bonus`` always raises.

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
* Push buttons, dropdowns, radio buttons and checkboxes now save the picked
  element of ``choices`` with its original type, not the browser's text.
  Search for these controls with numeric ``choices``, for example
  ``PushButtonControl([1, 2, 3])``, and compare their answers to numbers:
  ``answer == 3``, not ``answer == "3"``. ``int(answer)`` keeps working.
  Choices with the same text, such as ``1`` and ``"1"``, raise
  ``ValueError``.
  Fixed bot answers, from ``bot_response`` or a ``get_bot_response`` method
  that returns a plain value, are not converted, and an answer that is not
  one of the choices is rejected (see the next item), so give them as numbers
  too: ``bot_response=3``, not ``bot_response="3"``.
* These controls now reject an answer that is not one of their ``choices``.
  Search for ``def format_answer`` on these controls and on pages that use
  them; if it saves something other than a choice, such as a dictionary with a
  reaction time, set ``restrict_to_choices = False`` on the control class or
  pass ``restrict_to_choices=False`` to the control. Also search for ``random.`` in
  ``PageMaker`` functions and ``show_trial``: the page is built again when the
  response arrives, so random choices must be picked once (for example in
  ``finalize_definition`` or ``participant.var``). See
  :class:`~psynet.modular_page.OptionControl`.
* ``NumberControl`` now saves a number (``78.5`` or ``100``), not the
  browser's text. Search for ``NumberControl`` and compare its answers to
  numbers: ``answer == 100``, not ``answer == "100"``. ``float(answer)``
  keeps working. Default bots save numbers too. A fixed bot answer, from
  ``bot_response`` or a ``get_bot_response`` method that returns a plain
  value, is saved as given, so give it as a number: ``bot_response=25``,
  not ``bot_response="25"``, which now fails validation. The typed text is
  lost (``02139`` is saved as ``2139``), so use ``TextControl`` for codes such
  as postcodes or IDs where the exact text matters. Text with ``_``, such as
  ``1_000``, fails validation. A ``NumberControl`` page that overrides
  ``format_answer`` must now return a number: call
  ``super().format_answer(raw_answer, **kwargs)`` or convert the text
  yourself, since returned text fails validation.
* Default bot answers now go through the page's or control's
  ``format_answer``, as participants' answers do. Search for
  ``def format_answer`` on pages that bots answer without ``bot_response``
  and on subclasses of the controls listed in the next item, and check that
  it accepts what the browser sends. For example, a ``TextControl`` page whose
  ``format_answer`` returns ``int(raw_answer)`` used to be skipped for bots,
  but now fails on the default answer ``"Hello, I am a bot!"``: pass
  ``bot_response=`` with a suitable answer, or let ``format_answer`` accept
  the default. Whole-number floats in any ``BotResponse(raw_answer=...)``,
  including your own, are now submitted as ints, as the browser's JSON
  does: a rating scale given as ``{"low": 0.0, "high": 1.0}`` saves ``1``,
  not ``1.0``.
* The built-in ``get_bot_response`` methods of ``NumberControl``,
  ``TextControl``, ``MonitorControl``, ``SliderControl``,
  ``FrameSliderControl``, ``MultiRatingControl`` (and so ``RatingControl``)
  and ``GraphicControl`` now return a ``BotResponse`` holding the browser's
  raw answer, rather than a plain value. Search for ``get_bot_response`` in
  subclasses of these controls: code that calls ``super().get_bot_response(...)``
  should read ``.raw_answer`` from the result. This is the browser's text for
  ``NumberControl`` (``"57"``) and SurveyJS JSON text for ``MultiRatingControl``
  and ``RatingControl`` (``json.loads(raw_answer)`` gives
  ``{"rating": 3}``). Return ``BotResponse(raw_answer=...)`` in the same form,
  so that the answer still goes through ``format_answer``; a plain return
  value is saved as given. For example:

  .. code-block:: python

      class OneMoreNumberControl(NumberControl):
          def get_bot_response(self, experiment, bot, page, prompt):
              response = super().get_bot_response(experiment, bot, page, prompt)
              return BotResponse(raw_answer=str(int(response.raw_answer) + 1))
* ``LanguageVocabularyTrial`` answers are now screen positions (``"1"`` to
  ``"4"``) rather than ``"correct"``. A custom subclass that compares an
  answer with ``"correct"`` should compare it with
  ``definition["correct_answer"]`` instead. A subclass that overrides
  ``finalize_definition`` must call ``super()`` or set
  ``definition["correct_answer"]`` (the 1-based position) itself.

17. Groups and barriers
-----------------------

Search for code that changes ``SyncGroup.participants``, custom ``Barrier``
subclasses, ``get_waiting_participants(``, ``SimpleGrouper(``,
``waiting_logic=``, ``.sync_group`` on trials and ``ParticipantFailRoutine``.

* Change group membership with ``SyncGroup.add_participant()`` and
  ``SyncGroup.remove_participant(participant, reason=...)``, which needs a
  reason such as ``"removed_by_experimenter"``. ``SyncGroup.participants``
  is read-only and lists only active members.
* Custom barriers implement ``check_waiting_participants()`` and
  ``choose_who_to_release()`` instead of overriding ``check()``. Barrier
  state is saved as data, so custom release state must be JSON-compatible
  values, importable classes or functions, or database objects.
* ``Barrier.get_waiting_participants()`` takes the participant as its first
  argument; pass ``for_update`` as a keyword.
  ``get_waiting_participants_from_barrier_id`` is removed.
* ``SimpleGrouper`` IDs now include the group size. Pass the same ``id_``
  to two groupers that should share a waiting pool.
* ``SimpleGrouper(min_group_size=...)`` is now ``quorum=...``: how many
  active members a group needs to keep going. The old name still works with
  a ``FutureWarning``. A grouper for groups of three or more without
  ``quorum`` warns: pass ``quorum=initial_group_size`` to keep failing a group
  as soon as one member leaves, or a smaller number if your code handles
  smaller groups. A ``quorum`` below ``initial_group_size`` also needs
  ``below_quorum="fail"`` (the old behavior) or
  ``below_quorum="continue_without_group"``.
  Participants failed because their group fell below its quorum now get the
  failure tag ``sync group below quorum`` instead of
  ``sync group below minimum size``; update analysis code that filters on it.
* ``SimpleGrouper(join_existing_groups=True)`` now warns unless you say when
  newcomers start taking part: pass ``use_admission_points=False`` to keep
  the old behavior, or ``use_admission_points=True`` to admit
  them only at admission points (see :ref:`sync-admission-points`).
* A ``quorum`` (or ``min_group_size``) larger than ``max_group_size`` now
  raises a ``ValueError``, because such a group could never reach it. Lower
  the quorum, or raise ``max_group_size``:

  .. code-block:: python

      # Before: accepted, but a group of at most 3 can never have 4 members
      SimpleGrouper("team", initial_group_size=2, max_group_size=3,
                    min_group_size=4, join_existing_groups=True)
      # After
      SimpleGrouper("team", initial_group_size=2, max_group_size=3,
                    quorum=2, join_existing_groups=True,
                    use_admission_points=False)
* Pages shown from a barrier's ``waiting_logic``, such as filler trials,
  now end when the barrier releases the participant, ``release_grace``
  seconds (3 by default) after the browser notices, instead of running to
  their end. The page saves an empty response with ``"interrupted": True``
  in its metadata, and its trial, any trial that the rest of that pass of
  ``waiting_logic`` reaches, and one the trial maker prepared for its next
  pass are failed with ``failed_reason="interrupted_by_release"``. These
  failed trials still count towards ``n_created_trials`` (so later trials'
  ``position`` skips them) and ``max_trials_per_block``, but not towards
  completed-trial targets, so count played filler trials with
  ``n_completed_trials`` or ``complete``. The interrupted page calls
  ``Experiment.process_response`` with ``interrupted=True``, which is why an
  override must accept ``**kwargs`` (see step 16). Pass
  ``release_grace=None`` to keep letting each waiting page run to its end:

  .. code-block:: python

      # Before: the filler page always ran to its end
      GroupBarrier(id_="ready", group_type="team", waiting_logic=filler)
      # After, to keep that behavior
      GroupBarrier(id_="ready", group_type="team", waiting_logic=filler,
                   release_grace=None)
* ``Trial.sync_group`` now returns the group the trial was played in
  (``trial.sync_group_id``), also after the participant has left it,
  instead of the participant's current group of the trial maker's type. Code
  that wants the current group should look it up on the participant:

  .. code-block:: python

      # Before: the participant's current group, or None once they left
      group = trial.sync_group
      # After, for a trial maker with sync_group_type="team"
      group = participant.active_sync_groups.get("team")
* A member failed by a :class:`~psynet.sync.GroupBarrier` for being late
  (``late_action="fail"``) or for waiting too long
  (``max_wait_action="fail"``, the default), including at a synchronized
  trial maker's barriers, now leaves all their groups before being failed,
  and a member failed because their group dissolved
  (``below_quorum="fail"``) first leaves that group. So a
  ``ParticipantFailRoutine`` no longer finds those groups in
  ``participant.active_sync_groups``. Other failures, such as returning the
  study, still run the routines while the participant is in their groups.
  Read the group they left with ``participant.latest_sync_group()``:

  .. code-block:: python

      # Before
      def record_team(participant):
          participant.var.team_id = participant.active_sync_groups["team"].id
      # After
      def record_team(participant):
          team = participant.latest_sync_group("team")
          participant.var.team_id = None if team is None else team.id

      ParticipantFailRoutine("record_team", record_team)
* Synchronized trial makers no longer wait at an ``init_participant``
  barrier before their first trial, and their ``prepare_trial`` barrier is
  now ``{id}__prepare_trial``, where ``{id}`` is the trial maker's ID.
  Update tests or dashboards that look for these barriers.
* A trial maker's ``sync_group_max_wait_time`` without ``sync_group_type``
  has no effect and now warns; remove it or set ``sync_group_type``.
* In bot tests, ``advance_past_wait_pages(bots, max_iterations=...)`` is
  deprecated; pass ``timeout=`` (seconds) instead.

If you used a PsyNet 14.0 release candidate, also make these changes. The
old options of barriers, groupers and trial makers raise an error naming
the replacement:

* ``GroupBarrier(notify_arrivals=False)`` becomes
  ``GroupBarrier(on_arrival_message=None)``. Drop ``notify_arrivals=True``.
* ``GroupBarrier``'s ``timeout_between_barriers_time`` and
  ``timeout_between_barriers_action`` were renamed ``late_after`` and
  ``late_action``; on trial makers, ``sync_group_timeout_between_barriers_time``
  and ``sync_group_timeout_between_barriers_action`` were renamed
  ``sync_group_late_after`` and ``sync_group_late_action``. ``late_action`` no
  longer defaults to ``"fail"``, so pass it whenever you pass ``late_after``,
  and write ``"leave_group"`` for ``"kick"``. Remove ``max_wait_time`` (or
  ``sync_group_max_wait_time``) where you pass ``late_after``: it now
  defaults to no limit there, and a limit raises an error.
* ``content=`` on ``wait_while``, ``AsyncCodeBlock``, barriers and groupers
  becomes ``waiting_message=``, and trial makers' ``sync_group_wait_content``
  becomes ``sync_group_waiting_message``.
* ``fail_participants_below_min_size=False`` becomes
  ``below_quorum="continue_without_group"``, and
  ``fail_participants_below_min_size=True`` becomes ``below_quorum="fail"``.
  ``SimpleSyncGroup.dissolve_if_below_min_size()`` was renamed
  ``dissolve_if_below_quorum()``.
* Synchronized trial makers no longer have an ``{id}__init_participant``
  barrier; look for ``{id}__prepare_trial`` instead.

See :doc:`/code/multiplayer/synchronization`.

18. Assets and stimuli
----------------------

Search for ``ExperimentAsset``, ``CachedAsset``, ``CachedFunctionAsset``,
``personal=``, ``cache=``, ``compile_nodes_from_directory``,
``on-demand-asset`` and ``.deposited``.

* Rename ``ExperimentAsset`` and ``CachedAsset`` to ``FileAsset``, and
  ``CachedFunctionAsset`` to ``GeneratedAsset``. The old names still work
  but warn, and ``asset(..., cache=...)`` no longer has an effect.
* Remove ``personal=``; it now raises an error. Treat exported media as
  potentially identifying.
* Remove ``obfuscate=`` too; it raises ``TypeError``. The URLs of locally
  stored assets (``/asset/<access_token>``) are already unguessable.
* HTML, SVG, XML and JavaScript assets at ``/asset/<access_token>`` are sent
  as downloads rather than opened in the browser. Serve such files that a
  page must display from ``static/`` instead.
* ``compile_nodes_from_directory`` reads media from ``static/``: move the
  files there from ``data/``, replace ``asset_label`` with ``url_key``, and
  pass ``self.definition["url"]`` to prompts.
* Ready-made stimuli can live in ``static/`` and be referenced with
  ``psynet.media.static_url_for``; see :doc:`/code/using_stimuli`.
* ``/on-demand-asset?id=…`` URLs no longer work. Use the asset's ``url``
  attribute instead, which has the form ``/asset/<access_token>``.
* With the default local asset storage and in-place navigation, audio and
  video recordings now upload after the page is submitted. A later
  page that plays back or processes a recording must wait for it and handle a
  missing one. Replace a ``wait_while`` on ``.deposited`` followed by
  playback with::

      from psynet.page import InfoPage, wait_for_recording

      wait_for_recording(lambda participant: participant.assets["recording"]),
      PageMaker(
          lambda participant: playback(participant)
          if participant.assets["recording"].deposited
          else InfoPage("Recording unavailable. Please continue.", time_estimate=5),
          time_estimate=5,
      ),

  Trial analysis such as ``analyze_recording`` and trial feedback already
  wait.
* With local asset storage and in-place timeline transitions (the
  defaults), uploaded recordings have a size limit, and a larger one fails
  its trial. An audio recording may be as large as an uncompressed WAV lasting one and
  a half times the control's ``duration`` plus 5 seconds, up to 128 MiB,
  so a page that stops recording on its own event should set ``duration``
  to the longest expected recording. Other recordings, such as video, may
  be up to 128 MiB.
* With the same defaults, a bot's ``bot_response_media`` must be a WAV
  file for audio and a WebM file for video.

19. Async jobs
--------------

Search for ``psynet.process``, ``AsyncProcess``, ``WorkerAsyncProcess``,
``LocalAsyncProcess``, ``async_processes`` and ``process_id``.

* Async processes are now called async jobs, and live in
  ``psynet.async_job``: ``AsyncJob``, ``WorkerAsyncJob`` and
  ``LocalAsyncJob``.
* Creating a job no longer runs it. Call ``.enqueue()``, which launches the
  job once the transaction commits::

      from psynet.async_job import WorkerAsyncJob

      WorkerAsyncJob(function=analyse, arguments={"trial": trial}).enqueue()

  PsyNet logs a warning when a job is created but never enqueued.
* The old names still work but warn. ``WorkerAsyncProcess(...)`` and
  ``LocalAsyncProcess(...)`` create and enqueue the job, and
  ``AsyncJob.get_process`` calls ``get_async_job``. A subclass of
  ``WorkerAsyncProcess`` or ``LocalAsyncProcess`` becomes a subclass of the
  new class, so call ``.enqueue()`` on its jobs.
* ``async_processes`` on participants, trials, nodes, networks, responses
  and assets is now ``async_jobs``.
* An override of ``Experiment.handle_error`` that reads ``process=`` should
  read ``async_job=``; ``ErrorRecord.process_id`` is now ``async_job_id``.
* In exports, ``database/process.csv`` is now ``database/async_job.csv``,
  and its ``type`` column holds names such as
  ``psynet.async_job.WorkerAsyncJob``. ``error.csv`` has ``async_job_id``
  instead of ``process_id``, and ``participant.csv`` has
  ``awaited_async_code_block_job_id``.

See :doc:`/reference/api/async_job`.

20. Exports and analysis scripts
--------------------------------

Search scripts and notes for ``--assets all``, ``--legacy``,
``--anonymize``, ``psynet.zip``, ``database.zip``, ``extra_var``,
``claim_var``, ``export_classes_to_skip`` and ``min_group_size``.

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
  ``psynet.export.unpack_json_column``. Delete ``@extra_var`` and
  ``register_extra_var``, and write ``claim_var(name)`` without the
  ``__extra_vars__`` dict, which now raises ``TypeError``.
* ``export_classes_to_skip`` no longer has an effect; delete it.
* The ``sync_group`` table's ``min_group_size`` column is now ``quorum``.
* Search experiment code for ``copy_expert``, ``copy_from``, ``copy_to`` and
  ``COPY``. In a web request or background job, PostgreSQL ``COPY`` must run
  inside :func:`psynet.db.blocking_psycopg`, or psycopg2 raises
  ``ProgrammingError``.
* ``LanguageVocabularyTest`` answers are now screen positions (``"1"`` to
  ``"4"``) rather than image names. Find the asset key of the chosen image
  with ``LanguageVocabularyTrial.image_keys[definition["order"][int(answer) - 1]]``;
  the correct image is ``"image_correct"``.
* An unfinished trial, abandoned or still running at export time, can now
  have an ``answer``: the answer so far, copied from its pages before
  ``format_answer`` runs. Filter on ``complete`` as well as ``failed`` when
  analysing answers.

See :doc:`/data/what_an_export_contains`.

21. Validate
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

Bots in parallel tests (``--parallel`` or ``test_mode = "parallel"``) and in
``psynet performance-test`` now run as threads that share one experiment
instance, instead of a process each. Large performance tests spread the
bots over several such processes (see
:ref:`performance_testing_bot_processes`). Bot code that keeps state at
module level or on ``self``, such as a global counter or ``random.seed()``,
now affects every bot in the same process: store per-bot traits on
``bot.var`` in ``initialize_bot``, and use a ``random.Random()`` instance.
See :ref:`parallel_bot_tests`.

Other test commands changed too:

* ``psynet simulate`` is removed. Use ``psynet audit simulate``, which needs
  an audit packet and writes its export to
  ``audit/simulate/analysis/simulated_export/``; see
  :doc:`/test/audit_reference`.
* ``psynet performance-test ssh`` runs only on apps it deployed itself, so
  you no longer run ``psynet debug ssh`` first. In Python,
  ``PerformanceTester.run`` is replaced by
  ``PerformanceSuite(tester).run(bot_counts)`` and
  ``PerformanceSuite(tester).find_capacity()``; see
  :doc:`/test/scalability`.

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

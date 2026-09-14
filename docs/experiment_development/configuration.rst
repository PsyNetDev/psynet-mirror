.. _configuration:

.. |dlgr-icon| raw:: html

    <img src="../_static/images/dallinger.jpg" width="15" style="margin-bottom: -1px; margin-left: 3px; cursor: pointer;" title="Dallinger"/>

.. |psynet-icon| raw:: html

    <img src="../_static/images/psynet.png" width="15" style="margin-bottom: -1px; margin-left: 3px; cursor: pointer;" title="PsyNet"/>

.. |sensitive-icon| raw:: html

    <img src="../_static/images/sensitive.png" width="15" style="margin-bottom: -1px; margin-left: 3px; cursor: pointer;" title="Sensitive"/>

Configuration
=============

Setting config variables
^^^^^^^^^^^^^^^^^^^^^^^^

Setting config variables can be done in multiple ways depending on the type of a variable.

Global variables
++++++++++++++++

Global variables should be set via the `.dallingerconfig` file in your home directory. This applies in particular to those which have to be keep secret and which should under no circumstances be added to Git. They are global in the sense that they apply to all experiments being developed and deployed by the user. Declaration of global variables allows for the grouping into freely to be chosen sections. For example:

.. code-block:: text

    [AWS]
    aws_access_key_id = your-secret-aws-access-key-id

    [Email]
    contact_email_on_error = some-email@provider.com


Experiment-specific variables
+++++++++++++++++++++++++++++

Every experiment directory must include a ``config.txt`` file. The file may be
empty. PsyNet still requires it to be present before local debug/test and
deployment.

Experiment-specific variables can be set in two ways – firstly via that
``config.txt`` file, which follows the same syntactic rules as the one for
global variables above. For example:

.. code-block:: text

    [Custom settings]
    show_early_exit_button = true
    base_payment = 1.2
    currency = €

Secondly, they can also be set by creating a config dictionary in the ``Experiment`` class like this:

.. code-block:: python

    class Exp(Experiment):
        config = {
            "wage_per_hour": 12.0,
            "show_early_exit_button": True,
        }

Do not set the same key in both places. If a variable appears in both
``config.txt`` and ``Experiment.config``, PsyNet raises an error and asks you
to keep just one location.

.. note::

    When setting variables via `config.txt` or `.dallingerconfig` boolean values can be assigned be either using ``true``, ``True``, ``false``, or ``False``.

.. note::

    **Upgrading an older experiment.** Older PsyNet versions sometimes ran
    without a real ``config.txt`` (for example when all settings lived in
    ``Experiment.config``). If you upgrade such an experiment and PsyNet
    complains that ``config.txt`` is missing, create an empty file in the
    experiment directory::

        touch config.txt

    Prefer that over ``psynet scripts scaffold`` / ``psynet setup`` if you
    already manage settings in Python: scaffolding writes a demo template with
    active keys (title, recruiter, and so on), which will conflict with any
    overlapping keys in ``Experiment.config``. An existing ``config.txt`` —
    including an empty one — is never overwritten by scaffold or update.


Load order and precedence
^^^^^^^^^^^^^^^^^^^^^^^^^

Config variables can be set via several sources. When the same variable is set
in more than one source, the value from the higher-priority source wins.
The sources are, from highest to lowest priority:

1. **Runtime writes** — values set from code through ``config.set()``,
   ``config.extend()``, or ``config.override()``.
2. **Environment variables** — variables named after config keys
   (e.g. ``dashboard_user``).
3. **config.txt** — the experiment-specific config file in the experiment's
   root directory.
4. **The ``Experiment.config`` dictionary** in ``experiment.py``. Although
   ``config.txt`` formally takes precedence, PsyNet raises an error at
   deployment time if the same variable is set in both places.
5. **~/.dallingerconfig** — the global, per-user config file in your home
   directory.
6. **PsyNet experiment defaults** — values from
   ``Experiment.config_defaults()``.
7. **Dallinger package defaults** — values from
   ``local_config_defaults.txt`` and ``global_config_defaults.txt``.

Note in particular that values set in the ``Experiment.config`` dictionary
override values set in ``~/.dallingerconfig``: they are the experiment's
explicit decisions, not defaults. Only environment variables (and runtime
configuration writes) take precedence over them; PsyNet logs a warning at
deployment time if that happens.

After the experiment package has been initialized, web, worker, and clock
processes continue loading its experiment-specific layers after changing into
a non-experiment directory. Environment variables and runtime writes may still
differ between processes.


Available config variables
^^^^^^^^^^^^^^^^^^^^^^^^^^

Config variables originate from either *PsyNet* |psynet-icon| or *Dallinger* |dlgr-icon|, the latter being the software PsyNet is built upon. What follows is an exhaustive list of all known config variables grouped into specific sections and sorted alphabetically. Sensitive variables are marked with |sensitive-icon|.


General
+++++++

``base_port`` *int* |dlgr-icon|
    The port to be used to access the web application. Normally there should not be the need to change this from the default. Default ``5000``.

``check_dallinger_version`` *bool* |psynet-icon|
    Set this to ``False`` if you want to bypass the check for the version of Dallinger that is recommended for the current PsyNet release. This allows for flexibility, e.g. when deploying `Dallinger` development branches.
    Default: ``True``.

``check_participant_opened_devtools`` *bool* |psynet-icon|
    If ``True``, whenever a participant opens the developer tools in the web browser,
    this is logged as participant.var.opened_devtools = ``True``,
    and the participant is shown a warning alert message.
    Default: ``False``.

    .. note::

        Chrome does not currently expose an official way of checking whether
        the participant opens the developer tools. People therefore have to rely
        on hacks to detect it. These hacks can often be broken by updates to Chrome.
        We've therefore disabled this check by default, to reduce the risk of
        false positives. Experimenters wishing to enable the check for an individual
        experiment are recommended to verify that the check works appropriately
        before relying on it. We'd be grateful for any contributions of updated
        developer tools checks.

``color_mode`` *str* |psynet-icon|
    The color mode to be used. Must be one of ``light``, ``dark``, or ``auto``. Default: ``light``.

``dallinger_develop_directory`` *str* |dlgr-icon|
    The directory on your computer to be used to hold files and symlinks
    when running ``dallinger develop``. Defaults to ``~/dallinger_develop``
    (a folder named ``dallinger_develop`` inside your home directory).

``dashboard_password`` *str* |dlgr-icon| |sensitive-icon|
    An optional password for accessing the Dallinger Dashboard interface. If not
    specified, a random password will be generated.

``dashboard_user`` *str* |dlgr-icon| |sensitive-icon|
    An optional login name for accessing the Dallinger Dashboard interface. If not
    specified ``admin`` will be used.

``enable_global_experiment_registry`` *bool* |dlgr-icon|
    Enable a global experiment id registration. When enabled, the ``collect`` API
    check this registry to see if an experiment has already been run and reject
    re-running an experiment if it has been.

    .. note::

        This concerns a Dallinger feature not currently used by PsyNet.

``inplace_timeline_transitions`` *bool* |psynet-icon|
    When ``True`` (default), PsyNet keeps the browser document open and swaps
    timeline page content in place. Custom pages must use fragment templates
    and managed asset arguments; see :doc:`/whats_new/upgrading_to_psynet_14`
    and :doc:`/tutorials/writing_custom_frontends`. Prefer opting out for a
    single page with ``requires_full_page_reload=True`` on that page's
    constructor. Set this config to ``False`` only as a temporary
    experiment-wide opt-out while migrating. Default: ``True``.

``label`` *str* |psynet-icon|
    This variable is used internally for data export.

    .. note::

        This feature may be revised in the future.

``legacy_js_var_globals`` *str* |psynet-icon|
    Controls deprecated access to page ``js_vars`` through matching ``window``
    properties. ``warn`` preserves access and reports each key once in the
    browser console, ``error`` raises an informative ``ReferenceError``, and
    ``off`` installs no compatibility properties. Accessors are never
    installed for names that already exist on ``window`` (for example
    ``name``, ``status``, ``event``, ``history``); those page values remain
    available on ``psynet.var``, and page construction warns for common
    collisions. New code should read ``psynet.var`` directly. Default:
    ``warn``.

``lock_table_when_creating_participant`` *bool* |dlgr-icon|
    Prevents possible deadlocks on the `Participant` table.
    Historically we have locked the participant table when creating participants
    to avoid database inconsistency problems. However some experimenters have experienced
    some deadlocking problems associated with this locking, so we have made
    it an opt-out behavior. Default: ``True``.

``logfile`` *str* |dlgr-icon|
    Where to write logs.

``loglevel`` *int* |dlgr-icon|
    A number between 0 and 4 that controls the verbosity of logs and maps to
    one of ``debug`` (0), ``info`` (1), ``warning`` (2), ``error`` (3), or
    ``critical`` (4). Note that ``psynet debug`` ignores this setting and
    always runs at 0 (``debug``). Default: ``0``.

``loglevel_worker`` *int* |dlgr-icon|
    A number between 0 and 4 that controls the verbosity of worker logs and maps to
    one of ``debug`` (0), ``info`` (1), ``warning`` (2), ``error`` (3), or
    ``critical`` (4). Default: ``1``.

``needs_internet_access`` *bool* |psynet-icon|
    Indicates whether the experiment needs internet access. Can be set to ``False`` for lab or field studies.
    Default: ``True``.

``protected_routes`` *str* |dlgr-icon|
    An optional JSON array of Flask route rule names which should be made inaccessible.
    Example::

        protected_routes = ["/participant/<participant_id>", "/network/<network_id>", "/node/<int:node_id>/neighbors"]

    Accessing routes included in this list will raise a ``PermissionError`` and no data will be returned.

``show_early_exit_button`` *bool* |psynet-icon|
    If ``True``, participants may request to leave early. The timeline footer
    then includes **Leave** (a page may
    still hide it with ``show_early_exit_button=False``). **Leave** opens an in-page
    confirmation, so choosing **Cancel** preserves the current page and
    response state. When an error makes continuation impossible, PsyNet
    follows the recruiter's tracked recovery policy. Generic, local, and lab
    recruitment has nothing to ask, so PsyNet commits the plan on the server
    and still tells the participant that an error occurred, without a Finish
    or Submit control. Prolific and Lucid
    keep a recovery page with the platform action they need. The ad page does
    not provide an exit control.
    Confirming a paid leave marks the participant failed, so Prolific uses the
    unsuccessful/partial-payment route; Lucid terminates the panel session.
    **Leave** is never offered once the participant is finishing (the
    end-of-experiment pages, the release pages, or a participant who has
    already left), because leaving there could only reduce their payment.
    Default: ``False``.

    ``Page(show_abort_button=...)`` and ``Page(show_termination_button=...)`` are
    deprecated aliases for the per-page override; use
    ``show_early_exit_button=...`` on the page instead.

    Confirmation copy is outcome-based: it states whether the participant will
    be paid, with concrete amounts where PsyNet can compute them. Paid
    recruiters gate *paid* leave on ``min_reward_for_paid_early_exit``. Below
    that threshold, Leave still opens a confirmation that offers
    **Leave without payment** (responses saved, no PsyNet payment, and
    platform-specific return instructions). Automatic error recovery ignores
    the voluntary payment threshold and uses the recruiter's configured error
    outcome. Lucid always permits termination and never talks about PsyNet
    payment.

    PsyNet represents every terminal outcome with an
    :class:`~psynet.exit.ExitPlan`: successful completion, unsuccessful
    completion, rejected consent, voluntary Leave, and fatal-error recovery.
    The plan records the outcome, recruiter path, and
    :class:`~psynet.exit.PaymentDecision` that will be used when payment is
    processed. Its :class:`~psynet.exit.PaymentState` distinguishes a complete
    decision, a decision deferred after an error, and recruiters for which
    PsyNet payment is not applicable. It is stored on
    :attr:`~psynet.participant.Participant.exit_plan`, giving recruiter handoff
    and later payment settlement one source of truth.
    Spend caps are still applied immediately before transfer.

    Voluntary Leave prepares one stable plan when the participant enters a page
    and commits it only after the participant confirms. Rendering the page does
    not change the offer, and refreshing restores the same plan. Successful and
    unsuccessful timeline endings commit their plans as they enter their
    existing end branches. After a fatal error, PsyNet stores one recovery plan
    during the failing request. Recruiters with nothing to ask (generic,
    HotAir, and lab) commit that plan on the server, finalize the worker
    session, and still show that an error occurred, with no extra click.
    Recruiter exit is reserved for finished and voluntary-leave sessions.
    Prolific and Lucid still show a recovery
    page and commit when the participant continues (or Lucid's redirect timer
    fires). If that recovery page is refreshed before the plan commits, PsyNet
    restores the same presentation so an unfinished platform handoff can
    resume.

    Experiments can customize voluntary Leave copy by overriding
    :meth:`~psynet.experiment.Experiment.plan_exit` and replacing the
    confirmation while preserving the planned path::

        from dataclasses import replace
        from psynet.exit import ExitContext

        class Exp(Experiment):
            def plan_exit(self, participant, context):
                plan = super().plan_exit(participant, context)
                if context is ExitContext.VOLUNTARY:
                    plan = replace(
                        plan,
                        confirmation=replace(
                            plan.confirmation,
                            message="Your responses so far will still be saved.",
                        ),
                    )
                return plan

    The same hook receives ``ExitContext.ERROR_RECOVERY`` for fatal errors; the
    recruiter does not apply the voluntary paid-exit threshold in that context.
    If the detailed reward calculation itself fails, Prolific records a
    deferred payment decision, uses recovery copy without a reward quote, and
    calculates the unquoted remainder when payment is processed.

    Recruiters provide both tracked and untracked error-page content through
    :meth:`~psynet.recruiters.PsyNetRecruiterMixin.error_page_presentation`.
    The hook receives an optional participant and plan and always returns an
    :class:`~psynet.exit.ErrorRecoveryPresentation`, which declares the
    copy and any POST, button, or redirect required by the platform. Whether
    tracked fatal recovery *shows* that page is a separate recruiter policy,
    :meth:`~psynet.recruiters.PsyNetRecruiterMixin.shows_error_recovery_page`,
    not an inference from a missing button. The mixin default is to skip that
    page; a custom recruiter that presents recovery UI must override the
    policy. Override
    ``error_page_presentation`` on a custom recruiter to customize error pages;
    ``Experiment.error_page_content`` and recruiter ``error_page_content``
    overrides are no longer supported. A tracked participant is never treated
    as an unidentified session: if they already left through a voluntary plan,
    that plan's presentation is reused; if they have no plan, the recruiter
    still addresses them     as a known participant. Fatal errors record the
    exception type on ``failure_tags`` and fail the session with
    ``error_recovery`` when a recovery plan is stored. Error-page Submit,
    Continue, and auto-redirect are armed only while that recovery plan is
    still prepared; a reused committed plan keeps its explanation copy without
    those controls.

    Once a participant has been created, PsyNet stores fatal recovery during
    the failing request. Recruiters that present recovery UI render it from
    ``/timeline?unique_id=<unique-id>``; generic recovery is already committed
    by then, so ``/timeline`` finalizes the session and still renders the error
    page.
    Reloading therefore re-reads the stored plan instead of running it again.
    ``/error-page`` is reserved for untracked errors and never treats an
    enumerable participant ID as session authority. Errors encountered while
    creating the participant still use Dallinger's error response so that
    specific refusal explanations remain available.

    Experiments may also override
    :meth:`~psynet.experiment.Experiment.early_exit_allowed` to customize when
    paid leave is available.

``show_reward`` *bool* |psynet-icon|
    If ``True``, then the participant's current estimated reward is displayed
    at the bottom of the page, and the end-of-experiment page reports it.
    If left unset, the recruiter decides: Prolific and the lab recruiters show
    the reward, while generic and local recruitment does not, because PsyNet
    cannot pay anyone in those cases. Lucid recruitment forbids showing rewards.

``show_footer`` *bool* |psynet-icon|
    If ``True`` (default), then a footer may be displayed at the bottom of the
    page. It holds reward information if ``show_reward`` resolves to ``True``, a
    `Comment` button if ``leave_comments_on_every_page`` is set, and **Leave** if
    ``show_early_exit_button`` is set or the recruiter requires one (Lucid). The
    footer is omitted when none of these apply, so that an empty bar does not
    take up space.

``show_progress_bar`` *bool* |psynet-icon|
    If ``True`` (default), then a progress bar is displayed at the top of the page.

``timeline_lock_timeout_seconds`` *float* |psynet-icon|
    Maximum time participant-facing timeline writes wait for a database lock
    before returning a temporary-busy response. Set to ``0`` to disable the
    timeout. Default: ``5.0``.

``whimsical`` *bool* |dlgr-icon|
    When set to True, this config variable enables 'whimsical' tone on Dallinger email notifications
    to the experimenter. When ``False`` (default), the notifications have a matter-of-fact tone.

``window_height`` *int* |psynet-icon|
    Determines the width in pixels of the window that opens when the
    participant starts the experiment. Only active if
    recruiter.start_experiment_in_popup_window is True.
    Default: ``768``.

``window_width`` *int* |psynet-icon|
    Determines the width in pixels of the window that opens when the
    participant starts the experiment. Only active if
    recruiter.start_experiment_in_popup_window is True.
    Default: ``1024``.


Payment
+++++++

``base_payment`` *float* |dlgr-icon|
    Base payment in the currency set via the ``currency`` config variable.
    Successful participants receive this much compensation from the recruiter.

``big_base_payment`` *bool* |psynet-icon|
    Set this to ``True`` if you REALLY want to set ``base_payment`` to a value > 20.
    Default: ``False``.

``currency`` *str* |psynet-icon|
    The currency in which the participant gets paid. Default: ``$``.

``hard_max_experiment_payment`` *float* |psynet-icon|
    Guarantees that in an experiment no more is spent than the value assigned.
    A bonus that would exceed this value is clipped to remaining room (or not
    paid if that remainder is below $0.01). ``planned_bonus`` stays the
    decided amount, delivered ``bonus`` is what was sent, and
    ``bonus_status = capped``. Default: ``1100.0``.

``max_participant_payment`` *float* |psynet-icon|
    The maximum payment, in the currency set via the ``currency`` config variable, that a participant is allowed to get. Default: ``25.0``.

``min_reward_for_paid_early_exit`` *float* |psynet-icon|
    The minimum accumulated reward, in the currency set via the ``currency``
    config variable, required before a paid recruiter offers *paid* footer **Leave**.
    Below this threshold, **Leave** still opens a confirmation that offers leaving
    without payment. Lucid termination is not gated by this value.
    Default: ``0.20``.

``soft_max_experiment_payment`` *float* |psynet-icon|
    The recruiting process stops if ``amount_spent()`` (recorded
    ``base_payment`` + ``bonus`` for every participant, including those
    still in progress) exceeds this value, in the currency set via the
    ``currency`` config variable. Default: ``1000.0``.

``wage_per_hour`` *float* |psynet-icon|
    The payment in currency the participant gets per hour. Default: ``9.0``.


Recruitment
+++++++++++

General
~~~~~~~

``auto_recruit`` *bool* |dlgr-icon|
    A boolean on whether recruitment should be automatic.

``description`` *str* |dlgr-icon|
    A description of the study used in deployment metadata. The default Lab
    ad page does not render this value.

``initial_recruitment_size`` *int* |dlgr-icon|
    The number of participants initially to be recruited. This value is used during the
    experiment's launch phase to start the recruitment process. Default: ``1``.

``recruiter`` *str* |dlgr-icon|
    The recruiter class to use during the experiment run. While this can be a
    full class name, it is more common to use the class's ``nickname`` property
    for this value; for example ``prolific``, ``generic``, ``hotair``, or
    ``lucid-recruiter``. PsyNet does not support Dallinger's ``mturk``, ``bots``,
    or ``multi`` recruiters.

    .. note::

        When running in debug mode, the HotAir recruiter (``hotair``) will
        always be used. PsyNet's testing commands may use Dallinger's
        BotRecruiter internally; this does not make ``recruiter = bots`` a
        supported deployment configuration.

``recruiters`` *str* |dlgr-icon|
    A Dallinger configuration key for the ``multi`` recruiter. PsyNet does not
    support multi-recruiter deployments; deploy separate experiment instances
    for each recruitment platform instead.

``title`` *str* |dlgr-icon|
    The participant-facing title of the study.

Allowed browsers and devices
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``allow_mobile_devices`` *bool* |psynet-icon|
    Allows participants to take the experiment on a phone or tablet. If
    ``False``, they are asked to switch to a computer.
    Default: ``True``.

``force_google_chrome`` *bool* |psynet-icon|
    Forces the user to use the Google Chrome browser. If another browser is used, it will give detailed instructions on how to install Google Chrome.
    Default: ``True``.

    .. note::

        PsyNet only officially supports Google Chrome.


``leave_comments_on_every_page`` *bool* |psynet-icon|
    Adds a comment box for the experimenter, which is shown on the "Help" modal. This feature is particularly useful for lab or field experiments, where the experimenter can leave comments on every page of the experiment. This is an opt-in feature, and is not enabled by default.
    Default: ``False``.


``force_incognito_mode`` *bool* |psynet-icon|
    Forces the user to open the experiment in a private browsing (i.e. incognito mode). This is helpful as incognito
    mode prevents the user from accessing their browsing history, which could be used to influence the experiment.
    Furthermore it does not enable addons which can interfere with the experiment. If the user is not using
    incognito mode, it will give detailed instructions on how to open the experiment in incognito mode.
    Default: ``False``.

``min_browser_version`` *str* |psynet-icon|
    The minimum version of Chrome a participant needs to take a study.
    Default: ``105.0``.

    Chrome 105 (August 2022) is the first release supporting CSS ``:has()``, which the
    default participant theme uses to style selected response options. Lowering this
    value is supported, but participants on older browsers will not see selected
    options highlighted.

Recruiters
~~~~~~~~~~

General
-------

``publish_experiment`` *bool* |dlgr-icon|
    Whether the experiment should be published when deploying. It is currently used in Prolific and Lucid recruitment: In the case of Prolific recruitment, if ``False`` a draft study will be created which later can be published via the Prolific web UI; in the case of Lucid recruitment, if ``False`` an awarded survey will be created which later can be published (set 'live') via the Lucid web UI. Default is ``True``.
    Default: ``True``.

General infrastructure
----------------------

``aws_access_key_id`` *str* |dlgr-icon| |sensitive-icon|
    AWS access key ID used for services such as EC2 and S3.

``aws_region`` *str* |dlgr-icon|
    AWS region to use. Default: ``us-east-1``.

``aws_secret_access_key`` *str* |dlgr-icon| |sensitive-icon|
    AWS access key secret.

``browser_exclude_rule`` *str* |dlgr-icon|
    A set of rules you can apply to prevent participants with unsupported web
    browsers from participating in your experiment. Valid exclusion values are:

    * ``mobile``
    * ``tablet``
    * ``touchcapable``
    * ``pc``
    * ``bot``

``disable_when_duration_exceeded`` *bool* |dlgr-icon|
    Whether to disable recruiting when the duration has been exceeded. PsyNet
    requires this setting to be ``False``.

``duration`` *float* |dlgr-icon|
    Maximum experiment duration in hours.

Lab Recruiter
-------------

``lab_recruiter_auth_token`` *str* |psynet-icon| |sensitive-icon|
    Authentication token for communication with the API of the Lab Recruiter web application.
    Store the raw key from ``drf_create_token`` (not the ``Token `` prefix) in
    ``~/.dallingerconfig``. PsyNet sends it as ``Authorization: Token <value>``
    when posting completion or failure. Deploying with the lab recruiter fails
    if it is unset; local debug still starts without it. In debug without a
    token, completion posts are skipped and treated as successful so
    participants are not left in payment review. Do not put this key in
    ``config.txt``; it is marked sensitive and would fail the experiment config
    check. As with any config key, an environment variable of the same name
    (``lab_recruiter_auth_token``) overrides ``~/.dallingerconfig``.

``lab_recruiter_external_submission_url`` *str* |psynet-icon|
    Override the default external submission URL (where completion/failure outcomes are posted).
    
    Default URLs are:
    
    * ``lab-recruiter``: ``https://recruiter.cococo-lab.cornell.edu/tasks``
    * ``staging-lab-recruiter``: ``https://recruiter-staging.cococo-lab.cornell.edu/tasks``
    * ``dev-lab-recruiter``: ``http://localhost:8000/tasks``

    ``psynet debug local`` uses ``dev-lab-recruiter`` when
    ``debug_recruiter = dev-lab-recruiter``.

Lucid
-----

``lucid_api_key`` *str* |psynet-icon| |sensitive-icon|
    The key used to access the Lucid/Cint API.

``lucid_sha1_hashing_key`` *str* |psynet-icon| |sensitive-icon|
    The key used to create the HMAC used in the SHA1 hash function that generates the hash
    used when sending requests to the Lucid/Cint API.

``lucid_recruitment_config`` *unicode – JSON formatted* |psynet-icon|

Prolific
--------

``prolific_api_token`` *str* |dlgr-icon| |sensitive-icon|
    A Prolific API token is requested from Prolific via email or some other non-programmatic
    channel, and should be stored in your ``~/.dallingerconfig`` file.

``prolific_api_version`` *str* |dlgr-icon|
    The version of the Prolific API you'd like to use

    The default (``v1``) is defined in *global_config_defaults.txt*.

``prolific_estimated_completion_minutes`` *int* |dlgr-icon|
    Estimated duration in minutes of the experiment or survey.

``prolific_is_custom_screening`` *bool* |dlgr-icon|
    Whether or not this study includes a custom screening. Default: `False`.
    See https://docs.prolific.com/api-reference/studies/create-study for more information.

``prolific_project`` *str* |dlgr-icon|
    The Prolific project identifier.

``prolific_recruitment_config`` *str* |dlgr-icon|
    JSON data to add additional recruitment parameters.
    Since some recruitment parameters are complex and are defined with relatively complex
    syntax, Dallinger allows you to define this configuration in raw JSON. The parameters
    you would typically specify this way :ref:`include <json-config-disclaimer>`:

    * ``device_compatibility``
    * ``peripheral_requirements``

    See the `Prolific API Documentation <https://docs.prolific.com/api-reference/studies/create-study>`__
    for details.

    Configuration can also be stored in a separate JSON file, and included by using the
    filename, prefixed with ``file:``, as the configuration value. For example, to use a
    JSON file called ``prolific_config.json``, you would first create this file, with
    valid JSON as contents::

        {
            "device_compatibility": ["desktop"],
            "peripheral_requirements": ["audio", "microphone"]
        }

    Supported devices are ``desktop``, ``tablet``, and ``mobile``.
    Supported peripherals are ``audio``, ``camera``, ``download`` (download additional software to run the experiment), and ``microphone``.

    You would then include this file in your overall configuration by adding the following
    to your config.txt file::

        prolific_recruitment_config = file:prolific_config.json

    .. _json-config-disclaimer:

    .. caution::

        While it is technically possible to specify other recruitment values this way
        (for example, ``{"title": "My Experiment Title"}``), we recommend that you stick to the standard
        ``key = value`` format of ``config.txt`` whenever possible, and leave ``prolific_recruitment_config``
        for complex requirements which can't be configured in this simpler way.

``prolific_workspace`` *str* |dlgr-icon|
    The Prolific workspace identifier.

Partial payment
...............

The following variables concern the situation in Prolific experiments where participants cannot
proceed to a successful completion, for example because they fail a pre-screening test or hit an
error. These settings do not apply to participants who reach a successful end page; successful
participants are approved and receive the base payment even if their accumulated reward is lower
than the base payment.

By default (``prolific_pay_unsuccessful = true``), PsyNet registers an additional Prolific
completion code (of type ``UNSUCCESSFUL``) with a fixed screen-out payment action. That code is
researcher-actor: when the participant clicks Submit, PsyNet completes the submission on Prolific
on their behalf. Participants do not enter a completion code. Prolific automatically pays them
this fixed amount; PsyNet additionally pays a bonus topping them up to their accumulated reward
(see ``prolific_unsuccessful_topup``). For participants who hit an error page, PsyNet finalizes
the recovery plan automatically and then explains the payment outcome. **Submit to Prolific**
sends the submission with the same completion code. Participants then see a confirmation
page that the submission has been sent to Prolific, and do not enter a completion code.
Successful participants click **Finish**, then **Submit to Prolific**; after Submit, recruiter-exit
reloads that same confirmation rather than leaving the submit heading on a done page.
Successful participants are completed with a researcher-actor
copy of the DEFAULT auto-approve code. Because this feature spends money automatically, Prolific
deployments must set ``prolific_screen_out_slots`` explicitly (see below); deployment fails with
an explanatory error otherwise.

.. note::

    Prolific documents the fixed screen-out payment feature as only available to selected
    workspaces (in our testing it was available across all workspaces of our account). If your
    workspace lacks it, Prolific rejects study creation; in that case ask Prolific support to
    enable custom screening for your workspace, or set ``prolific_pay_unsuccessful = false`` to
    disable the feature and fall back to the return-for-bonus flow below.

``prolific_pay_unsuccessful`` *bool* |psynet-icon|
    If ``True`` (default), unsuccessful participants are paid automatically via the screen-out
    completion code described above. Set to ``False`` to restore the previous return-for-bonus
    behavior (see ``prolific_enable_return_for_bonus`` below).

``prolific_unsuccessful_base_payment`` *float* |psynet-icon|
    The fixed amount (in the currency of your Prolific account) that Prolific automatically pays
    participants who fail or error out of the experiment. Must be positive and less than
    ``base_payment`` (a Prolific requirement). Defaults to ``0.25``; studies with
    ``base_payment <= 0.25`` must set it explicitly (or disable the feature).

``prolific_unsuccessful_topup`` *bool* |psynet-icon|
    If ``True`` (default), unsuccessful participants additionally receive a bonus equal to their
    accumulated reward minus ``prolific_unsuccessful_base_payment`` (never negative). If ``False``,
    only their performance reward is paid as a bonus on top of the fixed payment.

``prolific_screen_out_slots`` *int* |psynet-icon|
    The maximum number of screen-out payments Prolific will make before automatically pausing the
    study (a budgeting safeguard imposed by Prolific). **Required** for Prolific deployments when
    ``prolific_pay_unsuccessful`` is enabled, since ``prolific_screen_out_slots x
    prolific_unsuccessful_base_payment`` bounds the study's worst-case screen-out spend; a common
    choice is 10 times ``initial_recruitment_size``. If the limit is reached, the study pauses and
    can be resumed by increasing the slot count via the Prolific interface or API.

.. warning::

    Screened-out submissions do not count towards the study's places on Prolific: each screen-out
    releases its place and Prolific recruits a replacement participant. A study therefore only
    completes once enough participants finish *successfully*. If your experiment screens out a
    large proportion of participants, recruitment (and screen-out payments) will continue until
    the places are filled by successful participants or ``prolific_screen_out_slots`` is
    exhausted — this slot limit is the only budget backstop in the extreme case where almost all
    participants are screened out. Size ``prolific_screen_out_slots`` deliberately if you expect
    a high screen-out rate, and monitor the study's spending via the Prolific interface.

If ``prolific_pay_unsuccessful`` is ``False`` (or the workspace does not support screen-out
payments), PsyNet falls back to the older return-for-bonus flow: PsyNet will check if
``prolific_enable_return_for_bonus`` is ``True`` (default). If so, the
participant will be asked to return the submission in order to receive their payment.
PsyNet will wait for the submission return to be registered and only then make the payment.
Note: The experiment server has to be online still for the payment to be made.
If ``prolific_enable_return_for_bonus`` is ``False``, then PsyNet will instead ask the participant
to return the submission and contact the experimenter for their bonus.

``prolific_enable_return_for_bonus`` *bool* |psynet-icon|
    If ``True``, participants are eligible for a bonus and are asked to return their submission for bonus payment.
    If ``False``, they are asked to return the submission and message the experimenter for their payment.
    Default: ``True``. Only relevant when the screen-out payment flow is disabled
    (``prolific_pay_unsuccessful = false``) or unavailable for your workspace.

.. note::

    Prolific will use the currency of your researcher account and convert automatically
    to the participant's currency.


Monitoring
~~~~~~~~~~
``mute_same_warning_for_n_hours`` *float* |psynet-icon|
    To avoid resending the same error all the time, the same warning is muted for the next n hours. Default: ``1`` h.

``resource_warning_pct`` *float* |psynet-icon|
    If the percentage of the resource is above this value, the value is marked as a warning in the experiment dashboard
    and a warning is sent. Default: ``0.9``.

``resource_danger_pct`` *float* |psynet-icon|
    If the percentage of the resource is above this value, the value is marked as dangerous in the experiment dashboard
    (in red and an error icon) and the experimenter is informed via Slack. Default: ``0.95``.

``minimal_disk_space_warning_gb`` *float* |psynet-icon|
    While relative values are quite useful for memory and CPU, for disk space things become quite critical if values
    are too low. Therefore, we use absolute values for disk space. If the disk space is below this value, the value is
    marked as a warning in the experiment dashboard and a warning is sent. Default: ``5`` GB.

``minimal_disk_space_danger_gb`` *float* |psynet-icon|
    If the absolute disk space is below this value (see ``minimal_disk_space_warning_gb`` for a motivation), the value
    is marked as dangerous in the experiment dashboard (in red and an error icon) and the experimenter is informed via
    Slack. Default: ``2`` GB.

Deployment
++++++++++

General
~~~~~~~

``clock_on`` *bool* |dlgr-icon|
    If the clock process is on, it will enable a task scheduler to run automated
    background tasks. By default, a single task is registered which performs a
    series of checks that ensure the integrity of the database. The configuration
    option ``disable_when_duration_exceeded`` configures the behavior of that task.

``host`` *str* |dlgr-icon|
    IP address of the host.

``port`` *int* |dlgr-icon|
    Port of the host.

``server_pem`` *str* |dlgr-icon|
    Path to the PEM file for SSH authentication when deploying to a server using Docker SSH.
    This file will be used to authenticate SSH connections to the server.
    Can be set in either your experiment's `config.txt` or in `~/.dallingerconfig`:

    .. code-block:: ini

        [Parameters]
        server_pem = /path/to/your/key.pem

EC2
~~~

``ec2_default_pem`` *str* |dlgr-icon|
    Default PEM file for EC2 instances. Default: ``dallinger``.

``ec2_default_security_group`` *str* |dlgr-icon|
    Default security group for EC2 instances. Default: ``dallinger``.

Heroku
~~~~~~

``database_size`` *str* |dlgr-icon|
    Size of the database on Heroku. See `Heroku Postgres plans <https://devcenter.heroku.com/articles/heroku-postgres-plans>`__.

``database_url`` *str* |dlgr-icon| |sensitive-icon|
    URI of the Postgres database.

``dyno_type`` *str* |dlgr-icon|
    Heroku dyno type to use. See `Heroku dynos types <https://devcenter.heroku.com/articles/dyno-types>`__.

``dyno_type_web`` *str* |dlgr-icon|
    This determines how powerful the heroku web dynos are. It applies only to web dynos
    and will override the default set in ``dyno_type``. See ``dyno_type`` above for details
    on specific values.

``dyno_type_worker`` *str* |dlgr-icon|
    This determines how powerful the heroku worker dynos are. It applies only to worker
    dynos and will override the default set in ``dyno_type``.. See ``dyno_type`` above for
    details on specific values.

``heroku_python_version`` *str* |dlgr-icon|
    The python version to be used on Heroku deployments. The version specification will
    be deployed to Heroku in a `runtime.txt` file in accordance with Heroku's deployment
    API. Note that only the version number should be provided (eg: ``3.11.5``) and not the
    ``python-`` prefix included in the final `runtime.txt` format.
    See `Heroku supported runtimes <https://devcenter.heroku.com/articles/python-support#supported-python-versions>`__.

``heroku_region`` *str* |dlgr-icon|
    The Heroku region for deployment. Default: ``None``.

``heroku_team`` *str* |dlgr-icon|
    The name of the Heroku team to which all applications will be assigned.
    This is useful for centralized billing. Note, however, that it will prevent
    you from using free-tier dynos.

``num_dynos_web`` *int* |dlgr-icon|
    Number of Heroku dynos to use for processing incoming HTTP requests. It is
    recommended that you use at least two.

``num_dynos_worker`` *int* |dlgr-icon|
    Number of Heroku dynos to use for performing other computations.

``redis_size`` *str* |dlgr-icon|
    Size of the redis server on Heroku. See `Heroku Redis <https://elements.heroku.com/addons/heroku-redis>`__.

``sentry`` *bool* |dlgr-icon|
    When set to ``True`` enables the `Sentry` (https://sentry.io/) Heroku addon for performance monitoring of experiments. Default: ``False``.

``threads`` *str* |dlgr-icon|
    The number of gunicorn web worker processes started per Heroku CPU count.
    When given the default value of ``auto`` the number of worker processes will be calculated
    using the formula ``round(multiprocessing.cpu_count() * worker_multiplier)) + 1`` by making use
    of the ``worker_multiplier`` config variable. Default: ``auto``.
    ``psynet debug --legacy`` currently starts four workers by default rather
    than ``auto``. Ordinary ``psynet debug local`` is the Flask reloader (one
    process); there is no worker-count flag on that path. Playwright stacked-hold
    tests set
    ``PSYNET_LEGACY_DEBUG_GUNICORN_THREADS`` to the number of sessions so a
    last-arrival ``GET /timeline`` can overlap every waiter hold-resume POST.

``worker_multiplier`` *float* |dlgr-icon|
    Multiplier used to determine the number of gunicorn web worker processes
    started per Heroku CPU count. Reduce this if you see Heroku warnings
    about memory limits for your experiment. Default: ``1.5``.

For help on choosing appropriate configuration variables, also see this Dallinger documentation page at https://dallinger.readthedocs.io/latest/configuration.html#choosing-configuration-values

Docker
~~~~~~

``docker_image_base_name`` *str* |dlgr-icon|
    A string that will be used to name the docker image generated by this experiment.
    Defaults to the experiment directory name (``bartlett1932``, ``chatroom`` etc).
    To enable repeatability a generated docker image can be pushed to a registry.
    To this end the registry needs to be specified in the ``docker_image_base_name``.
    For example:

    * ``ghcr.io/<GITHUB_USERNAME>/<GITHUB_REPOSITORY>/<EXPERIMENT_NAME>``
    * ``docker.io/<DOCKERHUB_USERNAME>/<EXPERIMENT_NAME>``

``docker_image_name`` *str* |dlgr-icon|
    The docker image name to use for this experiment.
    If present, the code in the current directory will not be used when deploying.
    The specified image will be used instead. Example:

    * ``ghcr.io/dallinger/dallinger/bartlett1932@sha256:ad3c7b376e23798438c18aae6e0136eb97f5627ddde6baafe1958d40274fa478``

``docker_volumes`` *str* |dlgr-icon|
    Additional list of volumes to mount when deploying using docker.
    Example:

    * ``/host/path:/container_path,/another-path:/another-container-path``

``docker_worker_cpu_shares`` *int* |dlgr-icon|
    CPU shares for Docker worker containers. Default: ``1024``


Internationalization
++++++++++++++++++++

``allow_switching_locale`` *bool* |psynet-icon|
    Allow the user to change the language of the experiment during the experiment.
    Default: ``False``.

    .. note::

        This feature is still experimental.

``default_translator`` *str* |psynet-icon|
    The default translator to use for translations. Default: ``chat_gpt``.

``disable_browser_autotranslate`` *bool* |dlgr-icon|
    Disable browser autotranslate feature. Default: ``True``.

``google_translate_json_path`` *str* |psynet-icon| |sensitive-icon|
    Path to the Google Translate JSON credentials file. Default: ``None``.

``language`` *str* |dlgr-icon|
    A ``gettext`` language code to be used for the experiment.

``locale`` *str* |psynet-icon|
    The default locale for the experiment. Default: ``en``.

``openai_api_key`` *str* |psynet-icon| |sensitive-icon|
    The OpenAI API key for machine translation. Default: ``None``.

``openai_default_model`` *str* |psynet-icon|
    The default OpenAI model to use for translations. Default: ``gpt-4o``.

``openai_default_temperature`` *str* |psynet-icon|
    The default temperature setting for OpenAI translations. Default: ``0``.

``supported_locales`` *list* |psynet-icon|
    List of locales (i.e., ISO language codes) a user can pick from, e.g., ``["en"]``.
    Default: ``[]``.


Email Notifications
+++++++++++++++++++

``contact_email_on_error`` *str* |dlgr-icon|
    The email address used as the recipient for error report emails, and the email displayed to workers when there is an error.

``dallinger_email_address`` *str* |dlgr-icon|
    An email address for use by Dallinger to send status emails.

``smtp_host`` *str* |dlgr-icon|
    Hostname and port of a mail server for outgoing mail. Default: ``smtp.gmail.com:587``

``smtp_username`` *str* |dlgr-icon|
    Username for outgoing mail host.

``smtp_password`` *str* |dlgr-icon| |sensitive-icon|
    Password for the outgoing mail host.

See `Email Notification Setup <https://dallinger.readthedocs.io/latest/email_setup.html>`__ in the Dallinger documentation for a much more detailed explanation of above config variables and their use.


Notifications
+++++++++++++

``notifier`` *str* |psynet-icon|
    The notifier class to use for experiment notifications. Set to ``slack`` to use Slack for notifications.
    Default: ``logger``.

``experimenter_name`` *str* |psynet-icon|
    The name of the experimenter for notifications and contact information. Default: ``None``.

``slack_bot_token`` *str* |psynet-icon| |sensitive-icon|
    The Slack bot token for notifications. Default: ``None``.

``slack_channel_name`` *str* |psynet-icon|
    The Slack channel name for notifications. Default: ``None``.


Experiment debugging
++++++++++++++++++++

``enable_google_search_console`` *bool* |psynet-icon|
    Used to enable a special route allowing the site to be claimed in the Google Search Console
    dashboard of the computational.audition@gmail.com Google account.
    This allows the account to investigate and debug Chrome warnings
    (e.g. 'Deceptive website ahead'). See `Google Search Console <https://search.google.com/u/4/search-console>`__.
    The route is disabled by default, but can be enabled by assigning ``True``. Default: ``False``.


Misc (internal) variables
+++++++++++++++++++++++++

``chrome-path`` *str* |dlgr-icon|
    Used for darwin (macOS) only.

``EXPERIMENT_CLASS_NAME`` *str* |dlgr-icon|
    Config variable to manually set an experiment class name.

``heroku_app_id_root`` *str* |dlgr-icon|
    Internally used only.

``heroku_auth_token`` *str* |dlgr-icon|
    The Heroku authentication token. Internally used only and set automatically.

``id`` *str* |dlgr-icon|
    Internally used only.

``infrastructure_debug_details`` *str* |dlgr-icon|
    Redis debug info details.

``question_max_length`` *int* |dlgr-icon|
    Dallinger-only variable when using questionnaires. Default: ``1000``.

``replay`` *bool* |dlgr-icon|
    Support for replaying experiments from exported data. Set internally when using the optional ``--replay`` flag to start the experiment locally in replay mode. Default: ``False``.

``webdriver_type`` *str* |dlgr-icon|
    The webdriver type to use when using bots (e.g. when writing tests).
    Possible values are ``chrome``, ``chrome_headless``, and ``firefox``. Default: ``chrome_headless``.
    Also see Dallinger's documentation on writing bots at https://dallinger.readthedocs.io/latest/writing_bots.html#selenium-bots.

``webdriver_url`` *str* |dlgr-icon|
    Used to provide a URL to a Selenium WebDriver instance.
    Also see Dallinger's documentation on scaling Selenium bots at https://dallinger.readthedocs.io/latest/writing_bots.html#scaling-selenium-bots.


Config variables not to be set manually
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. warning::

    Below variables are set automatically and should never be set manually!

``dallinger_version`` *str* |psynet-icon|
    The version of the `Dallinger` package.

``hard_max_experiment_payment_email_sent`` *bool* |psynet-icon|
    Whether an email to the experimenter has already been sent indicating the ``hard_max_experiment_payment``
    had been reached. Default: ``False``. Once this is ``True``, no more emails will be sent about
    this payment limit being reached.

``mode`` *str* |dlgr-icon|
    The value for ``mode`` is determined by the invoking command-line command
    and is set to ``debug`` for local development, ``sandbox`` for a remote
    test deployment, or ``live`` for a production deployment.

``psynet_version`` *str* |psynet-icon|
    The version of the `psynet` package.

``python_version`` *str* |psynet-icon|
    The version of the `Python`.

``soft_max_experiment_payment_email_sent`` *bool* |psynet-icon|
    Whether an email to the experimenter has already been sent indicating the ``soft_max_experiment_payment``
    had been reached. Default: ``False``. Once this is ``True``, no more emails will be sent about
    this payment limit being reached.

=========
PsyNet 14
=========

PsyNet 14 is a major release. Participant pages now change in place instead
of reloading, experiments are set up with a single command, deployments
package exactly the files you list, and exports are built on the server. It
also adds tools for developing experiments with coding agents.

Some of these changes break existing experiments. Each section below says
what to change, and :doc:`upgrading_to_psynet_14` gives the step-by-step
checklist. The
`changelog <https://gitlab.com/PsyNetDev/PsyNet/-/blob/master/CHANGELOG.md>`_
lists every change.

Participant pages
-----------------

**In-place transitions.** When a participant moves on, PsyNet now replaces
the page content instead of loading a new page. Transitions are faster, and
audio, video and custom front ends keep their state between pages. Custom
pages must follow the new page lifecycle: fragment templates, page data read
from ``psynet.var``, and setup code in a page module's ``activate()``
function. Pages that don't raise an error that names the problem. While you
migrate, ``requires_full_page_reload=True`` exempts a single page and
``inplace_timeline_transitions = false`` exempts the whole experiment. See
:doc:`/code/pages/custom_front_ends`.

**A new default theme.** Pages sit on a content panel with a readable line
length, a blue accent and a matching footer and progress bar, and have a dark
palette; ``color_mode = auto`` follows the participant's system setting.
Radio buttons and checkboxes are full-width
rows that are easy to tap. If your CSS targeted bare ``label`` or ``input``
elements, check how those controls look.

**Phones and tablets.** Experiments now accept phones and tablets by default;
set ``allow_mobile_devices = false`` to keep a study desktop-only. The oldest
supported browser is now Chrome 105.

**Leaving and errors.** The **Leave** button now explains what leaving means
for the participant's payment on each recruiter, and error pages are shorter
and consistent. The related names changed to ``early_exit``, for example
``show_early_exit_button`` and ``Participant.early_exited``, and
``error_page_content`` is replaced by ``error_page_presentation``.

**Layout checks.** Every page provides ``psynetLayout.check()``, which
Playwright tests can call to find content that overflows the window or can't
be reached. Pages meant to be taller than the window declare
``expect_scrolling=True``. See :doc:`/test/frontend`.

Setting up experiments
----------------------

**One setup command.** ``pip install psynet`` now installs only a small
command-line tool. ``psynet setup``, run in the experiment directory, creates
the virtual environment, installs the full PsyNet runtime from
``constraints.txt`` and adds the boilerplate files. ``psynet services ensure``
starts PostgreSQL and Redis in Docker. See :doc:`/install` and
:doc:`/code/project/creating_an_experiment`.

**Python.** PsyNet supports Python 3.11 to 3.14, and 3.13 is recommended.
Python 3.10 is no longer supported.

**Coding agents.** ``psynet setup`` adds an ``AGENTS.md`` file and PsyNet's
:doc:`Agent Skills </skills/index>` to the experiment, which tell a coding
agent how to plan, build, test and deploy it. ``psynet audit`` keeps a
record of the work, from the original request to test evidence, for you to
review. See :doc:`/code/project/agentic_programming` and :doc:`/test/audits`.

Trials and groups
-----------------

**Choosing nodes and chains.** ``find_networks``, ``find_node`` and
``prioritize_networks`` are replaced by hooks for each kind of trial maker:
``find_chains``, ``select_chain`` and ``custom_chain_filter`` for chains, and
``find_nodes``, ``select_node`` and ``custom_node_filter`` for static
experiments. A selection hook can return a ``Selection``, whose ``context``
is passed to the trial maker's ``on_trial_created`` hook with the new trial,
and ``Trial.cue`` supports adaptive procedures such as staircases. See
:doc:`/code/writing_a_trial_maker`.

**Failing participants.** Call ``Participant.fail()`` or register a
``ParticipantFailRoutine`` instead of overriding
``Experiment.fail_participant``, which now raises an error. When a
participant leaves or fails, their unfinished trials fail and their
submitted trials are kept.

**Groups.** Barriers can time out participants who wait too long, and
groupers can let the remaining members continue when a group becomes too
small (``fail_participants_below_min_size``). A new dashboard page shows
active groups and waiting participants, and participants see when their
partners are ready. Group membership changes through
``SyncGroup.add_participant()`` and ``remove_participant()``, and custom
barriers implement ``check_waiting_participants()`` and
``choose_who_to_release()``. See :doc:`/code/multiplayer/synchronization`.

Stimuli and assets
------------------

**Stimuli in** ``static/``. Ready-made stimulus files can now live in the
experiment's ``static/`` folder and be referenced by URL, using
``psynet.media.static_url_for``. A deployment can include up to 1024 MB of
files by default. ``compile_nodes_from_directory`` now reads from
``static/``. See :doc:`/code/using_stimuli`.

**Asset classes.** Asset classes are named after how the file is made:
``FileAsset`` replaces ``ExperimentAsset`` and ``CachedAsset``, and
``GeneratedAsset`` replaces ``CachedFunctionAsset``. The old names still work
but warn. The ``personal`` flag is removed. See :doc:`/code/trials/assets`.

Deployment and recruitment
--------------------------

**deploy.toml.** Each experiment's ``deploy.toml`` now decides which files
are deployed; ``.gitignore`` and ``.dockerignore`` no longer do. PsyNet
creates the file when it is missing. If your ``.gitignore`` ignores files
that the new ``deploy.toml`` does not exclude, the next debug, test or deploy
command stops once and lists them, because they would now be deployed. Remote deployments need a Git commit, and stop early if
``constraints.txt`` is out of date. See :doc:`/deploy/how_deployment_works`.

**MTurk is gone.** Amazon is `closing MTurk on September 30, 2026
<https://docs.aws.amazon.com/sagemaker/latest/dg/sms-workforce-management-public.html>`_,
and PsyNet no longer supports it. Experiments configured with the ``mturk``,
``bots`` or ``multi`` recruiter stop with an error; move active studies to
another recruiter before upgrading.

**Prolific.** Participants who fail or hit an error are now paid a small
fixed amount through Prolific by default (``prolific_pay_unsuccessful``).
Whether participants see their reward now depends on the recruiter unless you
set ``show_reward``. See :doc:`/deploy/recruiters/prolific`.

Data export
-----------

**Exports are built on the server.** ``psynet export`` downloads a single
archive that the deployed experiment builds from one consistent snapshot of
the database, and no longer replaces your local database. It first checks
that the deployment matches your experiment directory. Exports go to
``exports/latest/``, with earlier ones kept under ``exports/history/``.

**What an export contains.** By default an export includes the files created
during the study, such as recordings, but not the stimuli you supplied; the
``--assets all`` option is removed. Empty tables are left out, and yes/no columns contain ``True`` and ``False``. See
:doc:`/data/what_an_export_contains`.

Upgrading
---------

1. Work through :doc:`upgrading_to_psynet_14`, which covers each of the
   changes above; in Cursor, ``/upgrade-to-psynet-14`` follows the same
   checklist.
2. Run ``psynet test local``, then a debug deployment, before collecting data.

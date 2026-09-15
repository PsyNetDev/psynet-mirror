.. _experiment_directory:

Experiment directory
====================

A PsyNet experiment implementation is defined by a particular *experiment directory*.
This directory contains all the files you need to run your experiment.
When you deploy an experiment, its deployable files are assembled into the Docker image
that runs on the experiment server.

When you are developing a PsyNet experiment it is good practice to use a *version control system*
for keeping track of changes to your experiment directory.
We recommend *Git*. PsyNet requires an active Git repository so it can record
deployment provenance (commit SHA and dirty state). To learn more visit
:doc:`/tutorials/version_control_with_git`.
PsyNet records the deployed Git commit and whether files selected by the
deployment plan contain uncommitted changes. Selected Git-ignored or untracked
files mark the deployment as dirty; changes outside the deployment plan, or
elsewhere in a parent repository, do not. For reproducible live deployments,
commit your changes before deploying. Experiment-file membership for staging
and deployment comes from ``deploy.toml``, not from Git visibility.

.. warning::

   ``deploy.toml`` planning currently requires a POSIX filesystem and is not
   supported on Windows.

Your experiment directory contains various important files and directories.
Let's talk through what these different files and directories do.
While reading this document, have a look at the experiment directory from a real
PsyNet experiment, the `Carillon Experiment <https://github.com/pmcharrison/2022-consonance-carillon>`_.

-   ``.python-version`` records the Python major and minor version used when the
    experiment was scaffolded. PsyNet generates it from the active interpreter.

-   ``static`` can be used as a storage place for files that the front-end browser can access directly via HTTP.
    Put public, immutable resources such as scripts, images, audio, and video here,
    and then access them via ``https://your-experiment-url/static/your-file.png``.
    These files are baked into the experiment's Docker image. Use PsyNet's asset
    management system instead for generated files, participant recordings, private
    data, or files that need storage-backed caching and export; see
    :doc:`/tutorials/assets`.

    PsyNet applies a deployment-plan size limit, currently 256 MB by default.
    Set the ``EXP_MAX_SIZE_MB`` environment variable when intentionally baking a
    larger static corpus into an image.

-   ``templates`` is used for customising PsyNet’s front-end. It contains
    `Jinja2 templates <https://jinja.palletsprojects.com/en/2.11.x/>`_; Jinja2 is a popular templating library for Python.
    Most experiments do not need to use this folder, but for an example of how to use it, see
    :doc:`/tutorials/writing_custom_frontends`.

-   ``.gitignore`` controls which files Git tracks. It does not control which
    files enter debug staging or deployment; that is ``deploy.toml``.

-   ``deploy.toml`` controls which files enter Dallinger's deployment plan and
    therefore the debug staging directory, Docker build context, or remote
    deployment package. PsyNet creates this file from its template when it is
    missing and never overwrites an existing copy. If a debug or deployment
    command creates the file, that command stops and reports Git-ignored files
    selected by the new policy so that you can review them before rerunning.
    ``psynet scripts scaffold`` and ``psynet scripts update`` also create the
    file when needed. ``[exclude]`` ``paths`` are
    root-relative prefixes; ``names`` are basenames in every directory;
    ``suffixes`` are literal endings such as ``.db``.
    Format, auto-omitted paths, and inspection commands are documented in
    Dallinger's
    `deploy.toml guide <https://github.com/Dallinger/Dallinger/blob/master/docs/source/deploy_toml.rst>`_.
    Stock ``[exclude]`` ``paths`` include ``audit`` (the local review packet),
    ``data``, and ``.cursor/skills/psynet``.
    Existing experiments keep their current ``deploy.toml`` until they add
    those entries themselves; PsyNet never overwrites a custom copy.
    Follow :doc:`/whats_new/upgrading_deployment_file_selection`.
    Inspect the current plan with ``dallinger deployment-files list``.
    ``.dockerignore`` is no longer supported. PsyNet removes recognized
    generated copies; a custom copy blocks debug and deployment until its rules
    are moved into ``deploy.toml`` and the file is removed.

-   ``Dockerfile`` is used by Docker to define the experiment's Docker image. Normally you should not edit this file
    directly, but instead use the boilerplate file provided by PsyNet. You can update this file to
    their latest PsyNet versions by running ``psynet scripts update`` within an experiment directory.
    If the file is missing entirely, you can recreate it with ``psynet scripts scaffold``.

-   ``.cursor/skills/psynet/`` contains PsyNet-managed Agent Skills for experiment
    implementation, validation, deployment, data, and participant evidence.
    ``psynet scripts update`` replaces this managed subdirectory with the version
    shipped by the installed PsyNet release. The directory is gitignored and
    excluded in ``deploy.toml`` so it is not committed or uploaded with the
    experiment; other directories under ``.cursor/skills/`` are
    experiment-owned, preserved on update, and remain eligible to track.

-   ``Dockertag`` determines the name of the Docker image that is built for the present experiment.
    It defaults to the name of the current directory.

-   ``README.md`` is a README file. You should put information about your experiment here for future readers.
    ``psynet scripts scaffold`` and ``psynet scripts update`` create a default README when missing, but never
    overwrite an existing one.

-   ``__init__.py`` is created automatically when you deploy the experiment; it tells Python to treat the directory as a
    package. You don’t need to worry about this file in practice.

-   ``carillon_samples.csv`` is specific to the Carillon Experiment implementation, we don't need to worry about it now.

-   ``config.txt`` is required in every experiment directory (it may be empty).
    It defines configuration parameters for local runs and online deployment.
    New experiments can get a demo template via ``psynet scripts scaffold`` /
    ``psynet setup``. An existing file (including an empty one) is preserved on
    scaffold and update. If you are upgrading an older experiment that never had
    a ``config.txt`` and you keep settings in ``Experiment.config``, create a
    blank file with ``touch config.txt`` rather than scaffolding a full
    template; see :doc:`/experiment_development/configuration`.

-   ``constraints.txt`` stores the locked versions of Python packages used when
    you install or deploy a **standalone** experiment. It is generated
    automatically (do not edit it by hand). Create or refresh it with
    ``psynet setup`` or ``psynet generate-constraints`` (Dallinger's lock
    policy via ``uv run``). Bundled demos omit it because they use the PsyNet
    repository's development environment. ``psynet setup --no-install`` still
    writes a local ``constraints.txt`` without installing into the virtual
    environment.

-   ``experiment.py`` is a Python file that defines the primary experiment logic.
    Split substantial helpers into sibling modules and import them with
    relative imports (see :ref:`experiment_python_modules`).

-   ``instructions.py`` is specific to the Carillon Experiment implementation, we don't need to worry about it now.

-   ``prepare_docker_image.sh`` is an optional file that provides extra setup code that is run when preparing
    the experiment's Docker image. Here we use it to install a particular dependency for stimulus generation.

-   ``pytest.ini`` is a boilerplate PsyNet file, you should not have to edit it yourself.
    If it goes missing, you can recreate it with ``psynet scripts scaffold``.

-   ``questionnaire.py`` is specific to the Carillon Experiment implementation, we don't need to worry about it now.

-   ``requirements.txt`` is where you specify the packages that your experiment will depend on.
    This file should always contain a link to the PsyNet library, for example:

    ::

        psynet@git+https://gitlab.com/psynetdev/psynet@d54c3f7a0afddebe1e53676c47c9a31f9cb9a827#egg=psynet

    This particular example indicates that the experiment should use a particular version of PsyNet from
    GitHub. The version is specified here by the long string that comes after the ``@`` symbol:
    ``d54c3f7a0afddebe1e53676c47c9a31f9cb9a827``.
    This string corresponds to a particular commit hash.
    You can also specify a particular version number here, for example ``10.3.0``.

-   ``server.log`` is an automatically generated log file, don’t worry about it.

-   ``synth.py`` is specific to the Carillon Experiment implementation, we don't need to worry about it now.

-   ``test.py`` is a boilerplate PsyNet file that defines generic tests for the experiment.
    You can run these tests with ``psynet test local``.
    If you want to customize these tests you should normally override specific methods in the Experiment class,
    for example ``Experiment.test_experiment`` and ``Experiment.test_check_bots``.
    If this file is missing, you can regenerate it with ``psynet scripts scaffold``.

    ``volume_calibration.py`` is specific to the Carillon Experiment implementation, we don't need to worry about it now.


.. _experiment_python_modules:

Importing other Python files
----------------------------

You can split experiment code across several ``.py`` files in the experiment
directory. Dallinger imports that directory as the package
``dallinger_experiment``, so siblings of ``experiment.py`` must use relative
imports. Do not run ``python experiment.py`` as a syntax or import check;
use ``psynet test local``.

.. code-block:: python

    from . import adaptive_logic

    def choose_next_item(state):
        return adaptive_logic.select_item(state)

Standalone scripts such as ``python -m audit.simulate.design.core`` use ordinary
top-level imports of the same helpers. Run that command from the experiment
root so those imports resolve. Put calibrated item banks in ``item_bank/``;
stock ``deploy.toml`` omits ``data/``, ``audit/``, and ``exports/``.

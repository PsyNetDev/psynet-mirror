.. _command_line:

============
Command line
============

Run ``psynet`` commands in the experiment directory, with the experiment's
virtual environment active. ``psynet <command> --help`` lists every option.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Command
     - What it does
   * - ``psynet setup``
     - Prepare a standalone experiment: files, ``constraints.txt``,
       packages and Git (see `Set up an experiment (setup)`_).
   * - ``psynet services check`` / ``ensure``
     - Check, or start in Docker, the local PostgreSQL and Redis
       (see `Local PostgreSQL and Redis (services)`_).
   * - ``psynet scripts scaffold`` / ``update`` / ``prune``
     - Create, refresh or remove boilerplate files
       (see `Manage experiment boilerplate (scripts)`_).
   * - ``psynet generate-constraints``
     - Refresh ``constraints.txt`` after changing ``requirements.txt``.
   * - ``psynet check-constraints``
     - Check that ``constraints.txt`` is up to date with
       ``requirements.txt``; see :doc:`/code/project/dependencies`.
   * - ``psynet debug local``
     - Run the experiment on your computer; see
       :doc:`/code/project/running_and_debugging`.
   * - ``psynet debug ssh --app NAME``
     - Run a debug deployment on a server. It uses the configured
       recruiter, so pilot with ``recruiter = generic``; see
       :doc:`/deploy/running_a_study`.
   * - ``psynet deploy ssh --app NAME``
     - Deploy the experiment for data collection; see
       :doc:`/deploy/running_a_study`. ``--archive`` redeploys from a
       previous export; see :doc:`/deploy/reference/deploy_from_archive`.
   * - ``psynet export local`` / ``ssh``
     - Export the data to ``exports/latest/``; see
       :doc:`/data/exporting_data`.
   * - ``psynet test local``
     - Run the experiment's automated tests with bots; see
       :doc:`/test/backend`.
   * - ``psynet performance-test local`` / ``ssh``
     - Measure how the server copes with many participants; see
       :doc:`/test/scalability`.
   * - ``psynet audit ...``
     - Create, validate and render the experiment audit; see
       :doc:`/test/audit_reference`.
   * - ``psynet estimate``
     - Estimate the completion time and maximum reward
       (see `Estimate maximum reward and completion time (estimate)`_).
   * - ``psynet installation update``
     - Update the installed PsyNet and Dallinger packages
       (see `Update the PsyNet/Dallinger installation (installation update)`_).
   * - ``psynet install autocomplete``
     - Install shell tab completion (see :ref:`shell_completion`).
   * - ``psynet docs show PAGE`` / ``path``
     - Print a documentation page for the installed PsyNet version, or the
       folder that holds every page, for searching (for example with
       ``rg -n -i --no-ignore "<term>" "$(psynet docs path)"``). Page names are the
       website paths without ``.html``, such as
       ``code/participants/payment``.
   * - ``psynet docs demos``
     - Print the folder that holds the demos' code for the installed PsyNet
       version (see :doc:`/demos/index`). Release installs include the demos'
       code and text files, but not their media.

Bundled demos in the PsyNet repository use the repository's development
``.venv``; ``psynet debug`` and ``psynet test`` prepare their boilerplate
automatically. Standalone experiments have their own ``.venv``, prepared with
``psynet setup``.

.. _estimate:

Estimate maximum reward and completion time (``estimate``)
----------------------------------------------------------

``psynet estimate`` examines the timeline and estimates how long a participant
takes and how much they are paid as a result. It is experimental and can be
inaccurate for some timelines, so check the estimates by piloting.

.. _experiment_setup_commands:

Experiment setup and boilerplate
--------------------------------

.. _setup:

Set up an experiment (``setup``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``psynet setup`` is the main path for a **standalone** experiment. Install the
thin PsyNet bootstrap package first (``uv pip install psynet``), then run
setup inside the experiment's dedicated active virtual environment. In order
it:

1. Scaffolds any missing standard experiment files and pins PsyNet. An
   existing bare ``psynet`` line in ``requirements.txt`` is pinned to
   ``psynet[experiment]`` at the active PsyNet installation *before* templates
   are written, so a failed pin never leaves a half-written scaffold; a
   ``requirements.txt`` created by the scaffold is pinned afterwards. (The
   ``[experiment]`` extra is the full runtime; a "bare" requirement is just
   the word ``psynet`` with no version, URL, or extras.)
2. Ensures ``constraints.txt`` (the locked dependency list): reuses it when it
   is already up to date with ``requirements.txt`` or was written by hand,
   otherwise regenerates it (same freshness rule as
   ``psynet check-constraints``).
3. Installs from ``constraints.txt`` with ``uv pip sync`` and verifies with
   ``uv pip check``.
4. Ensures the experiment has a Git repository for deployment. An experiment
   that already sits inside a repository uses it as-is; one that is not in a
   repository (or that its surrounding repository ignores) gets a dedicated
   repository via ``git init``. If Git is not installed, setup continues and
   asks you to install Git and run ``git init`` before debugging or deploying.
5. Softly checks local PostgreSQL/Redis (and may offer to start them with
   Docker). Missing services do not fail setup; use
   ``psynet services ensure`` if you want a hard guarantee before debugging.

.. code:: bash

  uv pip install psynet
  psynet setup

Useful flags:

* ``--no-install`` — do steps 1–2 only (write files and pin; ensure
  constraints when missing or stale; do not install packages). After a
  full ``psynet setup``, use ``psynet debug local --docker`` or a Docker
  deploy command when you want Docker.
* ``--force-shared-env`` — allow installing into the PsyNet repository's
  development ``.venv`` (rarely what you want; can remove packages other
  PsyNet work depends on).
* ``--force-foreign-env`` — allow installing into a virtual environment that
  is not this experiment's ``./.venv`` (for example another project's
  environment). Prefer creating and activating ``./.venv`` instead.

If PsyNet is installed editable, setup asks how to record it in
``requirements.txt``: keep the editable checkout, pin a specific pushed Git
commit URL, or retain an existing explicit requirement. The same choice can be
supplied non-interactively with ``--psynet-source editable``, ``commit``, or
``existing``.

If the active virtual environment is the PsyNet repository's development
``.venv``, setup refuses to install packages by default. Interactively it
offers a numeric menu: create a dedicated ``.venv`` here (recommended),
cancel, write files only, or install into the repository ``.venv`` anyway.

If the active environment is some other foreign virtualenv (not this
experiment's ``./.venv``), setup still scaffolds and writes constraints, but
refuses to ``uv pip sync`` into that environment unless you confirm
interactively or pass ``--force-foreign-env``.

In a demo inside a PsyNet source checkout, ``psynet setup`` only adds the
boilerplate files; it never installs packages or rewrites requirements, so
``--no-install`` isn't needed. It then checks the local services but doesn't
offer to start them in Docker.


.. _services:

Local PostgreSQL and Redis (``services``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Virtualenv ``psynet debug local`` expects PostgreSQL and Redis on localhost
(Dallinger defaults: ports 5432 and 6379).

.. code:: bash

  psynet services check
  psynet services ensure
  psynet services ensure --yes

``check`` only verifies connectivity and exits with an error if either service
is down. ``ensure`` does the same check, then offers to start Docker containers
that publish those host ports (``--yes`` skips the prompt). ``psynet debug``,
``psynet deploy``, and ``psynet test local`` call ``ensure`` automatically
before launch or packaging, including SSH deployments that still prepare the
experiment against local Postgres/Redis on this machine.


.. _scripts:

Manage experiment boilerplate (``scripts``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``psynet scripts`` group is for **file-level** control of standard
boilerplate (Dockerfile, ``deploy.toml``, ``pytest.ini``,
``test.py``, and related templates). Prefer ``psynet setup`` when you also need
a dedicated constrained environment.

.. code:: bash

  psynet scripts --help

``scaffold``
^^^^^^^^^^^^

Create any missing PsyNet boilerplate files. Existing authored files are left
alone. For standalone experiments, also pins a bare ``psynet`` requirement and
generates ``constraints.txt`` when needed (unless ``--skip-constraints``).

.. code:: bash

  psynet scripts scaffold
  psynet scripts scaffold --skip-constraints

``update``
^^^^^^^^^^

Overwrite scaffold-managed boilerplate with the latest templates from the
installed PsyNet version. Existing ``config.txt``, ``README.md``, and
``deploy.toml`` files are preserved. PsyNet-managed Agent Skills under
``.cursor/skills/psynet`` are refreshed; other skill directories under
``.cursor/skills/`` are preserved. Recognized generated ``docker/`` helper
scripts (``docker/psynet``, ``docker/run``, and related files) are deleted;
customized helpers and other files under ``docker/`` are kept. This is **not**
``psynet installation update``.

.. code:: bash

  psynet scripts update

``psynet update-scripts`` remains as a deprecated alias for this command.

``prune``
^^^^^^^^^

Remove scaffold-managed boilerplate and generated leftovers
(``static/assets``, untracked ``constraints.txt``), leaving authored files
such as ``experiment.py`` and ``requirements.txt``.

By default only unmodified, untracked scaffold paths are removed. Git-tracked
managed paths are kept. ``--include-modified`` also removes divergent untracked
scaffold paths. ``--include-tracked`` also removes git-tracked managed paths.
If this directory is a git work tree but tracked files cannot be listed, the
command errors unless ``--include-tracked`` is passed.
Recognized generated ``docker/`` helper scripts are deleted even if they are
git-tracked. Customized copies are preserved.

.. code:: bash

  psynet scripts prune
  psynet scripts prune --include-modified
  psynet scripts prune --include-modified --include-tracked


.. _generate_constraints:

Generate the constraints.txt file (``generate-constraints``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Standalone experiments need a ``constraints.txt`` lockfile so installs and
deploys are reproducible. Prefer ``psynet setup`` when bootstrapping an
experiment; that command creates the lockfile for you.

Use ``psynet generate-constraints`` when you only need to refresh an existing
lockfile after changing ``requirements.txt`` (for example after bumping the
PsyNet version pin):

.. code:: bash

  psynet generate-constraints

This runs Dallinger's standalone constraints script via ``uv run`` (the same
lock policy as ``dallinger constraints generate``). An editable Dallinger
checkout supplies its local script; otherwise PsyNet runs the canonical script
from Dallinger's GitHub repository.


.. _install:

Install PsyNet components (``install``)
---------------------------------------

Install additional PsyNet components and utilities.

.. _install_autocomplete:
.. _shell_completion:

Install shell completion (``install autocomplete``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Shell completion lets you press Tab to complete ``psynet`` commands,
subcommands and options, for example ``psynet debug l<TAB>`` becomes
``psynet debug local``. This command detects your shell (bash or zsh), writes
a completion script to ``~/.local/bin/``, and adds a line that loads it to
``~/.bashrc`` or ``~/.zshrc``:

.. code:: bash

  psynet install autocomplete

In an editable PsyNet installation, running
``./psynet/resources/scripts/install-completion.sh`` from the PsyNet
directory does the same. Restart the terminal, or load the script directly:

.. code-block:: bash

   source ~/.local/bin/.psynet-completion.bash  # for bash
   source ~/.local/bin/.psynet-completion.zsh   # for zsh

If completion doesn't work, check that the script exists
(``ls ~/.local/bin/.psynet-completion.*``), that ``~/.local/bin`` and
``psynet`` are on your ``PATH``, and that your shell configuration file
contains the ``source`` line above.

.. _update:

Update the PsyNet/Dallinger installation (``installation update``)
------------------------------------------------------------------

.. note::

    The following command only applies if you have installed PsyNet in a local
    environment, rather than using Docker.

This command updates the local **installations** of PsyNet and Dallinger
(the packages in your environment). It does **not** refresh experiment
boilerplate files; use ``psynet scripts update`` for that.

While the default is to update both packages, they can also be set to specific
versions (e.g. downgraded) using the ``--psynet-version`` and
``--dallinger-version`` command line options.

.. code:: bash

  psynet installation update

``psynet update`` remains as a deprecated alias for this command.

**Usage**

.. code:: bash

  psynet installation update [OPTIONS]

  Options:
    --dallinger-version TEXT  The git branch, commit or tag of the Dallinger
                              version to install.
    --psynet-version TEXT     The git branch, commit or tag of the psynet
                              version to install.
    --verbose                 Verbose mode
    --help                    Show this message and exit.

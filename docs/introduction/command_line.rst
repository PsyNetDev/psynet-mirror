.. _command_line:

============
Command line
============

Once you have installed PsyNet, you interact with it by running commands in your Unix shell.
Generally speaking, you should execute these commands inside the experiment directory you are
working on.

PsyNet has two common kinds of experiment folder:

* **Bundled demos / test experiments inside the PsyNet repository**
  (for example ``PsyNet/demos/experiments/timeline``). These use the PsyNet
  repository's development ``.venv``. Generated boilerplate is omitted from git
  on purpose; ``debug`` / ``test`` prepare it automatically.
* **Standalone experiments outside the PsyNet repository** (your own project
  copy). These should use a dedicated ``.venv`` in that project directory.
  Run ``psynet setup`` there to prepare files, write ``constraints.txt``, and
  install packages.

Do not treat a bundled demo path as the place to run a full standalone
``psynet setup`` install unless you intentionally want only the lightweight
in-repo preparation.


.. _debug:

Run an experiment in debug mode (``debug``)
-------------------------------------------

The following code runs an experiment in debug mode on your local computer:

.. code:: bash

    psynet debug local

The following code runs an experiment in debug mode on your own web server, via SSH;
this will push the experiment code to Heroku, but won't recruit any participants,
even if your recruiter is set to ``mturk`` or ``prolific``.
Note the specification of an app name.

.. code:: bash

    psynet debug ssh --app my-app-name

This code does the same, but provisioning the web server automatically via the paid service Heroku:

.. code:: bash

    psynet debug heroku --app my-app-name


.. _deploy:

Deploy an experiment (``deploy``)
---------------------------------

This command deploys an experiment, and enable the recruiter so you can collect real data.

.. code:: bash

    psynet deploy ssh --app my-app-name  # for deploying via SSH
    psynet deploy heroku --app my-app-name  # for deploying via Heroku

(Experimental): It is possible to deploy an experiment that resurrects the state of a previous
experiment deployment. To do this you add ``--archive path/to/database.zip`` where
``path/to/database.zip`` is the path to the ``database.zip`` file created by a previous PsyNet export.


.. _estimate:

Estimate maximum reward and completion time (``estimate``)
----------------------------------------------------------

This command examines the timeline, estimates how long the participant will take to complete the experiment,
and how much they need to be paid as a result.

.. code:: bash

    psynet estimate

.. warning::

    This functionality is still experimental and is known to produce inaccurate results
    in certain cases. Always check these estimates manually before finalizing an experiment implementation.


.. _export:

Export data from an experiment (``export``)
-------------------------------------------

This command export data from an experiment. The data is saved by default to ``~/PsyNet-data/export``.

.. code:: bash

    psynet export local
    psynet export ssh --app my-app-name
    psynet export heroku --app my-app-name

To see further options for the export command (e.g. if you want to control the export of assets),
append ``--help`` to these commands:

.. code:: bash

    psynet export local --help
    psynet export ssh --help
    psynet export heroku --help

For more information on PsyNet data export see `Data <../deploy/data.html>`_.


.. _experiment_setup_commands:

Experiment setup and boilerplate
--------------------------------

Recommended commands by goal:

* **Run a bundled demo inside the PsyNet repo:** activate the repository
  ``.venv``, then ``psynet debug local`` (boilerplate is prepared automatically).
* **Start a standalone experiment (virtualenv mode):** in a dedicated project
  ``.venv``, run ``uv pip install psynet`` (thin bootstrap install), then
  ``psynet setup`` (installs the full ``psynet[experiment]`` runtime via
  ``constraints.txt``).
* **Start a standalone experiment (Docker mode):** ``psynet setup --docker``,
  then follow ``docker/docs``.
* **Refresh template files only:** ``psynet scripts update`` (overwrites
  scaffold-managed files; preserves ``config.txt`` / ``README.md``).
* **Refresh dependency locks only:** ``psynet generate-constraints``.
* **Upgrade the installed PsyNet/Dallinger packages:**
  ``psynet installation update`` (not the same as ``psynet scripts update``).
* **Check local PostgreSQL/Redis:** ``psynet services check``.
* **Start missing local services with Docker:** ``psynet services ensure``.


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
   is already up to date with ``requirements.txt``, otherwise regenerates it
   (same freshness rule as ``psynet check-constraints``).
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
  constraints when missing or stale; do not install packages).
* ``--docker`` — same as ``--no-install``, then print Docker next steps
  (follow ``docker/docs``). Prefer this for Docker-mode bootstraps.
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

**Inside bundled demos / test experiments**, ``psynet setup`` always performs
only lightweight file preparation and never installs packages or rewrites
requirements. You do not need ``--no-install`` there; that behavior is
automatic. PsyNet CI scaffolds ignored demo boilerplate before collecting
``test.py``, and the pytest harness restores the authored-only tree afterwards
so later isolated tests are not polluted. After preparation, ``psynet setup``
in demos only **verifies** local services (it does not offer to start Docker
containers).


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
before launch or packaging, including SSH/Heroku paths that still prepare the
experiment against local Postgres/Redis on this machine.


.. _scripts:

Manage experiment boilerplate (``scripts``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``psynet scripts`` group is for **file-level** control of standard
boilerplate (Dockerfile, ``docker/`` helpers, ``pytest.ini``, ``test.py``, and
related templates). Prefer ``psynet setup`` when you also need a dedicated
constrained environment.

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
installed PsyNet version. Existing ``config.txt`` and ``README.md`` files are
preserved. This is **not** ``psynet installation update``.

.. code:: bash

  psynet scripts update

``psynet update-scripts`` remains as a deprecated alias for this command.

``prune``
^^^^^^^^^

Remove scaffold-managed boilerplate and generated leftovers
(``static/assets``, untracked ``constraints.txt``), leaving authored files
such as ``experiment.py`` and ``requirements.txt``.

By default only unmodified, untracked scaffold paths are removed. Git-tracked
managed paths are kept (a directory such as ``docker/`` is kept if any nested
path is tracked). ``--include-modified`` also removes divergent untracked
scaffold paths. ``--include-tracked`` also removes git-tracked managed paths.
If this directory is a git work tree but tracked files cannot be listed, the
command errors unless ``--include-tracked`` is passed.

.. code:: bash

  psynet scripts prune
  psynet scripts prune --include-modified
  psynet scripts prune --include-modified --include-tracked


.. _generate_constraints:

Generate the constraints.txt file (``generate-constraints``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Standalone experiments need a ``constraints.txt`` lockfile so installs and
deploys are reproducible. Prefer ``psynet setup`` (or ``psynet setup --docker``)
when bootstrapping an experiment; that command creates the lockfile for you.

Use ``psynet generate-constraints`` when you only need to refresh an existing
lockfile after changing ``requirements.txt`` (for example after bumping the
PsyNet version pin):

.. code:: bash

  psynet generate-constraints

This runs Dallinger's standalone constraints script via ``uv run`` (the same
lock policy as ``dallinger constraints generate``). An editable Dallinger
checkout supplies its local script; otherwise PsyNet runs the canonical script
from Dallinger's GitHub repository.


Run the experiment's regression test
------------------------------------

This command runs the experiment's regression test, as defined in ``test.py``. This normally involves
running one or more simulated participants through the experiment.

.. code:: bash

  psynet test


.. _performance_test:

Performance test an experiment (``performance-test``)
-----------------------------------------------------

This command measures how your experiment server copes under sustained load. It
keeps a target number of bots running for a fixed duration and reports detailed
latency and throughput statistics.

.. code:: bash

  psynet performance-test local --n-bots 25 --duration-minutes 5
  psynet performance-test ssh --app my-app-name --n-bots 50 --duration-minutes 10

Unlike ``psynet test``, which checks correctness, ``performance-test`` is about
performance under load. For a full guide, including how to sweep several
concurrency levels and how to interpret the results, see the
:ref:`testing experiment performance tutorial <performance_testing>`.


Simulate data for an experiment
-------------------------------

This command generates simulated data for an experiment by running the experiment's regression test
and exporting the resulting data to ``data/simulated_data/``.

.. code:: bash

  psynet simulate
  psynet simulate --audit

``--audit`` also zips that directory to ``./audit/artifacts/simulated_data.zip``
and marks ``simulation_export`` present. Use ``--no-mark-present`` to write the
zip without updating ``audit.json``. Iterate without ``--audit`` when you do
not want the packet's evidence updated.


.. _install:

Install PsyNet components (``install``)
---------------------------------------

Install additional PsyNet components and utilities.

.. _install_autocomplete:

Install shell completion (``install autocomplete``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This command installs shell tab completion for the ``psynet`` command. It automatically
detects your shell and adds the appropriate completion setup to your shell configuration file.

.. code:: bash

  psynet install autocomplete

This is equivalent to running the ``./install-completion.sh`` script manually from the root directory
of an editable PsyNet installation. For more information about shell completion, see :ref:`shell_completion`.

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

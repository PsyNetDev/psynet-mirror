=========================
Creating a new experiment
=========================

If you are using a coding agent, start with
:doc:`/experiment_development/agentic_programming`. This page covers creating
an experiment yourself by copying an existing demo, either from PsyNet's
demos directory or from a fully-fledged experiment repository.

Suppose we've copied the PsyNet demo ``demos/experiments/audio``,
pasted it to a new location on our computer,
and named this new directory ``my-audio``.
It's best if you put this somewhere outside your PsyNet package installation directory;
for example, you could put in a new folder called ``~/psynet-experiments``.
The first step is then to open this directory in your IDE.
Click File > Open in your IDE, then select your project folder.
If asked, click New Window.

The PsyNet demo directories contain authored experiment files and an unpinned
``psynet`` entry in ``requirements.txt``. Generated boilerplate and
``constraints.txt`` are intentionally omitted.

Before you create an experiment environment, make sure these tools are
available on your computer (once per machine):

* **Git** — required so the experiment folder can be a repository
  (``git init``). If you need to install it, follow the instructions on the
  `Git downloads page <https://git-scm.com/downloads>`_. A GUI client is fine;
  PsyNet only needs the ``git`` command to be available in your terminal.
* **uv** — used to create the virtual environment and install packages.
  The usual install is::

      curl -LsSf https://astral.sh/uv/install.sh | sh

  See the `uv installation docs <https://docs.astral.sh/uv/getting-started/installation/>`_
  for other options (Homebrew, pip, …).

Then initialize Git and install the thin PsyNet bootstrap package.
``psynet setup`` then installs the full ``psynet[experiment]`` runtime:

.. code-block:: bash

    git init
    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install psynet


Set up the experiment
---------------------

Let ``psynet setup`` pin the active PsyNet version, generate constraints,
scaffold the experiment, install the constrained dependencies with ``uv``,
and verify the environment:

.. code-block:: bash

    psynet setup

The install step removes packages that are not required by the experiment,
so use a dedicated experiment virtual environment.

.. note::

    Your IDE will typically detect the virtual environment automatically when you open the project.
    If it doesn't, you may need to manually select the virtual environment's Python interpreter in your IDE's settings.
    In most IDEs, you can do this by looking for an interpreter or Python environment selector (often in the bottom-right corner
    or in settings/preferences), and selecting the Python executable from the ``.venv`` folder you just created.

When the process is done, if you open a new terminal window in your IDE, you should see ``(<your-project-name)``
prefixed to the terminal prompt. This indicates that you are in the desired virtual environment.
You should be able to run ``psynet --version`` in this terminal to confirm that you have
successfully installed PsyNet.
You should then be able to run ``psynet debug local`` to launch a local version of your experiment.

If you decide at some point you want to make a fresh virtual environment for a
pre-existing project, create a new virtual environment using the commands above,
select it in your IDE's interpreter settings, then run the same bootstrap as
first-time setup. When ``constraints.txt`` is already present and up to date
with ``requirements.txt``, ``psynet setup`` reuses it and only synchronizes the
environment:

.. code-block:: bash

    uv pip install psynet
    psynet setup

Updating PsyNet
---------------

If you are working from an old experiment, it might be implemented using an older version of PsyNet.
You can see what version of PsyNet it uses by looking inside ``requirements.txt``
for a number that looks like ``10.1.0``. For example, you might see something like this:

::

    psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.1.0#egg=psynet

It's a good idea to check what the latest released version of PsyNet is.
You should be able to see this in the top-left corner of the online documentation website.
Alternatively, you can look at the `CHANGELOG on GitLab <https://gitlab.com/PsyNetDev/PsyNet/-/blob/master/CHANGELOG.md?ref_type=heads>`_.
This CHANGELOG lists the changes that happen with each new version of PsyNet.
You can compare the PsyNet version in your experiment to the latest PsyNet version listed here
to work out how PsyNet has changed in the meantime, and what (if anything) you might need to
change about your experiment in order to make it compatible with the latest PsyNet version.
In general, the rule is that only 'major' version changes should require changes to your experiment.
A major change is signified by the first number in the version tag increasing,
so for example from 10.3.1 to 11.0.0.
If both version tags begin with the same number, then you should probably be fine,
and you can just go ahead and increase the PsyNet version number in ``requirements.txt``.

If you have indeed increased the PsyNet version number, refresh
``constraints.txt`` and your environment with:

.. code:: bash

    psynet setup


Once it is complete, you should be able to run ``psynet debug local`` as before.

You can regenerate any missing standard boilerplate files at any time with:

.. code:: bash

    psynet scripts scaffold

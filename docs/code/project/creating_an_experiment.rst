Creating an experiment
======================

If you are using a coding agent, start with
:doc:`/code/project/agentic_programming` instead.

An experiment can start from an empty directory or from a copy of an existing
experiment. Copying a demo from the PsyNet repository's ``demos`` directory is
usually the quickest start: ``demos/features`` has focused demos of single
building blocks, ``demos/pipelines`` has end-to-end pipelines for common
paradigms, and ``demos/experiments`` has more complete experiments. To
customize an experiment from elsewhere, such as a published experiment
repository, copy it the same way; if it uses an older PsyNet version, see
`Updating PsyNet`_.

Prerequisites
-------------

Install these tools once per machine:

* **Git**, so the experiment folder can be a repository. Follow the
  instructions on the `Git downloads page <https://git-scm.com/downloads>`_.
  A GUI client is fine; PsyNet only needs the ``git`` command to be available
  in your terminal.
* **uv**, to create the virtual environment and install packages. The usual
  install is::

      curl -LsSf https://astral.sh/uv/install.sh | sh

  See the `uv installation docs <https://docs.astral.sh/uv/getting-started/installation/>`_
  for other options (Homebrew, pip, …).

Setting up the experiment
-------------------------

Create or copy the experiment directory somewhere outside your PsyNet
installation, for example in ``~/psynet-experiments/my-audio``. The directory
name must not match an existing Python module, such as ``code``. Open the directory in
your IDE (File > Open, then New Window if asked).

In a terminal in that directory, initialize Git and install the thin PsyNet
bootstrap package:

.. code-block:: bash

    git init
    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install psynet

Then run:

.. code-block:: bash

    psynet setup

``psynet setup`` pins the active PsyNet version in ``requirements.txt``,
generates ``constraints.txt``, scaffolds the standard boilerplate files,
installs the full ``psynet[experiment]`` runtime and other constrained
dependencies with ``uv``, and verifies the environment. In an empty directory
it also creates a starter ``experiment.py`` and ``requirements.txt``. Demos
ship only their authored files and an unpinned ``psynet`` entry in
``requirements.txt``, so a copied demo gets its boilerplate and constraints
here. Commit the generated ``constraints.txt``.

The install step removes packages that the experiment does not require, so
use a dedicated virtual environment for each experiment.

.. note::

    Your IDE usually detects the virtual environment when you open the
    project. If it doesn't, select the Python interpreter in the ``.venv``
    folder in your IDE's interpreter settings (often in the bottom-right corner
    or in settings/preferences).

A new terminal in your IDE should show ``(<your-project-name>)`` before the
prompt, meaning the virtual environment is active. Check the installation with
``psynet --version``, then launch the experiment locally with
``psynet debug local``.

To make a fresh virtual environment for an existing experiment, create and
select it as above, then run the same bootstrap. When ``constraints.txt`` is
present and up to date with ``requirements.txt``, ``psynet setup`` reuses it
and only synchronizes the environment:

.. code-block:: bash

    uv pip install psynet
    psynet setup

To regenerate missing boilerplate files at any time, run:

.. code-block:: bash

    psynet scripts scaffold

Customizing the experiment
--------------------------

Start with simple changes, such as editing the text of a question, then move
on to larger ones. If you ask a coding agent for help, tell it to read the
PsyNet source code rather than guess.

Text changes take effect when you save the file and refresh the browser.
Larger changes, such as changing the stimuli, need a restart: press Ctrl+C in
the terminal, then run ``psynet debug local`` again.

Updating PsyNet
---------------

The PsyNet version an experiment uses is pinned in ``requirements.txt``. A
current pin looks like this:

::

    psynet==13.3.0

Older experiments sometimes used a Git URL instead:

::

    psynet@git+https://gitlab.com/PsyNetDev/PsyNet@v10.1.0#egg=psynet

The latest released version is shown in the top-left corner of the online
documentation. The
`CHANGELOG on GitLab <https://gitlab.com/PsyNetDev/PsyNet/-/blob/master/CHANGELOG.md?ref_type=heads>`_
lists the changes in each version. In general, only major version changes,
where the first number increases (for example from 10.3.1 to 11.0.0), should
require changes to your experiment. If both versions start with the same
number, you can usually just raise the version in ``requirements.txt``. For
upgrades to PsyNet 14, follow :doc:`/whats_new/upgrading_to_psynet_14`.

After changing the version, refresh ``constraints.txt`` and your environment:

.. code-block:: bash

    psynet setup

Then run ``psynet debug local`` again. After a major upgrade, the error
messages usually point to what needs changing.

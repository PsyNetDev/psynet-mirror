.. _quickstart:

Quickstart
==========

This page takes you from an empty folder to an experiment running in your
browser, then hands it to a coding agent. It takes about ten minutes once
the tools in :doc:`install` are in place.

Create an experiment
--------------------

Each experiment lives in its own folder. The folder name must contain only
letters, digits and underscores, must not start with a digit, and must not be
the name of an existing Python module such as ``code`` or ``test``.

.. code-block:: bash

   mkdir chords
   cd chords
   uv venv --python 3.13
   source .venv/bin/activate
   uv pip install psynet
   psynet setup

``psynet setup`` installs the full PsyNet runtime into the folder's
``.venv``, sets up a Git repository, and creates a starter
``experiment.py`` along with the other files an experiment needs, including
instructions for coding agents.

Run it
------

Start the database and cache, then launch the experiment:

.. code-block:: bash

   psynet services ensure
   psynet debug local

``psynet services ensure`` checks for PostgreSQL and Redis and offers to
start them in Docker if they aren't running. ``psynet debug local`` then
opens two browser tabs: the experimenter dashboard, and the experiment as a
participant sees it. For now the experiment is just a welcome page. Press
:kbd:`Ctrl+C` in the terminal to stop it.

Hand it to your agent
---------------------

Open the ``chords`` folder in your coding agent, for example Cursor, Claude
Code or Codex, and describe the study you want. To try it out, you can
paste this:

.. code-block:: text

   Turn this into a PsyNet experiment in which participants rate how
   pleasant 40 chords sound, on a scale from 1 to 7. Synthesize the chords
   so that we don't need recordings. Each participant rates 20 chords, and
   we want about 20 ratings per chord. Test it with simulated participants,
   then tell me how to try it myself.

The agent reads the PsyNet instructions that ``psynet setup`` installed,
proposes a plan, writes the experiment and tests it. When it's done, run
``psynet debug local`` again and take part yourself.

To write the code yourself instead, start with
:doc:`/code/project/creating_an_experiment`. Writing PsyNet code by hand needs
some familiarity with Python (functions, classes and imports), the command
line and Git. If you're new to Python, start with
`Python's Getting Started page <https://www.python.org/about/gettingstarted/>`_.

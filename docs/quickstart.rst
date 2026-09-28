.. _quickstart:

Quickstart
==========

This page takes you from an empty folder to an experiment running in your
browser, then hands it to a coding agent. It takes about ten minutes once
the tools in :doc:`install` are in place.

Create an experiment
--------------------

Each experiment lives in its own folder. The folder name must be a valid
Python name: letters, digits and underscores, not starting with a digit.

.. code-block:: bash

   mkdir chords
   cd chords
   git init
   uv venv --python 3.13
   source .venv/bin/activate
   uv pip install psynet
   psynet setup

``psynet setup`` installs the full PsyNet runtime into the folder's
``.venv``, and creates a starter ``experiment.py`` along with the other files
an experiment needs, including instructions for coding agents.

.. note::

   These instructions are for the upcoming PsyNet release. The version
   currently on PyPI (13.3) doesn't have ``psynet setup`` yet, so until the
   next release, install PsyNet from the ``master`` branch instead:

   .. code-block:: bash

      uv pip install "psynet @ git+https://gitlab.com/PsyNetDev/PsyNet@master"
      psynet setup

   ``psynet setup`` then pins the experiment to that exact commit of
   PsyNet, so the experiment keeps working as ``master`` moves on.

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

To write the code yourself instead, see :doc:`/code/by_hand/index`.

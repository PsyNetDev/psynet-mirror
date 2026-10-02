Starting from a demo or an existing experiment
==============================================

The quickest start is a copy of a demo from the ``demos`` directory of the
`PsyNet repository <https://gitlab.com/PsyNetDev/PsyNet>`_:

- ``demos/features`` has focused demos of single building blocks;
- ``demos/pipelines`` has end-to-end pipelines for common paradigms;
- ``demos/experiments`` has more complete experiments.

``demos/features/pages`` and ``demos/features/timeline`` cover the core
building blocks: info pages, modular pages, prompts, controls, page makers,
code blocks, conditions and loops. :doc:`/demos/index` describes
every demo.

An experiment from elsewhere, such as a published experiment repository, is
set up the same way.

Set up the copy
---------------

The tools in :doc:`/install` must be installed first.

#. Copy the directory to a location outside your PsyNet checkout, for example
   ``~/psynet-experiments/chord_ratings``. The folder name follows the same
   rules as in :doc:`/quickstart`: letters, digits and underscores only, not
   starting with a digit, and not the name of an existing Python module.
#. Open the directory in your IDE and a terminal in it.
#. Install PsyNet into a fresh virtual environment and run ``psynet setup``:

   .. code-block:: bash

      uv venv --python 3.13
      source .venv/bin/activate
      uv pip install psynet
      psynet setup

   PsyNet supports Python 3.11 through 3.14 and recommends Python 3.13.

#. Start the local services and run the experiment:

   .. code-block:: bash

      psynet services ensure
      psynet debug local

Demos ship only their authored files and an unpinned ``psynet`` line in
``requirements.txt``. ``psynet setup`` adds the rest:

- it pins the installed PsyNet version in ``requirements.txt``;
- it generates ``constraints.txt``, or reuses it if it is up to date with
  ``requirements.txt``;
- it adds the boilerplate files described in
  :doc:`/code/project/experiment_directory`;
- it synchronizes the virtual environment with ``constraints.txt``, removing
  packages the experiment does not list, so each experiment needs its own
  ``.venv``;
- it initializes a Git repository if there isn't one.

Commit the generated ``constraints.txt``.

If your IDE doesn't pick up the virtual environment, select the Python
interpreter in ``.venv`` in its interpreter settings.

Set up an existing experiment on another computer
-------------------------------------------------

Clone the repository, then run the same four commands as above.
``psynet setup`` reuses the committed ``constraints.txt`` and only
synchronizes the environment. If the experiment pins an older PsyNet version,
follow :ref:`dependencies_updating_psynet`.

Run demos without copying them
------------------------------

To try several demos before choosing one, clone the PsyNet repository and
install it in editable mode with the demos' dependencies:

.. code-block:: bash

   git clone https://gitlab.com/PsyNetDev/PsyNet.git
   cd PsyNet
   uv venv --python 3.13
   source .venv/bin/activate
   uv pip install -e '.[dev,demos]'

Then start the local services and run a demo from its directory:

.. code-block:: bash

   psynet services ensure
   cd demos/features/timeline
   psynet debug local

All demos share this environment. When a demo inside the repository runs,
PsyNet generates its boilerplate files, which Git ignores, and leaves
``requirements.txt`` unchanged without creating ``constraints.txt``. After
taking a few pages as a participant, open the dashboard's database tab to see
the rows stored for you and your trials.

Restore missing boilerplate
---------------------------

``psynet scripts scaffold`` recreates missing boilerplate files without
touching existing ones. ``psynet scripts update`` overwrites them with the
templates from the installed PsyNet version, except ``config.txt``,
``README.md`` and ``deploy.toml``.

Edit the experiment
-------------------

Start with small changes, such as the text of a question. Text changes
appear when you save the file and refresh the browser. Changes to stimuli or
assets need a restart: press :kbd:`Ctrl+C` in the terminal, then run
``psynet debug local`` again. :doc:`/code/project/running_and_debugging`
covers debug mode in more detail.

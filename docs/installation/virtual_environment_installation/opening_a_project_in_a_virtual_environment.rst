To open a project in your IDE (e.g. a demo), click 'File' > 'Open Folder',
then navigate to the directory containing the project, select the project folder, and click 'Open'.

How you create the virtual environment depends on whether you are working inside
the PsyNet source checkout or on a copied standalone experiment.

Bundled demos inside the PsyNet repository
------------------------------------------

Bundled demos use the shared PsyNet source-checkout environment. They intentionally
omit generated scaffold files and per-demo ``constraints.txt``. From the PsyNet
repository root:

.. code-block:: bash

    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install -e '.[dev,demos]'

Then open the demo directory and run ``psynet debug local``.

Copied demos and other standalone experiments
---------------------------------------------

Copied demos do not ship ``constraints.txt``. You need **Git** and **uv** first
(see :doc:`/tutorials/creating_a_new_experiment` for install links). Initialize
Git and let ``psynet setup`` create the constrained environment:

.. code-block:: bash

    git init
    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install psynet
    psynet setup

``psynet setup`` pins PsyNet, generates ``constraints.txt``, scaffolds boilerplate,
and synchronizes dependencies with ``uv``.

For an experiment that already has ``constraints.txt`` (for example after a
previous ``psynet setup``, or a fully published experiment repo), recreate the
environment with the same bootstrap. Setup reuses an up-to-date lockfile and
synchronizes packages into the new virtual environment:

.. code-block:: bash

    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install psynet
    psynet setup

.. note::

    This workflow creates an isolated virtual environment for each project.
    Your IDE will typically detect the virtual environment automatically when you open the project.
    If it doesn't, you may need to manually select the virtual environment's Python interpreter in your IDE's settings.
    In most IDEs, you can do this by looking for an interpreter or Python environment selector (often in the bottom-right corner
    or in settings/preferences), and selecting the Python executable from the ``.venv`` folder you just created.

If you are working as a PsyNet developer, now is the moment to install PsyNet and Dallinger in development mode.
To do this, run the following commands (assuming you have installed PsyNet and Dallinger in the default locations):

.. code-block:: bash

   uv pip install -e ~/PsyNet
   uv pip install -e ~/Dallinger

Whenever you develop or deploy an experiment using PsyNet (assuming you are not using Docker) you will need to
make sure you are in the appropriate virtual environment.
You can confirm that you are in the correct virtual environment by looking at the start of your terminal prompt.
It should look something like this: ``(my-project) your-name@your-computer-name ~ %``.
If you have only just created your new virtual environment, you might need to open
a new terminal window for your virtual environment to be loaded.
Your virtual environment should activate automatically when you open your project in your IDE;
if it does not (and you are using PyCharm), you can select it by clicking the interpreter box in the bottom right corner of the screen.

Once the required packages have been installed, you should be able to run the experiment
with the following command:

.. code-block:: bash

   psynet debug local

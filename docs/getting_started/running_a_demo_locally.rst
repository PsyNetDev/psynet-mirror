.. _running_a_demo_locally:

Running a demo locally
======================

The goal of this chapter is to run a demo experiment in debug mode on your own computer.
Once you have an experiment running in debug mode, it's easy to make small tweaks
and immediately test the results.

Setting up your environment
---------------------------

Before continuing, make sure you have followed the
:doc:`installation instructions <../installation/index>` for your operating system.

You will then need a local checkout of the PsyNet repository so that you have access to its
demos.

.. code-block:: bash

    git clone https://gitlab.com/PsyNetDev/PsyNet.git
    cd PsyNet

Create a virtual environment and activate it.
We suggest using `uv <https://docs.astral.sh/uv/>`_, but ``python -m venv`` also works.

.. code-block:: bash

    uv venv --python 3.13
    source .venv/bin/activate
    uv pip install -e '.[dev,demos]'

Bundled demos use this shared source-checkout environment. They intentionally
omit generated scaffold files and per-demo constraints.

Choosing a demo
---------------

PsyNet contains many demo experiments in the ``demos`` directory.
These are organized into three main subdirectories:

* ``demos/features/`` - focused demos that each illustrate a single building block of PsyNet.
* ``demos/pipelines/`` - end-to-end experiment pipelines for common paradigms.
* ``demos/experiments/`` - more complete example experiments.

.. admonition:: Two demos to start with
   :class: tip

   If you are new to PsyNet, the two most useful demos to read and run first are
   ``demos/features/pages/`` and ``demos/features/timeline/``. Together they cover
   the core building blocks (info pages, modular pages, prompts, controls,
   page makers, code blocks, conditional logic, loops). They are also the
   companion demos for the :doc:`Pages <pages>` and
   :doc:`Timelines <timelines>` chapters of the tutorial.

Launching a demo
----------------

To run a demo, navigate to its directory and launch it in debug mode:

.. code-block:: bash

    cd demos/features/timeline
    psynet debug local

PsyNet recognizes bundled demos and generates their ignored boilerplate
automatically without changing ``requirements.txt`` or generating constraints.
A copied standalone experiment should instead run ``psynet setup`` and commit
its generated ``constraints.txt``.

.. note::

    Whenever we write a ``cd`` command in this tutorial, we assume you are starting from
    the root of the PsyNet repository. If you have moved away, you can return with
    ``cd path/to/PsyNet``.

.. note::

    ``psynet debug local`` runs on port 5000 by default, which may be occupied
    on macOS systems with AirPlay enabled. If you see an error about the port
    being occupied, you can add ``port = 5001`` (or another port of your choice)
    to your experiment's ``config.txt`` file and try again.

You will need to wait a few seconds for the demo to start.
You may see one or more pop-ups asking whether you want to open an external website;
you should say Yes to these.

If everything works properly, you should see two web pages.
One is a participant interface, looking something like this:

.. image:: ../getting_started/images/participant-interface.png
    :alt: Screenshot showing a participant interface in a PsyNet demo.
    :class: bordered
    :align: center
    :width: 600px

The other is an admin (dashboard) interface, looking something like this:

.. image:: ../getting_started/images/admin-interface.png
    :alt: Screenshot showing an admin interface in a PsyNet demo.
    :class: bordered
    :align: center
    :width: 600px

You can now interact with the demo as if you were a participant.
Try taking a few pages, and check that the pages advance appropriately.
If you want to start a second participant session, you can do this via the admin interface,
clicking the 'New participant' button on the 'Development' tab.

Viewing your data
-----------------

You can use the admin interface to view the data collected from participants.
Once you have taken a few pages yourself, and ideally seen an experiment trial or two,
click the "Database" dropdown in the navbar and then select "Participant".
You should see a table containing one row, which corresponds to you as a participant.
Scroll to the right to see various attributes that have been stored.
If you click again on "Database" you should also see somewhere some variant of "Trial"
(e.g. "CustomTrial"), depending on the experiment you ran.
Click on this, and you should see one row for each trial you've seen so far.

Making changes to the experiment
--------------------------------

Your next task is to try making some minor changes to the experiment code.
For now, just limit yourself to changing the text displayed to the participant.
Look at the participant page currently visible, and try to find the part of the code
that is responsible for displaying it.
Change some of the text, save the file, then refresh the participant page.
You should see the changes you made.

.. note::

    Cosmetic changes to experiment code (e.g. changing display text) can be viewed
    immediately by refreshing the participant page.
    More substantial changes (e.g. adding new stimuli) require you to stop the debug
    session and start a new one.

Shutting down the session
-------------------------

When you are done with your debug session, you can shut it down by pressing
``Ctrl+C`` in the terminal.

Using a local copy of PsyNet or Dallinger
=========================================

An experiment can run against a local checkout of PsyNet or Dallinger, for
example to debug an error inside the library or to try a change before
contributing it.

Clone the repositories into your home directory, keeping their
capitalization:

.. code-block:: bash

    cd ~
    git clone https://gitlab.com/PsyNetDev/PsyNet
    git clone https://github.com/Dallinger/Dallinger

Use a local PsyNet
------------------

In the experiment directory, with its virtual environment active, install
the checkout in editable mode and rerun setup:

.. code-block:: bash

    uv pip install -e ~/PsyNet
    psynet setup --psynet-source editable

``requirements.txt`` then points at the checkout, and changes to the PsyNet
source take effect the next time you run the experiment. Without
``--psynet-source``, ``psynet setup`` asks how to record the editable PsyNet
unless ``requirements.txt`` already points at it.

A deployment server can't install from your local checkout. Before
deploying, push your PsyNet branch and pin its current commit:

.. code-block:: bash

    psynet setup --psynet-source commit

This writes a Git URL for the checkout's current commit, using its
``origin`` remote, so a branch on a fork works too. Uncommitted changes in
the checkout are not included. :ref:`dependencies_updating_psynet` shows the
format for pinning a branch or tag by hand.

Use a local Dallinger
---------------------

Install the checkout after ``psynet setup``:

.. code-block:: bash

    uv pip install -e ~/Dallinger

``psynet setup`` synchronizes the environment with ``constraints.txt`` and
so replaces the editable Dallinger with the pinned version. Reinstall it
after each ``psynet setup``.

To deploy with a Dallinger branch, push it and add a pin to
``requirements.txt``, then run ``psynet setup``:

::

    dallinger@git+https://github.com/<your-username>/Dallinger@<branch-name>#egg=dallinger

Contribute a change
-------------------

Members of the PsyNet or Dallinger projects push a branch to the main
repository and open a merge request (GitLab) or pull request (GitHub) from
it. Others fork the repository first. For PsyNet, follow
:doc:`/developer/contributing_a_feature_or_bugfix`.

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
the checkout are not included. Setup also installs PsyNet from that commit,
replacing the editable install, so rerun
``psynet setup --psynet-source editable`` to resume local development.
A commit is not a release, so ``psynet deploy ssh`` and
``psynet deploy heroku`` ask you to confirm before launching it.
:ref:`dependencies_updating_psynet` shows the format for pinning a branch or
tag by hand.

To try the checkout on a server without pinning or pushing it, including
uncommitted changes, launch a debug deployment that builds it into the
image:

.. code-block:: bash

    psynet debug ssh --app my-test --use-local-psynet

``psynet performance-test ssh`` takes the same option for the app it
deploys. The experiment's ``Dockerfile`` must be recent enough to install
the wheel; if PsyNet says it isn't, run ``psynet scripts update``. See
:doc:`/deploy/reference/ssh_server` for details. ``psynet deploy`` does not
offer this, so live deployments always use a pin.

Use a local Dallinger
---------------------

In the experiment directory, with its virtual environment active, install
the checkout in editable mode:

.. code-block:: bash

    uv pip install -e ~/Dallinger

``psynet setup`` keeps this editable Dallinger. It synchronizes the
environment with ``constraints.txt`` and then reinstalls the checkout, which
also installs any new dependencies the checkout needs.
``requirements.txt`` and ``constraints.txt`` still record PsyNet's own
Dallinger pin, so deployments use that pinned version, not your checkout.

``psynet setup --psynet-source commit`` is the exception: it replaces the
editable Dallinger with the pinned version. Run
``uv pip install -e ~/Dallinger`` afterwards to resume local development.

To deploy with a Dallinger branch, push it and add a pin to
``requirements.txt``, then run ``psynet setup``:

::

    dallinger@git+https://github.com/<your-username>/Dallinger@<branch-name>#egg=dallinger

For a debug deployment, ``psynet debug ssh --use-local-dallinger`` builds the
editable checkout into the image instead, together with any new dependencies
it needs. See :doc:`/deploy/reference/ssh_server` for details.

Contribute a change
-------------------

Members of the PsyNet or Dallinger projects push a branch to the main
repository and open a merge request (GitLab) or pull request (GitHub) from
it. Others fork the repository first. For PsyNet, follow
:doc:`/developer/contributing_a_feature_or_bugfix`.

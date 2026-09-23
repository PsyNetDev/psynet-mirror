Download the PsyNet repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

We recommend downloading the PsyNet repository so that you can access its collection
of built-in demos and explore the source code. However, you do not need to download it
for running your own experiments.

We recommend downloading PsyNet to your home directory if possible, there are
some PsyNet features that run smoother if it is located there.

.. code-block:: bash

   cd
   git clone https://gitlab.com/PsyNetDev/PsyNet

You can then find the PsyNet demos within the ``demos`` directory.

By default this will download the latest version of PsyNet's master branch,
but new versions are released regularly.
To get the latest version, run the following:

.. code-block:: bash

   cd ~/PsyNet
   git pull

If you want to ensure that this version of PsyNet is exactly the same as the
one that your experiment will use, you can check out a specific version of PsyNet like this:

.. code-block:: bash

   cd ~/PsyNet
   git checkout v10.4.0

where 10.4.0 matches the PsyNet version number specified in the experiment's
``requirements.txt`` file.

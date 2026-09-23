.. _deploy_from_archive:
.. highlight:: shell

======================
Deploying from archive
======================

Sometimes it's useful to redeploy a PsyNet experiment on the basis of previously exported data.
Perhaps you had to shut down the experiment server due to some problem which you've now fixed.
It's easy to do this with PsyNet. First, look for an ``export.zip`` from a previous
export, or the extracted ``database/`` directory inside an export folder.
Then run the same deploy command as you normally would, but pass that path using
the ``--archive`` option:

.. code:: bash

    psynet deploy ssh --app my-experiment --archive export.zip
    # or: --archive path/to/database
    # or: --archive path/to/extracted/export

.. note::

    Prepend ``docker/`` to these commands if you are running PsyNet within Docker.
    In this case you will need to put your archive inside your experiment directory
    so that Docker can see it properly.

Only the table CSVs under ``database/`` are sent to the server. PsyNet re-packs
whatever you pass to ``--archive`` before deploying it, so the recruiter
identifier sidecars and any exported asset files in an ``export.zip`` stay on
your computer.

When you deploy an experiment in this way, PsyNet will use the latest version of the code that you
have in your current experiment directory. This means that you can use this opportunity to address small
bugs in your code. Note that the database structure is, however, sensitive to what PsyNet version you use.
It's a bad idea however to upgrade PsyNet versions in between exporting and deploying from archive,
unless you're sure what you're doing.
Note also that the experiment deployment will reuse any assets you uploaded previously;
it's currently not supported to change your asset generation code and redeploy to obtain new assets.

It's also possible to debug an experiment using a previously exported archive using analogous logic.
For example, the following command runs a local debug experiment based on ``export.zip``:

.. code:: bash

    psynet debug local --archive export.zip

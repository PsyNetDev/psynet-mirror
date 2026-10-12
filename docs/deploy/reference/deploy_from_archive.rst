.. _deploy_from_archive:
.. highlight:: shell

======================
Deploying from archive
======================

A PsyNet experiment can be redeployed with the data from an earlier export,
for example after the server was shut down because of a problem that you have
since fixed. Pass the export to the usual deploy command with ``--archive``:

.. code:: bash

    psynet deploy ssh --app my-experiment --archive exports/latest
    # or: --archive export.zip
    # or: --archive path/to/database

``psynet export`` writes the export to ``exports/latest/`` in the experiment
directory, and the dashboard's Export tab downloads it as ``export.zip``.
``--archive`` also accepts the ``database/`` directory itself.

Only the table CSVs under ``database/`` are sent to the server. PsyNet re-packs
whatever you pass to ``--archive`` before deploying it, so the recruiter
identifier sidecars and any exported asset files in an ``export.zip`` stay on
your computer.

The deployment uses the code currently in your experiment directory, so you
can fix small bugs before redeploying. The database structure depends on the
PsyNet version, so don't upgrade PsyNet between exporting and redeploying
unless you know that the structure hasn't changed. The deployment reuses the
assets uploaded previously; changing the asset generation code and
redeploying does not create new assets.

``psynet debug`` accepts ``--archive`` in the same way, for example:

.. code:: bash

    psynet debug local --archive export.zip

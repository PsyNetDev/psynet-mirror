Local deployments
=================

Use a local deployment when collecting data on a computer in a laboratory or
in the field. Unlike disposable local debugging, every local deployment has a
required ID:

.. code-block:: bash

    psynet deploy local --id gibbs

The ID contains lowercase letters, digits, and dashes. It is scoped to the
experiment directory and identifies a history of database snapshots under
``data/snapshots/<id>/``.

Managed local snapshots currently support the standard and ``--legacy`` local
runners, but not ``--docker``.

Only one local experiment can use the shared PostgreSQL database at a time.
Starting a second ``psynet deploy local`` while another is still running
asks you to stop the running experiment first. Sequential launches after a
normal stop do not hit this error; they offer the previous snapshot history
instead.

Snapshots
---------

PsyNet creates a database snapshot when a participant finishes, every ten
minutes if the response table has grown since the last snapshot, after a
normal shutdown (when needed), and before resetting the local database to
start another experiment. Snapshots are private, non-anonymized recovery
files for resuming on the same machine. They do not include assets or
replace a full :ref:`data export <data>`.

The ten-minute timer does not write an archive when no new row has been
added to the ``response`` table. Long-running experiments therefore do not
accumulate identical backups during quiet periods.

Finish-time snapshots are on by default for managed local live deployments.
Disable them in ``config.txt`` or ``Experiment.config`` if they are too costly
on the machine you are using::

    snapshot_on_participant_finish = false

If the last snapshot was taken because a participant finished, and no later
participant started, PsyNet skips the shutdown snapshot. There is no new
collected data to save. Shutdown still snapshots when a participant is in
progress, when finish-time snapshots are disabled, or when nobody has finished
yet.

Running the same command again displays the ten most recent snapshots and asks
which one to resume. The latest is selected by default. Scripts can bypass the
prompt:

.. code-block:: bash

    psynet deploy local --id gibbs --snapshot latest
    psynet deploy local --id gibbs --snapshot 4

Before resetting the shared local PostgreSQL database, PsyNet checks whether it
contains an interrupted managed deployment. If so, PsyNet saves a recovery
snapshot in the owning experiment directory. A failed recovery prevents the
new deployment from starting.

A database left behind by ``psynet debug local`` is discarded without
prompting, because debugging runs are disposable. The same applies to a
database that was only prepared and never launched.

A local database from a live or sandbox run that PsyNet cannot account for,
such as one created before this snapshot system, is never discarded silently.
Adopt it explicitly after checking that the current experiment directory
contains the matching source:

.. code-block:: bash

    psynet deploy local --id gibbs --adopt-existing

Deployment history
------------------

Local deploy and snapshot events are recorded in
``data/deployment-events.jsonl``. The same file also covers remote deploy,
sandbox, export, destroy, and operator comments. See
:doc:`history` for ``--comment``, ``psynet comment``, and
``psynet history``.
